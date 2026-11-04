"""Serveur local : consigne, réglage de connexion et API, avec un module simulé (sans Bluetooth)."""
import asyncio

import pytest

pytest.importorskip("aiohttp")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import arcomlib  # noqa: E402
import server  # noqa: E402

MAC = "AA:BB:CC:DD:EE:01"


class FakeModule:
    """Client BLE simulé : …c69 reflète la consigne et la ventilation reçues (si `reflect`)."""

    def __init__(self, state: str = "000406000000", reflect: bool = True):
        self.state = bytearray(bytes.fromhex(state))
        self.reflect = reflect
        self.is_connected = True
        self.writes: list[str] = []
        self.reads = 0

    async def write_gatt_char(self, uuid, data, response):
        self.writes.append(bytes(data).hex())
        action = data[0]
        if self.reflect and action >> 4 == 0xD:
            self.state[2] = action & 0x0F
        elif self.reflect and action >> 4 == 0xB:
            self.state[1] = action & 0x0F

    async def read_gatt_char(self, uuid):
        self.reads += 1
        return bytes(self.state)

    async def disconnect(self):
        self.is_connected = False


@pytest.fixture
def module(monkeypatch, tmp_path):
    """Registre temporaire (jamais le modules.json du poste) et module simulé ; relecture CVC immédiate."""
    registry = arcomlib.Registry(tmp_path / "modules.json")
    registry.seen(MAC, "ARC_1302", -60)
    monkeypatch.setattr(arcomlib, "Registry", lambda: registry)
    fake = FakeModule()
    connections = []

    async def connect(mac, disconnected_callback=None):
        connections.append(mac)
        fake.is_connected = True
        return fake

    async def bluetooth_state():
        return "off"  # pas de recherche ni d'entretien pendant les tests

    monkeypatch.setattr(arcomlib, "connect", connect)
    monkeypatch.setattr(arcomlib, "bluetooth_state", bluetooth_state)
    monkeypatch.setattr(server, "HVAC_REFLECT_S", 0.01)
    fake.connections = connections
    return fake


async def settle():
    """Laisse passer la relecture d'état et la libération du module."""
    await asyncio.sleep(0.1)


def run(coro):
    return asyncio.run(coro)


def test_setpoint_step_reads_current_setpoint_first(module):
    """Consigne inconnue : le module est relu avant d'envoyer le cran (ici +3, donc +4)."""
    module.state[2] = 9

    async def scenario():
        link = server.Manager().link(MAC)
        r = await link.command("temp", "up", None, "0000")
        assert r["action"] == "10"
        assert module.writes == ["da00000000"]
        await settle()
        assert link.state["offset_temp"] == 10
        assert link.pending_setpoint() is None  # l'état relu fait foi
        assert not link.connected  # mode ponctuel : module libéré

    run(scenario())


def test_setpoint_steps_chain_before_module_reflects_them(module):
    """Deux crans rapprochés partent l'un de l'autre, pas de l'état pas encore relu."""
    module.reflect = False

    async def scenario():
        link = server.Manager().link(MAC)
        assert (await link.command("temp", "up", None, "0000"))["action"] == "7"
        assert (await link.command("temp", "up", None, "0000"))["action"] == "8"
        assert (await link.command("temp", "down", None, "0000"))["action"] == "7"
        assert module.writes == ["d700000000", "d800000000", "d700000000"]

    run(scenario())


@pytest.mark.parametrize(("offset", "action", "expected"), [(12, "up", "12"), (0, "down", "0")])
def test_setpoint_step_is_bounded(module, offset, action, expected):
    module.state[2] = offset

    async def scenario():
        link = server.Manager().link(MAC)
        assert (await link.command("temp", action, None, "0000"))["action"] == expected

    run(scenario())


def test_absolute_setpoint_and_ventilation(module):
    async def scenario():
        mgr = server.Manager()
        link = mgr.link(MAC)
        assert (await link.command("temp", "3", None, "0000"))["action"] == "3"
        assert mgr.public(MAC)["setpoint"] == 3  # affichée tout de suite, avant la relecture
        await link.command("vent", "2", None, "0000")
        assert module.writes == ["d300000000", "b200000000"]
        await settle()
        assert (link.state["offset_temp"], link.state["ventilation"]) == (3, 2)
        assert mgr.public(MAC)["setpoint"] is None

    run(scenario())


def test_invalid_setpoint_is_refused_before_connecting(module):
    async def scenario():
        link = server.Manager().link(MAC)
        with pytest.raises(ValueError):
            await link.command("temp", "13", None, "0000")
        assert module.connections == []

    run(scenario())


def test_api_keep_connected_without_auto_connect(module):
    """« Connexion auto » retirée : réglage ignoré, « Se déconnecter » toujours possible."""

    async def scenario():
        app = server.build_app(asyncio.Event())
        async with TestClient(TestServer(app)) as client:
            path = f"/api/modules/{MAC}"
            body = await (await client.patch(path, json={"auto_connect": True})).json()
            assert "auto_connect" not in body
            assert body["keep_connected"] is False
            await settle()
            assert module.connections == []  # rien ne se connecte d'office

            body = await (await client.patch(path, json={"keep_connected": True})).json()
            assert body["keep_connected"] is True
            await settle()
            assert app["mgr"].link(MAC).connected  # activer le maintien connecte tout de suite

            r = await client.post(f"{path}/disconnect")
            assert r.status == 200
            assert not app["mgr"].link(MAC).connected

            r = await client.post(f"{path}/command", json={"kind": "temp", "action": "down"})
            assert (await r.json())["action"] == "5"
            assert "auto_connect" not in app["mgr"].registry.get(MAC)

    run(scenario())
