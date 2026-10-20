package local.telecommande.arcom

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.CheckBox
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView

/** Choix du module (et des groupes) piloté par un widget, à l'ajout ou par appui long › Paramètres. */
class WidgetConfigActivity : Activity() {
    private var widgetId = AppWidgetManager.INVALID_APPWIDGET_ID
    private var selected: String? = null
    private lateinit var list: RadioGroup
    private lateinit var empty: View
    private lateinit var groups: List<CheckBox>

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setResult(RESULT_CANCELED) // retour arrière = widget non ajouté
        widgetId = intent?.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
            ?: AppWidgetManager.INVALID_APPWIDGET_ID
        if (widgetId == AppWidgetManager.INVALID_APPWIDGET_ID) {
            finish()
            return
        }
        Arcom.init(this)
        setContentView(R.layout.activity_widget_config)
        list = findViewById(R.id.modules)
        empty = findViewById(R.id.empty)
        groups = listOf(R.id.g1, R.id.g2, R.id.g3, R.id.g4).map { findViewById(it) }

        val existing = Widgets.config(this, widgetId)
        selected = existing?.mac
        existing?.groups?.takeIf { it.isNotEmpty() }?.let { g ->
            groups.forEachIndexed { i, box -> box.isChecked = (i + 1) in g }
        }

        list.setOnCheckedChangeListener { group, checkedId ->
            selected = group.findViewById<View>(checkedId)?.tag as String?
        }
        findViewById<Button>(R.id.open_app).setOnClickListener {
            startActivity(Intent(this, MainActivity::class.java))
        }
        findViewById<Button>(R.id.cancel).setOnClickListener { finish() }
        findViewById<Button>(R.id.save).setOnClickListener { save() }

        MainActivity.drawBehindBars(window)
        val root = findViewById<View>(R.id.root)
        val pad = root.paddingTop
        root.setOnApplyWindowInsetsListener { v, insets ->
            val (left, top, right, bottom) = MainActivity.systemBars(insets)
            v.setPadding(pad + left, pad + top, pad + right, pad + bottom)
            insets
        }
    }

    override fun onResume() {
        super.onResume()
        populate() // de retour de l'appli après une recherche
    }

    private fun populate() {
        list.removeAllViews()
        val modules = Arcom.registry.modules.values.sortedWith(
            compareByDescending<ModuleInfo> { it.pinned }.thenByDescending { it.rssi ?: -999 },
        )
        empty.visibility = if (modules.isEmpty()) View.VISIBLE else View.GONE
        if (selected == null) selected = modules.firstOrNull()?.mac
        for (m in modules) {
            val button = RadioButton(this).apply {
                id = View.generateViewId()
                tag = m.mac
                val star = if (m.pinned) "★ " else ""
                val detail = listOfNotNull(
                    m.name.takeIf { m.label.isNotBlank() },
                    m.rssi?.let { "$it dBm" },
                    getString(R.string.auto_connect).lowercase().takeIf { m.autoConnect },
                )
                text = star + m.displayName + if (detail.isEmpty()) "" else "\n" + detail.joinToString(" · ")
                textSize = 16f
                setTextColor(getColor(R.color.text))
                minHeight = (52 * resources.displayMetrics.density).toInt()
            }
            list.addView(button, RadioGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            if (m.mac == selected) list.check(button.id)
        }
    }

    private fun save() {
        val mac = selected
        val chosen = groups.withIndex().filter { it.value.isChecked }.map { it.index + 1 }.toSet()
        val error = findViewById<TextView>(R.id.error)
        when {
            mac == null -> error.setText(R.string.widget_config_pick)
            chosen.isEmpty() -> error.setText(R.string.widget_config_groups_none)
            else -> {
                Widgets.configure(this, widgetId, mac, if (chosen.size == 4) emptySet() else chosen)
                Widgets.render(this, widgetId)
                setResult(RESULT_OK, Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId))
                finish()
                return
            }
        }
        error.visibility = View.VISIBLE
    }
}
