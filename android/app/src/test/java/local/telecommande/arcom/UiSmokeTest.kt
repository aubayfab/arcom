package local.telecommande.arcom

import android.app.Activity
import android.app.Application
import android.appwidget.AppWidgetProviderInfo
import android.appwidget.AppWidgetManager
import android.bluetooth.BluetoothManager
import android.content.ComponentName
import android.content.Intent
import android.os.Build
import android.os.Looper
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.RadioGroup
import android.widget.RemoteViews
import android.widget.Switch
import android.widget.TextView
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowAlertDialog
import java.io.File

/**
 * Sans module ni Bluetooth : vérifie que l'écran, les widgets et le service s'affichent et
 * échouent proprement (Android 10 : autorisations à l'installation ; Android 14 : à l'exécution,
 * non accordées ici, d'où le service en shortService). Robolectric exige Java 21 au-delà d'Android 14.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29, 34])
class UiSmokeTest {
    private lateinit var app: Application

    @Before
    fun setUp() {
        app = RuntimeEnvironment.getApplication()
        Arcom.init(app)
        shadowOf(app.getSystemService(BluetoothManager::class.java).adapter).setEnabled(false)
        Arcom.registry.seen(MAC, "ARC_1302", -60)
        Arcom.update(MAC, label = LABEL, pinned = true, autoConnect = false, keepConnected = false)
    }

    private fun idle() = shadowOf(Looper.getMainLooper()).idle()

    /** Ce que l'appli doit dire quand on lance une commande dans ces conditions. */
    private val expectedRefusal: String
        get() = if (Build.VERSION.SDK_INT >= 31) "autorisation" else "Bluetooth désactivé"

    @Test
    fun mainScreenShowsModuleAndRefusesCleanly() {
        val activity = Robolectric.buildActivity(MainActivity::class.java).setup().get()
        idle()
        val pinned = activity.findViewById<LinearLayout>(R.id.pinned_list)
        assertEquals(1, pinned.childCount)
        val card = pinned.getChildAt(0)
        assertEquals(LABEL, card.findViewById<TextView>(R.id.title).text.toString())

        assertEquals(View.VISIBLE, activity.findViewById<View>(R.id.banner).visibility)

        card.findViewById<View>(R.id.on).performClick()
        idle()
        val toast = activity.findViewById<TextView>(R.id.toast)
        assertEquals(View.VISIBLE, toast.visibility)
        assertTrue(toast.text.toString(), toast.text.contains(expectedRefusal, ignoreCase = true))

        card.findViewById<View>(R.id.comfort_toggle).performClick()
        assertEquals(View.VISIBLE, card.findViewById<View>(R.id.comfort).visibility)
    }

    @Test
    fun connectionSwitchesOffByDefaultSavedAndShownOnCard() {
        Arcom.registry.seen("AA:BB:CC:DD:EE:02", "ARC_1301", -71) // module jamais réglé
        assertFalse(Arcom.registry.get("AA:BB:CC:DD:EE:02")!!.autoConnect)
        assertFalse(Arcom.registry.get("AA:BB:CC:DD:EE:02")!!.keepConnected)

        val activity = Robolectric.buildActivity(MainActivity::class.java).setup().get()
        idle()
        val card = activity.findViewById<LinearLayout>(R.id.pinned_list).getChildAt(0)
        val auto = card.findViewById<Switch>(R.id.auto_connect)
        val keep = card.findViewById<Switch>(R.id.keep_connected)
        val link = card.findViewById<Button>(R.id.link)
        val hint = card.findViewById<TextView>(R.id.mode_hint)

        // Par défaut : ponctuel, pas de bouton de connexion.
        assertFalse(auto.isChecked)
        assertFalse(keep.isChecked)
        assertEquals(View.GONE, link.visibility)
        assertEquals(activity.getString(R.string.mode_oneshot), hint.text.toString())

        // Maintien : bouton « Se déconnecter » (connexion demandée dès l'activation), enregistré.
        keep.performClick()
        idle()
        assertTrue(Arcom.registry.get(MAC)!!.keepConnected)
        assertEquals(View.VISIBLE, link.visibility)
        assertEquals(activity.getString(R.string.disconnect), link.text.toString())
        link.performClick()
        idle()
        assertEquals(activity.getString(R.string.connect), link.text.toString())
        assertFalse(Arcom.link(MAC).wanted)

        // Connexion auto : maintien coché et figé, plus de déconnexion possible.
        auto.performClick()
        idle()
        assertTrue(keep.isChecked)
        assertFalse(keep.isEnabled)
        assertEquals(View.GONE, link.visibility)
        Arcom.disconnect(MAC)
        assertTrue(Arcom.link(MAC).wanted)
        assertEquals(activity.getString(R.string.mode_auto), hint.text.toString())

        assertTrue(Arcom.registry.get(MAC)!!.autoConnect)
        assertTrue(Arcom.registry.get(MAC)!!.keepConnected)

        // Connexion auto retirée : le maintien reste (une liaison ouverte resterait tenue ; ici, aucune).
        auto.performClick()
        idle()
        assertTrue(keep.isChecked)
        assertTrue(keep.isEnabled)
        assertEquals(View.VISIBLE, link.visibility)
        assertEquals(activity.getString(R.string.connect), link.text.toString())
        keep.performClick()
        idle()
        assertFalse(Arcom.link(MAC).wanted)
        assertEquals(View.GONE, link.visibility)
    }

    /**
     * Réglages de connexion relus depuis modules.json (format du PC), désactivés si absents.
     * Fichier absent au départ : AtomicFile remplace le fichier par un renommage, que Windows
     * refuse quand la cible existe (Robolectric, Android 11+), contrairement à Android.
     */
    @Test
    fun registryRoundTripKeepsConnectionSettings() {
        val file = File.createTempFile("modules", ".json").apply { delete() }
        val other = "AA:BB:CC:DD:EE:02"
        Registry(file).apply {
            seen(MAC, "ARC_1302", -60).autoConnect = true
            seen(other, "ARC_1301", -71).keepConnected = true
            save()
        }
        val loaded = Registry(file)
        assertTrue(loaded.get(MAC)!!.autoConnect)
        assertFalse(loaded.get(MAC)!!.keepConnected)
        assertFalse(loaded.get(other)!!.autoConnect)
        assertTrue(loaded.get(other)!!.keepConnected)
        val json = JSONObject(file.readText()).getJSONArray("modules").getJSONObject(0)
        assertTrue(json.has("auto_connect") && json.has("keep_connected"))

        // Fichier d'une version précédente : réglages absents, donc désactivés ; le favori reste.
        file.writeText("""{"modules":[{"mac":"$MAC","name":"ARC_1302","pinned":true}]}""")
        val legacy = Registry(file).get(MAC)!!
        assertFalse(legacy.autoConnect)
        assertFalse(legacy.keepConnected)
        assertTrue(legacy.pinned)
        file.delete()
    }

    @Test
    fun renameDialogUpdatesLabel() {
        val activity = Robolectric.buildActivity(MainActivity::class.java).setup().get()
        idle()
        val card = activity.findViewById<LinearLayout>(R.id.pinned_list).getChildAt(0)
        card.findViewById<View>(R.id.titles).performClick()
        val dialog = ShadowAlertDialog.getLatestAlertDialog()
        assertNotNull(dialog)
        dialog.findViewById<EditText>(R.id.edit_label).setText("Bureau 13")
        dialog.getButton(android.content.DialogInterface.BUTTON_POSITIVE).performClick()
        idle()
        assertEquals("Bureau 13", Arcom.registry.get(MAC)!!.label)
        Arcom.update(MAC, label = LABEL)
    }

    @Test
    fun widgetLayoutsInflateAsRemoteViews() {
        for (layout in listOf(R.layout.widget_remote, R.layout.widget_light, R.layout.widget_blind)) {
            val view = RemoteViews(app.packageName, layout).apply(app, FrameLayout(app))
            assertNotNull(view.findViewById(R.id.w_title))
            assertNotNull(view.findViewById(R.id.w_status))
        }
    }

    @Test
    fun widgetConfigureRenderAndTap() {
        val widgets = shadowOf(AppWidgetManager.getInstance(app))
        val id = widgets.createWidget(RemoteWidget::class.java, R.layout.widget_remote)
        // createWidget ne renseigne pas le fournisseur, dont Widgets.render a besoin.
        widgets.putWidgetInfo(id, AppWidgetProviderInfo().apply { provider = ComponentName(app, RemoteWidget::class.java) })

        // Configuration : le module connu est proposé, on valide avec tous les groupes.
        val intent = Intent(app, WidgetConfigActivity::class.java).putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id)
        val config = Robolectric.buildActivity(WidgetConfigActivity::class.java, intent).setup().get()
        assertTrue(config.findViewById<RadioGroup>(R.id.modules).childCount >= 1)
        config.findViewById<View>(R.id.save).performClick()
        assertEquals(Activity.RESULT_OK, shadowOf(config).resultCode)
        assertEquals(MAC, Widgets.config(app, id)!!.mac)
        assertEquals(emptySet<Int>(), Widgets.config(app, id)!!.groups)

        val title = widgets.getViewFor(id).findViewById<TextView>(R.id.w_title)
        assertEquals(LABEL, title.text.toString()) // et non le texte d'aperçu de la mise en page

        // Appui sur « Allumer » : le service démarre au premier plan et le widget affiche le refus.
        val tap = Intent(app, LinkService::class.java)
            .setAction(LinkService.ACTION_WIDGET)
            .putExtra(LinkService.EXTRA_WIDGET, id)
            .putExtra(LinkService.EXTRA_OP, Widgets.Op.ON.name)
        val service = Robolectric.buildService(LinkService::class.java, tap).create().startCommand(0, 1).get()
        idle()
        assertNotNull(shadowOf(service).lastForegroundNotification)
        val status = widgets.getViewFor(id).findViewById<TextView>(R.id.w_status).text.toString()
        assertTrue(status, status.contains(if (Build.VERSION.SDK_INT >= 31) "Autorisation" else "Bluetooth"))
    }

    companion object {
        private const val MAC = "AA:BB:CC:DD:EE:01"
        private const val LABEL = "Salle 1302"
    }
}
