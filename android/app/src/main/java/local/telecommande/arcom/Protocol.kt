package local.telecommande.arcom

import android.os.ParcelUuid
import java.util.Locale
import java.util.UUID

/**
 * Protocole des modules Arcom, repris de arcomlib.py (lui-même tiré de l'APK myArcom 1.2.1).
 *
 * Trame écrite sur …c67 : [octet d'action][PIN sur 4 octets]. L'octet d'action porte l'action dans
 * le nibble haut et le masque de groupes dans le nibble bas (bit0 = G1 … bit3 = G4, F = tous).
 * Sans le suffixe PIN, le module acquitte la trame mais ne l'exécute pas.
 */
object Protocol {
    private fun uuid(last: Int): UUID =
        UUID.fromString(String.format(Locale.ROOT, "854dbb8e-f11e-11e5-9ce9-5e5517507c%02x", last))

    val SVC_COMMAND: UUID = uuid(0x66)
    val WRITE_COMMAND: UUID = uuid(0x67)
    val SVC_STATE: UUID = uuid(0x68)
    val READ_STATE: UUID = uuid(0x69)

    const val DEFAULT_PIN = "0000"

    /** Groupes 1..4 -> masque ; vide -> 0x0F (tous). */
    fun groupsMask(groups: Set<Int>): Int {
        if (groups.isEmpty()) return 0x0F
        var mask = 0
        for (g in groups) {
            require(g in 1..4) { "Les groupes vont de 1 à 4" }
            mask = mask or (1 shl (g - 1))
        }
        return mask
    }

    /** "0000" -> 00 00 00 00 ; "1234" -> 01 02 03 04. */
    fun pinBytes(pin: String): ByteArray {
        require(pin.length == 4 && pin.all { it in '0'..'9' }) { "Le PIN doit faire 4 chiffres (ex. 0000)" }
        return ByteArray(4) { (pin[it] - '0').toByte() }
    }

    fun frame(code: Int, pin: String = DEFAULT_PIN): ByteArray = byteArrayOf(code.toByte()) + pinBytes(pin)

    fun isArcom(name: String?, uuids: List<ParcelUuid>?): Boolean =
        name?.startsWith("ARC_") == true || uuids?.any { it.uuid == SVC_COMMAND } == true
}

enum class Direction { UP, DOWN }

enum class LightAction(val code: Int) { OFF(0x00), ON(0x10), UP(0x20), DOWN(0x30), STOP(0x40) }

/** [direction] : sens de la course ou de l'orientation, null pour un arrêt. */
enum class BlindAction(val code: Int, val direction: Direction?) {
    UP(0x50, Direction.UP), DOWN(0x60, Direction.DOWN), STOP(0x70, null),
    ROT_UP(0x80, Direction.UP), ROT_DOWN(0x90, Direction.DOWN), ROT_STOP(0xA0, null),
}

sealed class Command {
    /** Octet d'action complet (action | groupes, ou action | valeur pour le CVC). */
    abstract val code: Int

    /** Commande CVC : …c69 la reflète environ 1,5 s plus tard. */
    val isHvac: Boolean get() = code >= 0xB0

    /**
     * Début d'un appui maintenu (variation, orientation des lames) : sans maintien de la connexion,
     * la liaison reste ouverte jusqu'au « stop » qui suit, au lieu d'être libérée après la commande.
     */
    val startsHold: Boolean
        get() = when (this) {
            is Light -> action == LightAction.UP || action == LightAction.DOWN
            is Blind -> action == BlindAction.ROT_UP || action == BlindAction.ROT_DOWN
            else -> false
        }

    data class Light(val action: LightAction, val groups: Set<Int> = emptySet()) : Command() {
        override val code: Int get() = action.code or Protocol.groupsMask(groups)
    }

    data class Blind(val action: BlindAction, val groups: Set<Int> = emptySet()) : Command() {
        override val code: Int get() = action.code or Protocol.groupsMask(groups)
    }

    /** 0 = arrêt, 1..3, 4 = auto. */
    data class Ventilation(val level: Int) : Command() {
        init { require(level in 0..4) { "Ventilation : 0..4" } }
        override val code: Int get() = 0xB0 or level
    }

    data class Occupation(val occupied: Boolean) : Command() {
        override val code: Int get() = 0xC0 or (if (occupied) 1 else 0)
    }

    /** Offset de consigne 0..12, 6 = neutre. */
    data class Setpoint(val offset: Int) : Command() {
        init { require(offset in 0..12) { "Offset de consigne : 0..12" } }
        override val code: Int get() = 0xD0 or offset
    }
}

/** Caractéristique …c69 : [occupation][ventilation][offsetTemp][alarmeFenêtre][alarme][comptage]. */
data class Hvac(
    val occupation: Int,
    val ventilation: Int,
    val offsetTemp: Int,
    val windowAlarm: Int,
    val alarm: Int,
    val count: Int,
) {
    companion object {
        fun parse(data: ByteArray?): Hvac? {
            if (data == null || data.size < 6) return null
            fun u(i: Int) = data[i].toInt() and 0xFF
            return Hvac(u(0), u(1), u(2), u(3), u(4), u(5))
        }
    }
}

fun ByteArray.hex(): String = joinToString("") { String.format(Locale.ROOT, "%02x", it.toInt() and 0xFF) }
