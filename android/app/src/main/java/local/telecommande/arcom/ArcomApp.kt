package local.telecommande.arcom

import android.app.Application
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class ArcomApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Arcom.init(this)
    }
}

/** Démarrage du téléphone ou mise à jour de l'appli : reconnecte les modules en connexion auto, comme server.py. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        Arcom.init(context)
        LinkService.sync(context)
        Widgets.renderAll(context)
    }
}
