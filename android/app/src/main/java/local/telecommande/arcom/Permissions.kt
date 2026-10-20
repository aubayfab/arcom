package local.telecommande.arcom

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build

object Permissions {
    /** Indispensables : Android 12+ « Appareils à proximité » ; avant, la localisation (pour le scan). */
    val required: Array<String>
        get() = if (Build.VERSION.SDK_INT >= 31) {
            arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        } else {
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        }

    /** Facultative : sans elle, la notification du service reste invisible (le service marche quand même). */
    val optional: Array<String>
        get() = if (Build.VERSION.SDK_INT >= 33) arrayOf(Manifest.permission.POST_NOTIFICATIONS) else emptyArray()

    private fun granted(ctx: Context, permission: String) =
        ctx.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    /** Se connecter à un module connu : pas besoin de la localisation avant Android 12. */
    fun canConnect(ctx: Context) = Build.VERSION.SDK_INT < 31 || granted(ctx, Manifest.permission.BLUETOOTH_CONNECT)

    fun canScan(ctx: Context) = required.all { granted(ctx, it) }
}
