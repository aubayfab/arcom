package local.telecommande.arcom

import android.app.Application

class ArcomApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Arcom.init(this)
    }
}
