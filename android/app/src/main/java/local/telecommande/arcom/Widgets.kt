package local.telecommande.arcom

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.text.format.DateFormat
import android.util.Log
import android.widget.RemoteViews
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.Date

/** Les trois widgets : télécommande complète (4×2), lumière (2×1), stores (2×1). */
abstract class ArcomWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        for (id in ids) Widgets.render(context, id, manager)
    }

    override fun onDeleted(context: Context, ids: IntArray) {
        Widgets.forget(context, ids)
    }
}

class RemoteWidget : ArcomWidget()
class LightWidget : ArcomWidget()
class BlindWidget : ArcomWidget()

object Widgets {
    private const val PREFS = "widgets"

    /**
     * Un widget ne peut pas savoir qu'on maintient un bouton : − et + font une variation brève,
     * et l'orientation des lames (appui long) reste dans l'appli.
     */
    enum class Op { ON, OFF, DIM_DOWN, DIM_UP, UP, STOP, DOWN }

    private class Kind(val layout: Int, val buttons: List<Pair<Int, Op>>)

    private val LIGHT_BUTTONS = listOf(R.id.w_on to Op.ON, R.id.w_off to Op.OFF)
    private val BLIND_BUTTONS = listOf(R.id.w_up to Op.UP, R.id.w_stop to Op.STOP, R.id.w_down to Op.DOWN)
    private val PROVIDERS = listOf(RemoteWidget::class.java, LightWidget::class.java, BlindWidget::class.java)

    private fun kind(className: String): Kind? = when (className) {
        RemoteWidget::class.java.name -> Kind(
            R.layout.widget_remote,
            LIGHT_BUTTONS + listOf(R.id.w_dim_down to Op.DIM_DOWN, R.id.w_dim_up to Op.DIM_UP) + BLIND_BUTTONS,
        )
        LightWidget::class.java.name -> Kind(R.layout.widget_light, LIGHT_BUTTONS)
        BlindWidget::class.java.name -> Kind(R.layout.widget_blind, BLIND_BUTTONS)
        else -> null
    }

    /** Dernier résultat affiché par widget (en mémoire : perdu si Android arrête l'appli, sans gravité). */
    private val status = HashMap<Int, String>()

    // --- Configuration ---------------------------------------------------------------------------

    class Config(val mac: String, val groups: Set<Int>)

    private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun config(ctx: Context, id: Int): Config? {
        val p = prefs(ctx)
        val mac = p.getString("$id.mac", null) ?: return null
        val groups = p.getString("$id.groups", "").orEmpty().mapNotNull { it.digitToIntOrNull() }.toSet()
        return Config(mac, groups)
    }

    /** [groups] vide = tous les groupes. */
    fun configure(ctx: Context, id: Int, mac: String, groups: Set<Int>) {
        prefs(ctx).edit()
            .putString("$id.mac", mac)
            .putString("$id.groups", groups.sorted().joinToString(""))
            .apply()
        status.remove(id)
    }

    fun forget(ctx: Context, ids: IntArray) {
        val editor = prefs(ctx).edit()
        for (id in ids) {
            editor.remove("$id.mac").remove("$id.groups")
            status.remove(id)
        }
        editor.apply()
    }

    // --- Affichage -----------------------------------------------------------------------------

    fun renderAll(ctx: Context) {
        val manager = AppWidgetManager.getInstance(ctx) ?: return
        for (provider in PROVIDERS) {
            for (id in manager.getAppWidgetIds(ComponentName(ctx, provider))) render(ctx, id, manager)
        }
    }

    fun render(ctx: Context, id: Int, manager: AppWidgetManager = AppWidgetManager.getInstance(ctx)) {
        val info = manager.getAppWidgetInfo(id) ?: return
        val kind = kind(info.provider.className) ?: return
        val cfg = config(ctx, id)
        val module = cfg?.let { Arcom.registry.get(it.mac) }
        val views = RemoteViews(ctx.packageName, kind.layout)
        views.setTextViewText(R.id.w_title, module?.displayName ?: ctx.getString(R.string.widget_unconfigured))
        views.setTextViewText(R.id.w_status, status[id] ?: groupsLabel(cfg?.groups.orEmpty()))
        val open = PendingIntent.getActivity(
            ctx, 0, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE,
        )
        views.setOnClickPendingIntent(R.id.w_head, open)
        for ((viewId, op) in kind.buttons) views.setOnClickPendingIntent(viewId, opIntent(ctx, id, op))
        manager.updateAppWidget(id, views)
    }

    private fun groupsLabel(groups: Set<Int>) =
        if (groups.isEmpty()) "" else "G" + groups.sorted().joinToString("+")

    private fun opIntent(ctx: Context, id: Int, op: Op): PendingIntent {
        val intent = Intent(ctx, LinkService::class.java)
            .setAction(LinkService.ACTION_WIDGET)
            .setData(Uri.parse("arcom://widget/$id/${op.name}")) // un PendingIntent distinct par bouton
            .putExtra(LinkService.EXTRA_WIDGET, id)
            .putExtra(LinkService.EXTRA_OP, op.name)
        return PendingIntent.getForegroundService(ctx, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    private fun show(ctx: Context, id: Int, text: String) {
        status[id] = text
        render(ctx, id)
    }

    private fun clock(ctx: Context): String = DateFormat.getTimeFormat(ctx).format(Date())

    // --- Appui sur un bouton (appelé par LinkService) ------------------------------------------------

    fun handle(ctx: Context, id: Int, opName: String?) {
        val op = Op.entries.firstOrNull { it.name == opName } ?: return
        val cfg = config(ctx, id) ?: return show(ctx, id, "À configurer")
        val module = Arcom.registry.get(cfg.mac) ?: return show(ctx, id, "Module inconnu")
        if (!Permissions.canConnect(ctx)) return show(ctx, id, "Autorisation ? Ouvrir l’appli")
        if (!Arcom.bluetoothOn) return show(ctx, id, "Bluetooth désactivé")
        if (!Arcom.link(module.mac).alive) show(ctx, id, "Connexion…")

        Arcom.busy++
        Arcom.scope.launch {
            val text = try {
                val mark = when (op) {
                    Op.ON -> "✓".also { Arcom.command(module.mac, Command.Light(LightAction.ON, cfg.groups)) }
                    Op.OFF -> "✓".also { Arcom.command(module.mac, Command.Light(LightAction.OFF, cfg.groups)) }
                    Op.DIM_UP -> "+".also { Arcom.nudge(module.mac, up = true, cfg.groups) }
                    Op.DIM_DOWN -> "−".also { Arcom.nudge(module.mac, up = false, cfg.groups) }
                    Op.STOP -> "■".also { Arcom.command(module.mac, Command.Blind(BlindAction.STOP, cfg.groups)) }
                    Op.UP, Op.DOWN -> {
                        val direction = if (op == Op.UP) Direction.UP else Direction.DOWN
                        when (Arcom.blindTap(module.mac, direction, cfg.groups).first) {
                            BlindAction.STOP -> "■"
                            BlindAction.UP -> "▲"
                            else -> "▼"
                        }
                    }
                }
                "$mark ${clock(ctx)}"
            } catch (e: CancellationException) {
                if (!isActive) throw e
                "✗ interrompu" // connexion annulée entre-temps (« Déconnecter » dans l'appli)
            } catch (e: Exception) {
                Log.w(Arcom.TAG, "Widget ${module.displayName} : ${e.message}")
                "✗ " + (e.message?.substringBefore(" (") ?: "échec")
            } finally {
                Arcom.busy--
                Arcom.changed()
            }
            show(ctx, id, text)
        }
    }
}
