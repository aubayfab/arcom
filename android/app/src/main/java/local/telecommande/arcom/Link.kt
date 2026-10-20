package local.telecommande.arcom

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothProfile
import android.bluetooth.BluetoothStatusCodes
import android.os.Build
import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import java.io.IOException

enum class LinkStatus { DISCONNECTED, CONNECTING, WAITING, CONNECTED, ERROR }

/** [ms] : durée totale, connexion comprise ; [reversed] : STOP envoyé avant d'inverser un store. */
class CommandResult(val ms: Long, val reversed: Boolean)

/**
 * Liaison BLE avec un module (équivalent de Link dans server.py).
 *
 * Tout s'exécute sur le thread principal ; les rappels GATT, qui arrivent d'un autre thread, ne font
 * que compléter des Deferred ou poster sur le thread principal.
 *
 * - Par défaut, chaque commande se connecte (3,5 à 5,5 s, le temps que le module émette une
 *   annonce), écrit, puis libère le module : il reste libre pour un autre appareil (un module
 *   n'accepte qu'une liaison). Un appui maintenu (variation, lames) garde la liaison jusqu'à son stop.
 * - « Maintenir la connexion » : liaison tenue entre les commandes, jusqu'à « Se déconnecter ».
 * - « Connexion auto » : liaison permanente ; hors de portée, autoConnect (Android attend le module
 *   à faible consommation).
 * - Écriture avec accusé, comme l'app d'origine : la trame part au même événement de connexion
 *   qu'une écriture sans accusé, et une liaison morte est détectée au lieu d'avaler les commandes.
 * - Pas de requestConnectionPriority : le module réclame 150–300 ms et raccroche au bout de
 *   30–40 s si on lui impose plus rapide (constaté sous Windows, cf. README).
 */
@SuppressLint("MissingPermission") // Arcom vérifie BLUETOOTH_CONNECT avant toute opération
class Link(val mac: String) {
    var status = LinkStatus.DISCONNECTED
        private set
    var error: String? = null
        private set
    var hvac: Hvac? = null
        private set

    /** Durée de la dernière écriture, hors connexion. */
    var lastMs: Long? = null
        private set

    /** « Maintenir la connexion » : liaison tenue jusqu'à « Se déconnecter ». */
    var held = false

    /** Commandes en cours : sans maintien, la liaison n'est libérée qu'après la dernière. */
    private var pending = 0

    /** Début d'un appui maintenu (variation, lames), en attente de son « stop ». */
    private var gesture: Long? = null
    private val readLock = Mutex() // la libération attend la relecture d'état en cours

    private val blind = HashMap<Int, Pair<Direction, Long>>() // groupe -> (sens, début de course)
    private var session: Session? = null
    private var opening: Session? = null // connexion GATT de la tentative en cours
    private var attempt: Deferred<Session>? = null
    private var attemptAuto = false
    private var retryAt = 0L
    private var backoff = BACKOFF_MIN_MS
    private val commandLock = Mutex() // les commandes partent dans l'ordre (ex. « + » puis « stop »)

    val alive: Boolean get() = session?.alive == true
    private val module: ModuleInfo? get() = Arcom.registry.get(mac)
    private val name: String get() = module?.displayName ?: mac

    /** « Connexion auto » : connecté en permanence, pas de déconnexion possible. */
    val auto: Boolean get() = module?.autoConnect == true

    /** Liaison gardée entre les commandes (« Maintenir la connexion », implicite en connexion auto). */
    val keep: Boolean get() = auto || module?.keepConnected == true

    /** Liaison à tenir, et à rétablir si elle tombe. */
    val wanted: Boolean get() = auto || (keep && held)
    private val busy: Boolean get() = pending > 0 || gesture != null

    private fun setStatus(value: LinkStatus, message: String? = null) {
        status = value
        error = message
        Arcom.changed()
    }

    // --- Connexion ---------------------------------------------------------------------------

    suspend fun connect() {
        ensure()
    }

    /** Session prête ; partage la tentative directe en cours, remplace une attente autoConnect. */
    private suspend fun ensure(): Session {
        session?.takeIf { it.alive }?.let { return it }
        val running = attempt?.takeIf { it.isActive && !attemptAuto }
        return (running ?: startAttempt(auto = false)).await()
    }

    private fun startAttempt(auto: Boolean): Deferred<Session> {
        cancelAttempt()
        val job = Arcom.scope.async {
            setStatus(if (auto) LinkStatus.WAITING else LinkStatus.CONNECTING)
            val t0 = SystemClock.elapsedRealtime()
            try {
                val s = open(auto)
                session = s
                backoff = BACKOFF_MIN_MS
                Log.i(Arcom.TAG, "$name : connecté en ${SystemClock.elapsedRealtime() - t0} ms")
                setStatus(LinkStatus.CONNECTED)
                Arcom.scope.launch { refresh() }
                Arcom.scope.launch { release() } // réglage désactivé pendant la connexion : plus voulue
                s
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                retryAt = SystemClock.elapsedRealtime() + backoff
                backoff = (backoff * 2).coerceAtMost(BACKOFF_MAX_MS)
                Log.w(Arcom.TAG, "$name : échec de connexion (${e.message})")
                setStatus(LinkStatus.ERROR, e.message)
                throw e
            }
        }
        attempt = job
        attemptAuto = auto
        job.invokeOnCompletion { if (attempt === job) attempt = null }
        return job
    }

    private suspend fun open(auto: Boolean): Session {
        val adapter = Arcom.adapter?.takeIf { it.isEnabled } ?: throw IOException("Bluetooth désactivé")
        val device = adapter.getRemoteDevice(mac)
        var last: Exception? = null
        repeat(if (auto) 1 else 2) { // 2e essai : l'erreur 133 de la pile Android est fréquente
            val s = Session()
            val gatt = device.connectGatt(Arcom.context, auto, s, BluetoothDevice.TRANSPORT_LE)
            if (gatt == null) {
                last = IOException("connexion refusée par Android")
                return@repeat
            }
            s.gatt = gatt
            opening = s
            try {
                if (auto) {
                    s.ready.await()
                } else {
                    withTimeoutOrNull(CONNECT_TIMEOUT_MS) { s.ready.await() }
                        ?: throw IOException("module injoignable (hors de portée ?)")
                }
                return s
            } catch (e: CancellationException) {
                s.close()
                throw e
            } catch (e: Exception) {
                s.close()
                last = e
            } finally {
                if (opening === s) opening = null
            }
            delay(RETRY_PAUSE_MS) // laisser la pile libérer la tentative précédente
        }
        throw last ?: IOException("connexion impossible")
    }

    /** Liaison voulue (connexion auto, ou maintien) : la rétablit si besoin. */
    fun maintain() {
        if (!wanted || alive || attempt?.isActive == true) return
        if (!Arcom.bluetoothOn || !Permissions.canConnect(Arcom.context)) return // repris à l'autorisation / au rallumage
        if (SystemClock.elapsedRealtime() < retryAt) return
        Arcom.scope.launch {
            try {
                ensure()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // Hors de portée : Android guette le module et s'y connecte dès qu'il réapparaît.
                if (wanted && !alive && attempt?.isActive != true) startAttempt(auto = true)
            }
        }
    }

    /**
     * Annule la tentative en cours et ferme sa connexion GATT tout de suite : sinon elle ne le
     * serait qu'au prochain tour de la boucle principale, et deux clients viseraient le module.
     */
    private fun cancelAttempt() {
        attempt?.cancel()
        attempt = null
        opening?.close()
        opening = null
    }

    fun drop() {
        cancelAttempt()
        session?.let {
            session = null
            it.close()
        }
        setStatus(LinkStatus.DISCONNECTED)
    }

    /** Libère le module s'il n'a pas à rester connecté et que rien n'est en cours. */
    suspend fun release() {
        if (wanted || busy || !alive) return
        readLock.withLock { // après la relecture d'état lancée à la connexion
            if (!wanted && !busy && alive) {
                Log.i(Arcom.TAG, "$name : libéré")
                drop()
            }
        }
    }

    /** Entretien périodique : rétablit la liaison voulue, entretient la liaison tenue, libère les autres. */
    fun tick(now: Long) {
        expireBlind()
        if (gesture?.let { now - it > HOLD_MAX_MS } == true) gesture = null // « stop » jamais reçu
        when {
            alive && wanted -> Arcom.scope.launch { refresh() }
            alive -> Arcom.scope.launch { release() }
            else -> maintain()
        }
    }

    private fun discard(s: Session) {
        if (session === s) {
            session = null
            setStatus(LinkStatus.DISCONNECTED)
        }
        s.close()
    }

    private fun onLost(s: Session) {
        if (session !== s) return // tentative en cours : open() s'en occupe
        Log.i(Arcom.TAG, "$name : déconnecté")
        discard(s)
        if (wanted) {
            Arcom.scope.launch {
                delay(RECONNECT_DELAY_MS)
                maintain()
            }
        }
    }

    // --- Commandes ---------------------------------------------------------------------------

    suspend fun command(cmd: Command, pin: String): CommandResult {
        val frames = ArrayList<Pair<ByteArray, Long>>()
        val direction = (cmd as? Command.Blind)?.action?.direction
        val now = SystemClock.elapsedRealtime()
        val reversing = cmd is Command.Blind && direction != null && groupsOf(cmd.groups).any { g ->
            blind[g]?.let { (d, since) -> d != direction && now - since < BLIND_MOTION_TTL_MS } == true
        }
        if (reversing) {
            // Inverser un moteur en pleine course : STOP, temps mort, puis l'autre sens.
            val stop = Command.Blind(BlindAction.STOP, (cmd as Command.Blind).groups)
            frames += Protocol.frame(stop.code, pin) to BLIND_REVERSE_PAUSE_MS
        }
        frames += Protocol.frame(cmd.code, pin) to 0L

        if (keep) held = true
        val t0 = SystemClock.elapsedRealtime()
        pending++
        val writeMs = try {
            write(frames)
        } finally {
            pending--
        }

        if (cmd is Command.Blind) {
            for (g in groupsOf(cmd.groups)) {
                if (direction != null) blind[g] = direction to SystemClock.elapsedRealtime() else blind.remove(g)
            }
        }
        if (cmd is Command.Light || cmd is Command.Blind) gesture = if (cmd.startsHold) SystemClock.elapsedRealtime() else null
        lastMs = writeMs
        val ms = SystemClock.elapsedRealtime() - t0
        Log.i(Arcom.TAG, "$name : ${frames.joinToString(" puis ") { it.first.hex() }} ($ms ms)")
        Arcom.changed()
        Arcom.scope.launch { settle(cmd.isHvac) }
        return CommandResult(ms, reversing)
    }

    /** Écrit les trames dans l'ordre (une liaison morte est rétablie une fois) ; renvoie la durée d'écriture. */
    private suspend fun write(frames: List<Pair<ByteArray, Long>>): Long = commandLock.withLock {
        for (n in 1..2) {
            val s = ensure()
            val w0 = SystemClock.elapsedRealtime()
            try {
                for ((data, pause) in frames) {
                    s.write(data)
                    if (pause > 0) delay(pause)
                }
                return@withLock SystemClock.elapsedRealtime() - w0
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.w(Arcom.TAG, "$name : écriture impossible (${e.message})")
                discard(s)
                if (n == 2) throw e
            }
        }
        error("inaccessible")
    }

    /** Après une commande : relit l'état CVC une fois répercuté, puis libère le module si besoin. */
    private suspend fun settle(hvac: Boolean) {
        if (hvac) {
            pending++ // la liaison attend la relecture
            try {
                delay(HVAC_REFLECT_MS)
                refresh()
            } finally {
                pending--
            }
        }
        release()
    }

    /** Sens de la course en cours (la plus récente), null si à l'arrêt ou supposé en butée. */
    fun blindDirection(groups: Set<Int> = emptySet()): Direction? {
        val now = SystemClock.elapsedRealtime()
        return groupsOf(groups).mapNotNull { blind[it] }
            .filter { now - it.second < BLIND_MOTION_TTL_MS }
            .maxByOrNull { it.second }?.first
    }

    fun expireBlind() {
        val now = SystemClock.elapsedRealtime()
        if (blind.values.removeAll { now - it.second >= BLIND_MOTION_TTL_MS }) Arcom.changed()
    }

    /** Relit l'état CVC ; sert aussi de keep-alive, comme dans l'app d'origine. */
    suspend fun refresh() {
        val s = session?.takeIf { it.alive } ?: return
        try {
            val state = readLock.withLock { Hvac.parse(s.read()) }
            if (state != hvac) {
                hvac = state
                Arcom.changed()
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            if (session !== s) return // libérée entre-temps (« Se déconnecter », Bluetooth coupé…)
            Log.i(Arcom.TAG, "$name : lecture d'état impossible (${e.message}), liaison abandonnée")
            discard(s)
            maintain()
        }
    }

    // --- Session GATT --------------------------------------------------------------------------

    /** Une connexion GATT. Un objet par tentative : les rappels d'une ancienne liaison sont ignorés. */
    private inner class Session : BluetoothGattCallback() {
        @Volatile
        var gatt: BluetoothGatt? = null
        val ready = CompletableDeferred<Unit>()

        @Volatile
        private var up = false

        @Volatile
        private var lost = false

        @Volatile
        private var op: CompletableDeferred<Pair<Int, ByteArray?>>? = null
        private val opLock = Mutex() // Android n'accepte qu'une opération GATT à la fois
        private var writeChar: BluetoothGattCharacteristic? = null
        private var readChar: BluetoothGattCharacteristic? = null

        val alive: Boolean get() = up && !lost && gatt != null

        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS && newState == BluetoothProfile.STATE_CONNECTED) {
                Arcom.main.post {
                    if (!lost && gatt != null && !g.discoverServices()) fail(IOException("découverte des services refusée"))
                }
            } else {
                fail(IOException(gattError(status)))
                Arcom.main.post { onLost(this) }
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            val w = g.getService(Protocol.SVC_COMMAND)?.getCharacteristic(Protocol.WRITE_COMMAND)
            if (status != BluetoothGatt.GATT_SUCCESS || w == null) {
                fail(IOException("service de commande introuvable"))
                return
            }
            writeChar = w
            readChar = g.getService(Protocol.SVC_STATE)?.getCharacteristic(Protocol.READ_STATE)
            up = true
            ready.complete(Unit)
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            op?.complete(status to null)
        }

        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray, status: Int) {
            op?.complete(status to value)
        }

        @Deprecated("Android 12 et avant")
        @Suppress("DEPRECATION")
        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            op?.complete(status to c.value)
        }

        private fun fail(e: IOException) {
            lost = true
            ready.completeExceptionally(e)
            op?.completeExceptionally(e)
        }

        suspend fun write(data: ByteArray) {
            val c = writeChar ?: throw IOException("liaison non prête")
            exchange(WRITE_TIMEOUT_MS) { writeTo(it, c, data) }
        }

        suspend fun read(): ByteArray? {
            val c = readChar ?: return null
            return exchange(READ_TIMEOUT_MS) { it.readCharacteristic(c) }
        }

        private suspend fun exchange(timeoutMs: Long, start: (BluetoothGatt) -> Boolean): ByteArray? = opLock.withLock {
            val g = gatt?.takeIf { !lost } ?: throw IOException("liaison fermée")
            val pending = CompletableDeferred<Pair<Int, ByteArray?>>()
            op = pending
            try {
                if (!start(g)) throw IOException("opération refusée par Android")
                val (status, value) = withTimeoutOrNull(timeoutMs) { pending.await() }
                    ?: throw IOException("pas de réponse du module")
                if (status != BluetoothGatt.GATT_SUCCESS) throw IOException(gattError(status))
                value
            } finally {
                op = null
            }
        }

        fun close() {
            fail(IOException("liaison fermée"))
            val g = gatt ?: return
            gatt = null
            try {
                g.disconnect()
            } catch (_: Exception) {
            }
            g.close()
        }
    }

    companion object {
        private const val CONNECT_TIMEOUT_MS = 15_000L
        private const val WRITE_TIMEOUT_MS = 3_000L
        private const val READ_TIMEOUT_MS = 5_000L
        private const val RETRY_PAUSE_MS = 300L
        private const val RECONNECT_DELAY_MS = 1_000L
        private const val BACKOFF_MIN_MS = 2_000L
        private const val BACKOFF_MAX_MS = 60_000L
        private const val HVAC_REFLECT_MS = 1_500L        // aller-retour régulateur avant que …c69 change
        private const val BLIND_REVERSE_PAUSE_MS = 500L   // temps mort moteur entre STOP et le sens opposé
        private const val BLIND_MOTION_TTL_MS = 120_000L  // au-delà, le store est supposé en butée
        private const val HOLD_MAX_MS = 30_000L           // appui maintenu dont le « stop » n'arrive pas

        private fun groupsOf(groups: Set<Int>): Set<Int> = groups.ifEmpty { setOf(1, 2, 3, 4) }

        @Suppress("DEPRECATION")
        private fun writeTo(g: BluetoothGatt, c: BluetoothGattCharacteristic, data: ByteArray): Boolean =
            if (Build.VERSION.SDK_INT >= 33) {
                g.writeCharacteristic(c, data, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == BluetoothStatusCodes.SUCCESS
            } else {
                c.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                c.value = data
                g.writeCharacteristic(c)
            }

        private fun gattError(status: Int): String = when (status) {
            BluetoothGatt.GATT_SUCCESS -> "liaison fermée par le module"
            8 -> "délai de liaison dépassé (module hors de portée ?)"
            19 -> "liaison fermée par le module"
            133 -> "module injoignable (erreur 133)"
            else -> "erreur Bluetooth $status"
        }
    }
}
