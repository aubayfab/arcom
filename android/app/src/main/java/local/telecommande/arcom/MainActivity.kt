package local.telecommande.arcom

import android.app.Activity
import android.bluetooth.BluetoothAdapter
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.view.WindowInsets
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class MainActivity : Activity() {
    private var scope: CoroutineScope? = null
    private val cards = HashMap<String, ModuleCard>()
    private lateinit var content: LinearLayout
    private lateinit var scanButton: Button
    private lateinit var banner: View
    private lateinit var bannerText: TextView
    private lateinit var bannerAction: Button
    private lateinit var welcome: TextView
    private lateinit var pinnedSection: View
    private lateinit var pinnedEmpty: View
    private lateinit var pinnedList: LinearLayout
    private lateinit var othersToggle: Button
    private lateinit var othersHint: View
    private lateinit var othersList: LinearLayout
    private lateinit var toastView: TextView

    /** null : repliée s'il y a des favoris, dépliée sinon. */
    private var othersOpen: Boolean? = null
    private var askedPermissions = false
    private var deniedForGood = false
    private var autoScanned = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Arcom.init(this)
        setContentView(R.layout.activity_main)
        content = findViewById(R.id.content)
        scanButton = findViewById(R.id.scan)
        banner = findViewById(R.id.banner)
        bannerText = findViewById(R.id.banner_text)
        bannerAction = findViewById(R.id.banner_action)
        welcome = findViewById(R.id.welcome)
        pinnedSection = findViewById(R.id.pinned_section)
        pinnedEmpty = findViewById(R.id.pinned_empty)
        pinnedList = findViewById(R.id.pinned_list)
        othersToggle = findViewById(R.id.others_toggle)
        othersHint = findViewById(R.id.others_hint)
        othersList = findViewById(R.id.others_list)
        toastView = findViewById(R.id.toast)
        edgeToEdge()

        scanButton.setOnClickListener { scan() }
        bannerAction.setOnClickListener { fixBanner() }
        othersToggle.setOnClickListener {
            othersOpen = othersList.visibility != View.VISIBLE
            render()
        }
    }

    override fun onStart() {
        super.onStart()
        val s = MainScope()
        scope = s
        s.launch { Arcom.changes.collect { render() } }
        if (!Permissions.canScan(this) && !askedPermissions) {
            askedPermissions = true
            requestPermissions(Permissions.required + Permissions.optional, REQUEST_PERMISSIONS)
        } else {
            ready()
        }
    }

    override fun onResume() {
        super.onResume()
        render() // autorisation accordée ou Bluetooth activé depuis les paramètres
    }

    override fun onStop() {
        scope?.cancel()
        scope = null
        super.onStop()
    }

    /** Autorisations en place : reconnexion des favoris, et recherche au tout premier lancement. */
    private fun ready() {
        Arcom.wake()
        LinkService.sync(this) // l'appli est au premier plan : Android autorise le service
        if (Arcom.registry.modules.isEmpty() && Permissions.canScan(this) && Arcom.bluetoothOn && !autoScanned) {
            autoScanned = true
            scan()
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        if (requestCode != REQUEST_PERMISSIONS) return
        deniedForGood = Permissions.required.any {
            checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED && !shouldShowRequestPermissionRationale(it)
        }
        render()
        if (Permissions.canScan(this)) ready()
    }

    private fun scan() {
        if (!Permissions.canScan(this)) return fixBanner()
        Arcom.scope.launch {
            try {
                val found = Arcom.scan()
                val known = Arcom.registry.modules.size
                toast(if (found > 0) "$found nouveau(x) module(s) · $known au total" else "$known module(s) connu(s)")
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                toast(e.message ?: "Recherche impossible", error = true)
            }
        }
    }

    // --- Bandeau (autorisation, Bluetooth) ------------------------------------------------------

    private fun fixBanner() {
        when {
            !Permissions.canScan(this) ->
                if (deniedForGood) {
                    startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)))
                } else {
                    requestPermissions(Permissions.required + Permissions.optional, REQUEST_PERMISSIONS)
                }
            !Arcom.bluetoothOn -> try {
                @Suppress("MissingPermission") // BLUETOOTH_CONNECT accordée (vérifiée juste au-dessus)
                startActivity(Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE))
            } catch (e: Exception) {
                startActivity(Intent(Settings.ACTION_BLUETOOTH_SETTINGS))
            }
        }
    }

    private fun renderBanner() {
        val (text, action) = when {
            !Permissions.canScan(this) -> getString(R.string.banner_permission) to
                getString(if (deniedForGood) R.string.banner_settings else R.string.banner_allow)
            Arcom.adapter == null -> getString(R.string.banner_no_bluetooth) to null
            !Arcom.bluetoothOn -> getString(R.string.banner_bluetooth_off) to getString(R.string.banner_enable)
            else -> null to null
        }
        banner.visibility = if (text == null) View.GONE else View.VISIBLE
        bannerText.text = text
        bannerAction.visibility = if (action == null) View.GONE else View.VISIBLE
        bannerAction.text = action
    }

    // --- Liste des modules -----------------------------------------------------------------------

    private fun render() {
        renderBanner()
        val usable = Permissions.canScan(this) && Arcom.bluetoothOn
        scanButton.isEnabled = usable && !Arcom.scanning
        scanButton.alpha = if (scanButton.isEnabled) 1f else 0.5f
        scanButton.setText(if (Arcom.scanning) R.string.scanning else R.string.scan)

        val sorted = Arcom.registry.modules.values.sortedWith(
            compareByDescending<ModuleInfo> { it.pinned }
                .thenByDescending { it.rssi ?: -999 }
                .thenBy { it.displayName.lowercase() },
        )
        var pinnedCount = 0
        var othersCount = 0
        for (m in sorted) {
            val card = cards.getOrPut(m.mac) { ModuleCard(this, m.mac) }
            card.update(m, Arcom.linkOrNull(m.mac))
            val (list, index) = if (m.pinned) pinnedList to pinnedCount++ else othersList to othersCount++
            // Ne déplace que les cartes mal placées (un déplacement interromprait un appui en cours).
            if (list.getChildAt(index) !== card.view) {
                (card.view.parent as? ViewGroup)?.removeView(card.view)
                list.addView(card.view, index)
            }
        }

        welcome.visibility = if (sorted.isEmpty()) View.VISIBLE else View.GONE
        welcome.setText(if (Arcom.scanning) R.string.welcome_scanning else R.string.welcome_empty)
        pinnedSection.visibility = if (sorted.isEmpty()) View.GONE else View.VISIBLE
        pinnedEmpty.visibility = if (pinnedCount == 0) View.VISIBLE else View.GONE

        val open = othersOpen ?: (pinnedCount == 0)
        othersToggle.visibility = if (othersCount == 0) View.GONE else View.VISIBLE
        othersToggle.text = getString(if (open) R.string.others_open else R.string.others_closed, othersCount)
        othersHint.visibility = if (othersCount > 0 && open) View.VISIBLE else View.GONE
        othersList.visibility = if (open) View.VISIBLE else View.GONE
    }

    // --- Message éphémère ------------------------------------------------------------------------

    private val hideToast = Runnable { toastView.animate().alpha(0f).withEndAction { toastView.visibility = View.GONE } }

    fun toast(message: String, error: Boolean = false) {
        toastView.text = message
        toastView.setBackgroundResource(if (error) R.drawable.bg_toast_error else R.drawable.bg_toast)
        toastView.animate().cancel()
        toastView.alpha = 1f
        toastView.visibility = View.VISIBLE
        toastView.removeCallbacks(hideToast)
        toastView.postDelayed(hideToast, if (error) 5000 else 2500)
    }

    // --- Affichage bord à bord ------------------------------------------------------------------

    private fun edgeToEdge() {
        drawBehindBars(window)
        val pad = content.paddingTop
        val toastMargin = (toastView.layoutParams as ViewGroup.MarginLayoutParams).bottomMargin
        findViewById<View>(R.id.root).setOnApplyWindowInsetsListener { _, insets ->
            val (left, top, right, bottom) = systemBars(insets)
            content.setPadding(pad + left, pad + top, pad + right, pad + bottom)
            (toastView.layoutParams as ViewGroup.MarginLayoutParams).bottomMargin = toastMargin + bottom
            toastView.requestLayout()
            insets
        }
    }

    companion object {
        private const val REQUEST_PERMISSIONS = 1

        /** Contenu sous les barres système (Android 15+ l'impose déjà), marges appliquées à la main. */
        @Suppress("DEPRECATION")
        fun drawBehindBars(window: Window) {
            when {
                Build.VERSION.SDK_INT >= 35 -> Unit
                Build.VERSION.SDK_INT >= 30 -> window.setDecorFitsSystemWindows(false)
                else -> window.decorView.systemUiVisibility = window.decorView.systemUiVisibility or
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            }
        }

        /** Marges des barres système (et de l'encoche) : gauche, haut, droite, bas. */
        fun systemBars(insets: WindowInsets): List<Int> =
            if (Build.VERSION.SDK_INT >= 30) {
                val i = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                listOf(i.left, i.top, i.right, i.bottom)
            } else {
                @Suppress("DEPRECATION")
                listOf(insets.systemWindowInsetLeft, insets.systemWindowInsetTop, insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            }
    }
}
