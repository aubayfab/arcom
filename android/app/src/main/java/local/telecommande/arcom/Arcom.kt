package local.telecommande.arcom

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.location.LocationManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File
import java.io.IOException

/**
 * État de l'application, partagé par l'interface, les widgets et le service (équivalent du Manager
 * de server.py). Tout se passe sur le thread principal.
 */
@SuppressLint("StaticFieldLeak", "MissingPermission") // contexte d'application ; autorisations vérifiées
object Arcom {
    const val TAG = "Arcom"
    private const val KEEPALIVE_MS = 10_000L
    private const val SCAN_MS = 8_000L
    const val NUDGE_MS = 700L                // variation brève (widgets) : + ou − pendant 0,7 s

    lateinit var context: Context
        private set
    lateinit var registry: Registry
        private set
    val main = Handler(Looper.getMainLooper())
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val links = HashMap<String, Link>()

    /** Incrémenté à chaque changement : interface, notification et service s'y abonnent. */
    val changes = MutableStateFlow(0)
    var scanning = false
        private set

    /** Commandes de widget en cours : le service doit tenir jusqu'à leur fin. */
    var busy = 0

    fun init(ctx: Context) {
        if (::context.isInitialized) return
        context = ctx.applicationContext
        registry = Registry(File(context.filesDir, "modules.json"))
        // Diffusion système protégée : aucun autre appli ne peut l'émettre, pas besoin de drapeau.
        context.registerReceiver(object : BroadcastReceiver() {
            override fun onReceive(c: Context, intent: Intent) {
                when (intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, -1)) {
                    BluetoothAdapter.STATE_OFF -> links.values.forEach { it.drop() }
                    BluetoothAdapter.STATE_ON -> wake()
                }
                changed()
            }
        }, IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED))
        scope.launch { maintenance() }
    }

    val adapter: BluetoothAdapter?
        get() = context.getSystemService(BluetoothManager::class.java)?.adapter
    val bluetoothOn: Boolean get() = adapter?.isEnabled == true

    fun link(mac: String): Link = links.getOrPut(mac.uppercase()) { Link(mac.uppercase()) }
    fun linkOrNull(mac: String): Link? = links[mac.uppercase()]

    fun changed() {
        changes.value += 1
        LinkService.sync(context)
    }

    /** Le service de premier plan garde le processus (et donc les liaisons) en vie. */
    fun needsService(): Boolean {
        if (busy > 0) return true
        if (!Permissions.canConnect(context)) return false
        val active = setOf(LinkStatus.CONNECTING, LinkStatus.WAITING, LinkStatus.CONNECTED)
        return links.values.any { it.status in active || it.wanted } ||
            registry.modules.values.any { it.autoConnect }
    }

    /** Toutes les 10 s : (re)connecte ce qui doit l'être, entretient les liaisons tenues, libère les autres. */
    private suspend fun maintenance() {
        while (true) {
            if (bluetoothOn && Permissions.canConnect(context)) {
                val now = SystemClock.elapsedRealtime()
                for (m in registry.modules.values.toList()) link(m.mac).tick(now)
            }
            delay(KEEPALIVE_MS)
        }
    }

    /** Rétablit tout de suite les liaisons voulues (ouverture de l'appli, Bluetooth rallumé…). */
    fun wake() {
        if (!bluetoothOn || !Permissions.canConnect(context)) return
        for (m in registry.modules.values) link(m.mac).maintain()
    }

    // --- Commandes -----------------------------------------------------------------------------

    private fun checkReady() {
        if (!Permissions.canConnect(context)) throw IOException("autorisation Bluetooth manquante")
        if (!bluetoothOn) throw IOException("Bluetooth désactivé")
    }

    suspend fun command(mac: String, cmd: Command): CommandResult {
        val m = registry.get(mac) ?: throw IOException("module inconnu")
        checkReady()
        return link(m.mac).command(cmd, m.pin)
    }

    /** Clic sur ▲/▼ : lance la course, ou l'arrête si elle va déjà dans ce sens (comme l'app d'origine). */
    suspend fun blindTap(mac: String, direction: Direction, groups: Set<Int> = emptySet()): Pair<BlindAction, CommandResult> {
        val action = when {
            link(mac).blindDirection(groups) == direction -> BlindAction.STOP
            direction == Direction.UP -> BlindAction.UP
            else -> BlindAction.DOWN
        }
        return action to command(mac, Command.Blind(action, groups))
    }

    /** Variation brève, là où on ne peut pas maintenir un bouton (widgets, lecteur d'écran). */
    suspend fun nudge(mac: String, up: Boolean, groups: Set<Int> = emptySet()): CommandResult {
        val r = command(mac, Command.Light(if (up) LightAction.UP else LightAction.DOWN, groups))
        delay(NUDGE_MS)
        withContext(NonCancellable) { command(mac, Command.Light(LightAction.STOP, groups)) }
        return r
    }

    /** « Se connecter » (maintien de la connexion) : liaison tenue jusqu'à « Se déconnecter ». */
    fun connect(mac: String) {
        val link = link(mac)
        if (!link.keep) return // sans maintien, chaque commande se connecte seule
        link.held = true
        connectNow(link)
    }

    private fun connectNow(link: Link) {
        scope.launch {
            try {
                checkReady()
                link.connect()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // L'échec s'affiche déjà sur la carte (« Injoignable ») ; l'entretien réessaiera.
            }
        }
    }

    /** « Se déconnecter » : rend la main (impossible en connexion auto). */
    fun disconnect(mac: String) {
        val link = link(mac)
        if (link.auto) return
        link.held = false
        link.drop()
    }

    /** « Tout déconnecter » (notification) : tout sauf les modules en connexion auto. */
    fun disconnectAll() {
        for (m in registry.modules.values) disconnect(m.mac)
    }

    /** Une liaison au moins peut être rendue (« Tout déconnecter » a un effet). */
    fun disconnectable(): Boolean = registry.modules.values.any { m ->
        !m.autoConnect && links[m.mac]?.let { it.wanted || it.status in setOf(LinkStatus.CONNECTING, LinkStatus.CONNECTED) } == true
    }

    fun update(
        mac: String,
        label: String? = null,
        pin: String? = null,
        pinned: Boolean? = null,
        autoConnect: Boolean? = null,
        keepConnected: Boolean? = null,
    ) {
        val m = registry.get(mac) ?: return
        val link = link(mac)
        val wasAuto = link.auto
        val wasKeep = link.keep
        label?.let { m.label = it.trim().take(60) }
        pin?.let { m.pin = it }
        pinned?.let { m.pinned = it }
        autoConnect?.let { m.autoConnect = it }
        keepConnected?.let { m.keepConnected = it }
        registry.save()
        if (link.auto != wasAuto || link.keep != wasKeep) applyLinkSettings(link, wasAuto, wasKeep)
        changed()
        Widgets.renderAll(context)
    }

    /** Après un changement de réglage : activer connecte tout de suite, désactiver libère le module. */
    private fun applyLinkSettings(link: Link, wasAuto: Boolean, wasKeep: Boolean) {
        link.held = when {
            !link.keep -> false
            (link.auto && !wasAuto) || !wasKeep -> true
            // Connexion auto retirée, maintien gardé : la liaison en place reste tenue jusqu'à « Se déconnecter ».
            else -> link.alive || link.status == LinkStatus.CONNECTING
        }
        if (link.wanted) connectNow(link) else scope.launch { link.release() }
    }

    /** Résumé pour la notification du service. */
    fun summary(): String {
        if (!bluetoothOn) return "Bluetooth désactivé"
        val parts = registry.modules.values.mapNotNull { m ->
            when (links[m.mac]?.status) {
                LinkStatus.CONNECTED -> "${m.displayName} : connecté" + if (m.autoConnect) " (auto)" else ""
                LinkStatus.CONNECTING -> "${m.displayName} : connexion…"
                LinkStatus.WAITING -> "${m.displayName} : en attente du module"
                else -> null
            }
        }
        return parts.joinToString("\n").ifEmpty { "Aucun module connecté" }
    }

    // --- Recherche -----------------------------------------------------------------------------

    /** Scan actif ; renvoie le nombre de nouveaux modules. Un module déjà connecté n'émet plus. */
    suspend fun scan(durationMs: Long = SCAN_MS): Int {
        if (scanning) return 0
        if (!Permissions.canScan(context)) throw IOException("autorisation Bluetooth manquante")
        val scanner = adapter?.takeIf { it.isEnabled }?.bluetoothLeScanner ?: throw IOException("Bluetooth désactivé")
        if (Build.VERSION.SDK_INT in 28..30 &&
            context.getSystemService(LocationManager::class.java)?.isLocationEnabled == false
        ) {
            throw IOException("activez la localisation : sur cette version d'Android, la recherche Bluetooth en dépend")
        }
        val before = registry.modules.size
        val failed = CompletableDeferred<Int>()
        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                main.post { onAdvertisement(result) }
            }

            override fun onBatchScanResults(results: MutableList<ScanResult>) {
                main.post { results.forEach(::onAdvertisement) }
            }

            override fun onScanFailed(errorCode: Int) {
                failed.complete(errorCode)
            }
        }
        scanning = true
        changed()
        try {
            val settings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build()
            scanner.startScan(null, settings, callback)
            val code = withTimeoutOrNull(durationMs) { failed.await() }
            if (code != null) throw IOException("recherche impossible (erreur $code)")
        } finally {
            try {
                scanner.stopScan(callback)
            } catch (_: Exception) {
            }
            scanning = false
            registry.save()
            changed()
        }
        return registry.modules.size - before
    }

    private fun onAdvertisement(r: ScanResult) {
        val name = r.scanRecord?.deviceName ?: r.device.name
        if (!Protocol.isArcom(name, r.scanRecord?.serviceUuids)) return
        registry.seen(r.device.address, name, r.rssi)
        changed()
    }
}
