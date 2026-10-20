package local.telecommande.arcom

import android.annotation.SuppressLint
import android.app.AlertDialog
import android.content.res.ColorStateList
import android.view.MotionEvent
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ImageButton
import android.widget.Switch
import android.widget.TextView
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/** Carte d'un module dans l'écran principal (même disposition que l'interface web). */
class ModuleCard(private val activity: MainActivity, private val mac: String) {
    val view: View = activity.layoutInflater.inflate(R.layout.item_module, null, false)
    private val title: TextView = view.findViewById(R.id.title)
    private val meta: TextView = view.findViewById(R.id.meta)
    private val pin: ImageButton = view.findViewById(R.id.pin)
    private val dot: View = view.findViewById(R.id.dot)
    private val statusText: TextView = view.findViewById(R.id.status)
    private val signal: TextView = view.findViewById(R.id.signal)
    private val linkButton: Button = view.findViewById(R.id.link)
    private val blindUp: ImageButton = view.findViewById(R.id.blind_up)
    private val blindDown: ImageButton = view.findViewById(R.id.blind_down)
    private val comfortToggle: Button = view.findViewById(R.id.comfort_toggle)
    private val comfort: View = view.findViewById(R.id.comfort)
    private val ventButtons: List<Button> =
        listOf(R.id.vent_0, R.id.vent_1, R.id.vent_2, R.id.vent_3, R.id.vent_4).map { view.findViewById(it) }
    private val tempValue: TextView = view.findViewById(R.id.temp_value)
    private val occOff: Button = view.findViewById(R.id.occ_off)
    private val occOn: Button = view.findViewById(R.id.occ_on)
    private val autoSwitch: Switch = view.findViewById(R.id.auto_connect)
    private val keepSwitch: Switch = view.findViewById(R.id.keep_connected)
    private val modeHint: TextView = view.findViewById(R.id.mode_hint)

    private var module: ModuleInfo? = null
    private var link: Link? = null

    /** Consigne demandée, en attendant que …c69 la reflète (deux appuis rapides = deux crans). */
    private var pendingOffset: Int? = null
    private var shownHvac: Hvac? = null

    init {
        bind()
    }

    private val name: String get() = module?.displayName ?: mac

    /** Envoie une commande ; [text] : message affiché en cas de succès (null = discret). */
    private fun send(text: String?, block: suspend () -> CommandResult) {
        Arcom.scope.launch {
            try {
                val r = block()
                if (text != null) {
                    val reversed = if (r.reversed) " (arrêt puis inversion)" else ""
                    activity.toast("$name — $text$reversed · ${r.ms} ms")
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                activity.toast("$name — ${e.message}", error = true)
            }
        }
    }

    private fun send(cmd: Command, text: String? = null) = send(text) { Arcom.command(mac, cmd) }

    private fun bind() {
        view.findViewById<View>(R.id.titles).setOnClickListener { edit() }
        pin.setOnClickListener { Arcom.update(mac, pinned = module?.pinned != true) }
        // « Se connecter » / « Se déconnecter » : affiché en mode « Maintenir la connexion » uniquement.
        linkButton.setOnClickListener {
            val l = link
            if (l != null && (l.wanted || l.status == LinkStatus.CONNECTED)) Arcom.disconnect(mac) else Arcom.connect(mac)
        }
        // Clic plutôt que changement d'état : update() recoche les interrupteurs sans rien déclencher.
        autoSwitch.setOnClickListener { Arcom.update(mac, autoConnect = autoSwitch.isChecked) }
        keepSwitch.setOnClickListener { Arcom.update(mac, keepConnected = keepSwitch.isChecked) }
        view.findViewById<View>(R.id.on).setOnClickListener { send(Command.Light(LightAction.ON), "lumière allumée") }
        view.findViewById<View>(R.id.off).setOnClickListener { send(Command.Light(LightAction.OFF), "lumière éteinte") }
        holdToDim(view.findViewById(R.id.dim_down), LightAction.DOWN)
        holdToDim(view.findViewById(R.id.dim_up), LightAction.UP)
        blindButton(blindUp, Direction.UP)
        blindButton(blindDown, Direction.DOWN)
        view.findViewById<View>(R.id.blind_stop).setOnClickListener {
            send(Command.Blind(BlindAction.STOP), "stores arrêtés")
        }

        comfortToggle.setOnClickListener {
            comfort.visibility = if (comfort.visibility == View.VISIBLE) View.GONE else View.VISIBLE
            renderHvac()
        }
        ventButtons.forEachIndexed { level, button ->
            button.setOnClickListener { send(Command.Ventilation(level), "ventilation ${ventText(level)}") }
        }
        view.findViewById<View>(R.id.temp_down).setOnClickListener { stepSetpoint(-1) }
        view.findViewById<View>(R.id.temp_up).setOnClickListener { stepSetpoint(+1) }
        occOff.setOnClickListener { send(Command.Occupation(false), "inoccupé") }
        occOn.setOnClickListener { send(Command.Occupation(true), "occupé") }
    }

    /** Maintenir : varie ; relâcher : stop (comme l'app d'origine). */
    @SuppressLint("ClickableViewAccessibility") // le clic (lecteur d'écran) fait une variation brève
    private fun holdToDim(button: View, action: LightAction) {
        var held = false
        button.setOnTouchListener { v, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    held = true
                    v.isPressed = true
                    send(Command.Light(action))
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> if (held) {
                    held = false
                    v.isPressed = false
                    send(Command.Light(LightAction.STOP))
                }
            }
            true
        }
        button.setOnClickListener { send(null) { Arcom.nudge(mac, action == LightAction.UP) } }
    }

    /** Clic : lance la course ou l'arrête ; appui long : oriente les lames tant qu'on maintient. */
    @SuppressLint("ClickableViewAccessibility") // le relâchement court appelle performClick()
    private fun blindButton(button: View, direction: Direction) {
        var tilting = false
        val tilt = Runnable {
            tilting = true
            send(Command.Blind(if (direction == Direction.UP) BlindAction.ROT_UP else BlindAction.ROT_DOWN))
        }
        button.setOnTouchListener { v, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    v.isPressed = true
                    tilting = false
                    v.postDelayed(tilt, LONG_PRESS_MS)
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    v.isPressed = false
                    v.removeCallbacks(tilt)
                    if (tilting) {
                        tilting = false
                        send(Command.Blind(BlindAction.ROT_STOP))
                    } else if (e.actionMasked == MotionEvent.ACTION_UP) {
                        v.performClick()
                    }
                }
            }
            true
        }
        button.setOnClickListener {
            Arcom.scope.launch {
                try {
                    val (action, r) = Arcom.blindTap(mac, direction)
                    val text = when (action) {
                        BlindAction.UP -> "stores en montée"
                        BlindAction.DOWN -> "stores en descente"
                        else -> "stores arrêtés"
                    }
                    activity.toast("$name — $text${if (r.reversed) " (arrêt puis inversion)" else ""} · ${r.ms} ms")
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    activity.toast("$name — ${e.message}", error = true)
                }
            }
        }
    }

    private fun stepSetpoint(delta: Int) {
        val current = pendingOffset ?: link?.hvac?.offsetTemp ?: 6
        val next = (current + delta).coerceIn(0, 12)
        pendingOffset = next
        renderHvac()
        send(Command.Setpoint(next), "consigne ${offsetText(next)}")
    }

    /** Nom affiché et PIN du module. */
    private fun edit() {
        val m = module ?: return
        val form = activity.layoutInflater.inflate(R.layout.dialog_module, null, false)
        val label = form.findViewById<EditText>(R.id.edit_label)
        val pinField = form.findViewById<EditText>(R.id.edit_pin)
        label.setText(m.label)
        label.hint = m.name ?: m.mac
        pinField.setText(m.pin)
        AlertDialog.Builder(activity)
            .setTitle(m.name ?: m.mac)
            .setView(form)
            .setPositiveButton(R.string.save) { _, _ ->
                val pinText = pinField.text.toString().trim()
                if (pinText.length == 4 && pinText.all { it.isDigit() }) {
                    Arcom.update(mac, label = label.text.toString(), pin = pinText)
                } else {
                    Arcom.update(mac, label = label.text.toString())
                    activity.toast("PIN ignoré : il faut 4 chiffres", error = true)
                }
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    fun update(m: ModuleInfo, link: Link?) {
        module = m
        this.link = link
        val ctx = view.context
        title.text = m.displayName
        meta.text = if (m.label.isNotBlank()) "${m.name ?: "?"} · ${m.mac}" else m.mac
        pin.setImageResource(if (m.pinned) R.drawable.ic_star else R.drawable.ic_star_outline)
        pin.contentDescription = ctx.getString(if (m.pinned) R.string.unpin else R.string.pin)

        val status = link?.status ?: LinkStatus.DISCONNECTED
        statusText.text = when (status) {
            LinkStatus.CONNECTED -> "Connecté"
            LinkStatus.CONNECTING -> "Connexion…"
            LinkStatus.WAITING -> "En attente du module"
            LinkStatus.ERROR -> "Injoignable"
            LinkStatus.DISCONNECTED -> if (link?.wanted == true) "Reconnexion…" else "Déconnecté"
        }
        val color = when (status) {
            LinkStatus.CONNECTED -> R.color.ok
            LinkStatus.CONNECTING, LinkStatus.WAITING -> R.color.warn
            LinkStatus.ERROR -> R.color.err
            LinkStatus.DISCONNECTED -> R.color.muted
        }
        dot.backgroundTintList = ColorStateList.valueOf(ctx.getColor(color))
        signal.text = if (status == LinkStatus.ERROR && link?.error != null) {
            link.error
        } else {
            listOfNotNull(m.rssi?.let { "$it dBm" }, link?.lastMs?.let { "$it ms" }).joinToString(" · ")
        }

        // Connexion auto : pas de déconnexion possible ; sans maintien, chaque commande se connecte seule.
        linkButton.visibility = if (m.keepConnected && !m.autoConnect) View.VISIBLE else View.GONE
        val holding = link?.wanted == true || status == LinkStatus.CONNECTED
        linkButton.setText(
            when {
                holding -> R.string.disconnect
                status == LinkStatus.CONNECTING -> R.string.connecting
                else -> R.string.connect
            },
        )
        linkButton.isEnabled = holding || status != LinkStatus.CONNECTING

        autoSwitch.isChecked = m.autoConnect
        // La connexion auto implique le maintien : affiché coché, et non modifiable tant qu'elle est active.
        keepSwitch.isChecked = m.keepConnected || m.autoConnect
        keepSwitch.isEnabled = !m.autoConnect
        modeHint.setText(
            when {
                m.autoConnect -> R.string.mode_auto
                m.keepConnected -> R.string.mode_keep
                else -> R.string.mode_oneshot
            },
        )

        val moving = link?.blindDirection()
        blindUp.isSelected = moving == Direction.UP
        blindDown.isSelected = moving == Direction.DOWN

        if (link?.hvac != shownHvac) {
            shownHvac = link?.hvac
            pendingOffset = null // l'état relu fait foi
        }
        renderHvac()
    }

    private fun renderHvac() {
        val h = link?.hvac
        val arrow = if (comfort.visibility == View.VISIBLE) "▴" else "▾"
        comfortToggle.text = if (h == null) "Confort  $arrow" else "Confort · ${hvacText(h)}  $arrow"
        ventButtons.forEachIndexed { level, b -> b.isSelected = h?.ventilation == level }
        tempValue.text = offsetText(pendingOffset ?: h?.offsetTemp ?: 6)
        occOff.isSelected = h?.occupation == 0
        occOn.isSelected = h?.occupation == 1
    }

    companion object {
        /** Au-delà, l'appui sur ▲/▼ oriente les lames au lieu de lancer la course. */
        private const val LONG_PRESS_MS = 450L

        fun ventText(level: Int) = when (level) {
            0 -> "arrêtée"
            4 -> "auto"
            else -> "$level"
        }

        /** Offset brut 0..12 -> écart à la consigne (6 = neutre). */
        fun offsetText(offset: Int): String {
            val d = offset - 6
            return when {
                d > 0 -> "+$d"
                d < 0 -> "−${-d}"
                else -> "±0"
            }
        }

        fun hvacText(h: Hvac): String {
            val parts = mutableListOf(if (h.occupation == 1) "occupé" else "inoccupé")
            parts += "ventilation ${ventText(h.ventilation.coerceAtMost(4))}"
            parts += "consigne ${offsetText(h.offsetTemp)}"
            if (h.windowAlarm != 0) parts += "fenêtre ouverte"
            if (h.alarm != 0) parts += "alarme"
            return parts.joinToString(" · ")
        }
    }
}
