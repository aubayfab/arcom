package local.telecommande.arcom

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Trames de référence du README (relevées sur l'app d'origine et vérifiées sur les modules). */
class ProtocolTest {
    private fun frame(cmd: Command, pin: String = Protocol.DEFAULT_PIN) = Protocol.frame(cmd.code, pin).hex()

    @Test
    fun lights() {
        assertEquals("0f00000000", frame(Command.Light(LightAction.OFF)))
        assertEquals("1f00000000", frame(Command.Light(LightAction.ON)))
        assertEquals("2f00000000", frame(Command.Light(LightAction.UP)))
        assertEquals("3f00000000", frame(Command.Light(LightAction.DOWN)))
        assertEquals("4f00000000", frame(Command.Light(LightAction.STOP)))
    }

    @Test
    fun blinds() {
        assertEquals("5f00000000", frame(Command.Blind(BlindAction.UP)))
        assertEquals("6f00000000", frame(Command.Blind(BlindAction.DOWN)))
        assertEquals("7f00000000", frame(Command.Blind(BlindAction.STOP)))
        assertEquals("8f00000000", frame(Command.Blind(BlindAction.ROT_UP)))
        assertEquals("9f00000000", frame(Command.Blind(BlindAction.ROT_DOWN)))
        assertEquals("af00000000", frame(Command.Blind(BlindAction.ROT_STOP)))
    }

    @Test
    fun hvac() {
        assertEquals("b400000000", frame(Command.Ventilation(4)))
        assertEquals("c100000000", frame(Command.Occupation(true)))
        assertEquals("c000000000", frame(Command.Occupation(false)))
        assertEquals("d800000000", frame(Command.Setpoint(8)))
    }

    @Test
    fun groupsAndPin() {
        assertEquals("1501020304", frame(Command.Light(LightAction.ON, setOf(1, 3)), "1234"))
        assertEquals("6800000000", frame(Command.Blind(BlindAction.DOWN, setOf(4))))
        assertEquals(0x0F, Protocol.groupsMask(setOf(1, 2, 3, 4)))
    }

    /** Sans maintien de la connexion, ces commandes gardent la liaison jusqu'au « stop » qui suit. */
    @Test
    fun holdStarts() {
        val holds = listOf(
            Command.Light(LightAction.UP), Command.Light(LightAction.DOWN),
            Command.Blind(BlindAction.ROT_UP), Command.Blind(BlindAction.ROT_DOWN),
        )
        assertTrue(holds.all { it.startsHold })
        val others = listOf(
            Command.Light(LightAction.ON), Command.Light(LightAction.STOP), Command.Blind(BlindAction.UP),
            Command.Blind(BlindAction.ROT_STOP), Command.Ventilation(4), Command.Setpoint(6),
        )
        assertFalse(others.any { it.startsHold })
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsShortPin() {
        Protocol.pinBytes("12")
    }

    @Test
    fun parsesState() {
        val state = Hvac.parse(byteArrayOf(1, 4, 6, 0, 0, 0))!!
        assertEquals(1, state.occupation)
        assertEquals(4, state.ventilation)
        assertEquals(6, state.offsetTemp)
        assertNull(Hvac.parse(byteArrayOf(1, 2)))
    }
}
