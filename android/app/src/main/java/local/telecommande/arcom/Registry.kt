package local.telecommande.arcom

import android.util.AtomicFile
import android.util.Log
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.File
import java.io.FileNotFoundException
import java.io.IOException

/**
 * [pinned] : favori ★ (en tête de liste, sans effet sur la connexion). [autoConnect] : « Connexion
 * auto », connecté en permanence. [keepConnected] : « Maintenir la connexion » jusqu'à « Se
 * déconnecter ». Sans l'un ni l'autre (défaut), chaque commande se connecte puis libère le module.
 */
class ModuleInfo(
    val mac: String,
    var name: String?,
    var label: String = "",
    var pinned: Boolean = false,
    var pin: String = Protocol.DEFAULT_PIN,
    var rssi: Int? = null,
    var lastSeen: Long? = null,
    var autoConnect: Boolean = false,
    var keepConnected: Boolean = false,
) {
    val displayName: String get() = label.ifBlank { name ?: mac }
}

/**
 * Modules connus, au même format que le modules.json de la version PC. Un module connecté n'émet
 * plus d'annonces : c'est la MAC enregistrée ici qui permet de s'y reconnecter sans scan.
 */
class Registry(file: File) {
    private val file = AtomicFile(file)
    val modules = LinkedHashMap<String, ModuleInfo>()

    init {
        load()
    }

    fun get(mac: String): ModuleInfo? = modules[mac.uppercase()]

    private fun load() {
        val text = try {
            file.readFully().toString(Charsets.UTF_8)
        } catch (e: FileNotFoundException) {
            return
        }
        try {
            val list = JSONObject(text).optJSONArray("modules") ?: return
            for (i in 0 until list.length()) {
                val o = list.getJSONObject(i)
                val mac = o.getString("mac").uppercase()
                modules[mac] = ModuleInfo(
                    mac = mac,
                    name = o.str("name"),
                    label = o.str("label").orEmpty(),
                    pinned = o.optBoolean("pinned"),
                    pin = o.str("pin") ?: Protocol.DEFAULT_PIN,
                    rssi = if (o.isNull("rssi")) null else o.getInt("rssi"),
                    lastSeen = if (o.isNull("last_seen")) null else o.getLong("last_seen"),
                    autoConnect = o.optBoolean("auto_connect"),
                    keepConnected = o.optBoolean("keep_connected"),
                )
            }
        } catch (e: JSONException) {
            Log.w(Arcom.TAG, "modules.json illisible, ignoré", e)
        }
    }

    fun save() {
        val list = JSONArray()
        for (m in modules.values.sortedBy { it.name ?: it.mac }) {
            list.put(JSONObject().apply {
                put("mac", m.mac)
                put("name", m.name ?: JSONObject.NULL)
                put("label", m.label)
                put("pinned", m.pinned)
                put("pin", m.pin)
                put("auto_connect", m.autoConnect)
                put("keep_connected", m.keepConnected)
                m.rssi?.let { put("rssi", it) }
                m.lastSeen?.let { put("last_seen", it) }
            })
        }
        val out = file.startWrite()
        try {
            out.write(JSONObject().put("modules", list).toString(2).toByteArray(Charsets.UTF_8))
            file.finishWrite(out)
        } catch (e: IOException) {
            file.failWrite(out)
            Log.w(Arcom.TAG, "modules.json non enregistré", e)
        }
    }

    fun seen(mac: String, name: String?, rssi: Int): ModuleInfo {
        val m = modules.getOrPut(mac.uppercase()) { ModuleInfo(mac.uppercase(), name) }
        if (name != null) m.name = name
        m.rssi = rssi
        m.lastSeen = System.currentTimeMillis() / 1000
        return m
    }

    /** optString renvoie "null" pour une valeur JSON null : on veut null. */
    private fun JSONObject.str(key: String): String? = if (isNull(key)) null else getString(key)
}
