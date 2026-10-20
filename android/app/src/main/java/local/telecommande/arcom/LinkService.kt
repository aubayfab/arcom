package local.telecommande.arcom

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Service de premier plan : tant qu'une liaison est ouverte ou voulue (connexion auto, maintien de
 * la connexion, commande en cours) ou qu'une commande de widget est en cours, il garde le processus
 * en vie, sinon Android le gèlerait et les liaisons tomberaient. Il s'arrête seul ensuite.
 *
 * Les boutons des widgets le démarrent directement (PendingIntent.getForegroundService) : Android
 * l'autorise parce que l'utilisateur vient de toucher le widget.
 */
class LinkService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var stopping: Job? = null
    private var shown: String? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        running = true
        Arcom.init(this)
        val channel = NotificationChannel(CHANNEL, getString(R.string.channel_links), NotificationManager.IMPORTANCE_LOW)
        channel.description = getString(R.string.channel_links_desc)
        channel.setShowBadge(false)
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        scope.launch { Arcom.changes.collect { onChange() } }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Obligatoire à chaque démarrage par startForegroundService, avant tout le reste.
        if (!goForeground()) {
            stopSelf()
            return START_NOT_STICKY
        }
        when (intent?.action) {
            ACTION_WIDGET -> Widgets.handle(
                this,
                intent.getIntExtra(EXTRA_WIDGET, AppWidgetManager.INVALID_APPWIDGET_ID),
                intent.getStringExtra(EXTRA_OP),
            )
            ACTION_DISCONNECT -> Arcom.disconnectAll()
        }
        onChange()
        return START_STICKY
    }

    /** shortService (sans autorisation Bluetooth) : Android demande d'arrêter. */
    override fun onTimeout(startId: Int) {
        stopSelf()
    }

    override fun onDestroy() {
        running = false
        scope.cancel()
        super.onDestroy()
    }

    private fun goForeground(): Boolean = try {
        val notification = buildNotification(Arcom.summary(), Arcom.disconnectable())
        when {
            // Android 14+ refuse le type connectedDevice sans l'autorisation Bluetooth : on démarre
            // quand même (obligatoire), le temps que le widget affiche quoi faire.
            Build.VERSION.SDK_INT >= 34 && !Permissions.canConnect(this) ->
                startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SHORT_SERVICE)
            Build.VERSION.SDK_INT >= 29 ->
                startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
            else -> startForeground(NOTIFICATION_ID, notification)
        }
        true
    } catch (e: Exception) {
        Log.w(Arcom.TAG, "Service de premier plan refusé", e)
        false
    }

    private fun onChange() {
        if (Arcom.needsService()) {
            stopping?.cancel()
            stopping = null
            val text = Arcom.summary()
            val disconnectable = Arcom.disconnectable()
            if ("$text|$disconnectable" != shown) {
                shown = "$text|$disconnectable"
                getSystemService(NotificationManager::class.java)
                    .notify(NOTIFICATION_ID, buildNotification(text, disconnectable))
            }
        } else if (stopping == null) {
            stopping = scope.launch {
                delay(STOP_DELAY_MS)
                if (!Arcom.needsService()) {
                    stopForeground(STOP_FOREGROUND_REMOVE)
                    stopSelf()
                }
                stopping = null
            }
        }
    }

    /** [disconnectable] : « Tout déconnecter » aurait un effet (la connexion auto ne se déconnecte pas). */
    private fun buildNotification(text: String, disconnectable: Boolean): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(getColor(R.color.accent))
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text.substringBefore('\n'))
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
        if (disconnectable) {
            val disconnect = PendingIntent.getForegroundService(
                this, 1, Intent(this, LinkService::class.java).setAction(ACTION_DISCONNECT),
                PendingIntent.FLAG_IMMUTABLE,
            )
            builder.addAction(Notification.Action.Builder(null, getString(R.string.disconnect_all), disconnect).build())
        }
        return builder.build()
    }

    companion object {
        const val ACTION_WIDGET = "local.telecommande.arcom.WIDGET"
        const val ACTION_DISCONNECT = "local.telecommande.arcom.DISCONNECT"
        const val EXTRA_WIDGET = "widget"
        const val EXTRA_OP = "op"
        private const val CHANNEL = "links"
        private const val NOTIFICATION_ID = 1
        private const val STOP_DELAY_MS = 1_500L

        var running = false
            private set

        /** Démarre le service s'il le faut (il s'arrête seul quand plus rien ne le justifie). */
        fun sync(context: Context) {
            if (running || !Arcom.needsService()) return
            try {
                context.startForegroundService(Intent(context, LinkService::class.java))
            } catch (e: Exception) {
                // Android 12+ interdit de le démarrer depuis l'arrière-plan : il le sera à la prochaine
                // ouverture de l'appli ou au prochain appui sur un widget.
                Log.i(Arcom.TAG, "Service non démarré : ${e.message}")
            }
        }
    }
}
