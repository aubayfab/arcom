"""Protocole, registre des modules et connexion BLE rapide — partagé par arcom_cli.py et server.py.

bleak et asyncio ne sont importés qu'à l'usage : la CLI qui passe par le serveur n'en paie pas
le coût (~0,5 s à l'import sous Windows).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

UUID_BASE = "854dbb8e-f11e-11e5-9ce9-5e5517507c{:02x}"
SVC_COMMAND = UUID_BASE.format(0x66)
SVC_STATE = UUID_BASE.format(0x68)
WRITE_COMMAND = UUID_BASE.format(0x67)
READ_COMMAND = UUID_BASE.format(0x69)
# Points de donnée du module (capteurs / retours du régulateur), enregistrements de 5 octets.
# Non utilisés par l'app d'origine ; 0x00b4 suit l'éclairage (35 allumé, 45 éteint, ~3,5 s de retard).
SVC_POINTS = UUID_BASE.format(0x86)
POINT_CHARS = [UUID_BASE.format(x) for x in (0x87, 0x88, 0x89, 0xAE, 0xAF)]

# Nibble haut de l'octet d'action. Le nibble bas porte le masque de groupes.
LIGHT = {"off": 0x00, "on": 0x10, "up": 0x20, "down": 0x30, "stop": 0x40}
BLIND = {"up": 0x50, "down": 0x60, "stop": 0x70,
         "rot_up": 0x80, "rot_down": 0x90, "rot_stop": 0xA0}
VENT = 0xB0   # | 0..4 (0=arrêt, 4=auto)
OCCUP = 0xC0  # | 0/1
TEMP = 0xD0   # | 0..12 (6 = consigne neutre)
# Début d'un appui maintenu (variation, orientation des lames) : sans maintien de la connexion,
# la liaison reste ouverte jusqu'au « stop » qui suit, au lieu d'être libérée après la commande.
HOLD_ACTIONS = {("light", "up"), ("light", "down"), ("blind", "rot_up"), ("blind", "rot_down")}

DEFAULT_PIN = "0000"


def data_dir() -> Path:
    """Données utilisateur : ARCOM_DATA, sinon le dossier du projet quand on travaille sur les sources,
    sinon %LOCALAPPDATA%\\Arcom (appli installée, CLI installée avec pip : ils partagent le registre)."""
    if os.environ.get("ARCOM_DATA"):
        return Path(os.environ["ARCOM_DATA"])
    here = Path(__file__).parent
    if not getattr(sys, "frozen", False) and (here / "pyproject.toml").exists():
        return here
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Arcom"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "arcom"


def version() -> str:
    """Version des sources (fichier VERSION), sinon celle du paquet installé avec pip."""
    try:
        return (Path(__file__).parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as installed_version

        try:
            return installed_version("telecommande-arcom")
        except PackageNotFoundError:
            return "inconnue"


REGISTRY_PATH = data_dir() / "modules.json"


def pin_to_bytes(pin: str) -> bytes:
    """'0000' -> 00 00 00 00 ; '1234' -> 01 02 03 04. Sans ce suffixe, le module ignore la trame."""
    if not pin.isdigit() or len(pin) != 4:
        raise ValueError("Le PIN doit faire 4 chiffres (ex. 0000)")
    return bytes(int(d) for d in pin)


def groups_mask(groups) -> int:
    """Groupes 1..4 -> masque ; vide/None -> 0x0F (tous)."""
    if not groups:
        return 0x0F
    mask = 0
    for g in groups:
        g = int(g)
        if not 1 <= g <= 4:
            raise ValueError("Les groupes vont de 1 à 4")
        mask |= 1 << (g - 1)
    return mask


def build_action(kind: str, action: str, groups=None) -> int:
    kind, action = kind.lower(), str(action).lower()
    if kind == "light":
        if action not in LIGHT:
            raise ValueError(f"Action lumière inconnue : {action} ({', '.join(LIGHT)})")
        return LIGHT[action] | groups_mask(groups)
    if kind == "blind":
        if action not in BLIND:
            raise ValueError(f"Action store inconnue : {action} ({', '.join(BLIND)})")
        return BLIND[action] | groups_mask(groups)
    if kind == "vent":
        v = int(action)
        if not 0 <= v <= 4:
            raise ValueError("Ventilation : 0..4")
        return VENT | v
    if kind == "occ":
        return OCCUP | (1 if action in ("1", "on", "oui", "true") else 0)
    if kind == "temp":
        t = int(action)
        if not 0 <= t <= 12:
            raise ValueError("Offset de consigne : 0..12")
        return TEMP | t
    raise ValueError(f"Catégorie inconnue : {kind} (light, blind, vent, occ, temp)")


def frame(action_byte: int, pin: str = DEFAULT_PIN) -> bytes:
    return bytes([action_byte & 0xFF]) + pin_to_bytes(pin)


def parse_points(data: bytes) -> dict[int, int]:
    """[id 2 octets LE][valeur][type 2 octets] répétés ; les id nuls sont des emplacements vides."""
    points = {}
    for i in range(0, len(data) - 4, 5):
        rid = data[i] | data[i + 1] << 8
        if rid:
            points[rid] = data[i + 2]
    return points


def blind_direction(action: str) -> str | None:
    """'up' / 'down' pour une course ou une orientation, None pour un arrêt."""
    return {"up": "up", "rot_up": "up", "down": "down", "rot_down": "down"}.get(action)


def parse_state(data: bytes) -> dict | None:
    """Caractéristique …c69 : [occupation][ventilation][offsetTemp][alarmeFenêtre][alarme][comptage]."""
    if len(data) < 6:
        return None
    return {"occupation": data[0], "ventilation": data[1], "offset_temp": data[2],
            "window_alarm": data[3], "alarm": data[4], "count": data[5]}


class Registry:
    """modules.json : modules connus, indexés par MAC (un module connecté n'émet plus, on garde sa MAC).

    Par module : label (nom affiché), pinned (favori ★, simple classement), pin (code à 4 chiffres),
    auto_connect (« Connexion auto ») et keep_connected (« Maintenir la connexion »), faux par défaut.
    """

    def __init__(self, path: Path = REGISTRY_PATH):
        self.path = path
        self.modules: dict[str, dict] = {}
        self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.modules = {m["mac"].upper(): m for m in data.get("modules", [])}
        except FileNotFoundError:
            self.modules = {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        data = {"modules": sorted(self.modules.values(), key=lambda m: m.get("name") or m["mac"])}
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, key: str) -> dict | None:
        """Par MAC, nom (ARC_1302) ou libellé, sans tenir compte de la casse."""
        k = key.strip().upper()
        if k in self.modules:
            return self.modules[k]
        for m in self.modules.values():
            if (m.get("name") or "").upper() == k or (m.get("label") or "").upper() == k:
                return m
        return None

    def seen(self, mac: str, name: str | None, rssi: int | None) -> dict:
        m = self.modules.setdefault(mac.upper(), {"mac": mac.upper(), "name": name, "label": "",
                                                  "pinned": False, "pin": DEFAULT_PIN,
                                                  "auto_connect": False, "keep_connected": False})
        if name:
            m["name"] = name
        if rssi is not None:
            m["rssi"] = rssi
        m["last_seen"] = int(time.time())
        return m

    def update(self, mac: str, **fields) -> dict:
        m = self.modules[mac.upper()]
        m.update(fields)
        return m


async def bluetooth_state() -> str:
    """'on', 'off' (radio coupée, ex. mode avion), 'absent' (pas d'adaptateur) ou 'unknown'."""
    try:
        from winrt.windows.devices.radios import Radio, RadioKind, RadioState

        for radio in await Radio.get_radios_async():
            if radio.kind == RadioKind.BLUETOOTH:
                return "on" if radio.state == RadioState.ON else "off"
        return "absent"
    except Exception:
        return "unknown"


def is_arcom(name: str | None, service_uuids) -> bool:
    return bool(name and name.startswith("ARC_")) or SVC_COMMAND in [u.lower() for u in service_uuids]


async def scan(duration: float = 8.0) -> list[dict]:
    """Scan actif ; renvoie [{mac, name, rssi}] des modules Arcom, du plus proche au plus lointain."""
    import asyncio

    from bleak import BleakScanner

    found: dict[str, dict] = {}

    def on_adv(device, adv):
        name = adv.local_name or device.name
        if is_arcom(name, adv.service_uuids):
            e = found.setdefault(device.address.upper(), {"mac": device.address.upper(), "name": name, "rssi": adv.rssi})
            e["name"] = name or e["name"]
            e["rssi"] = max(e["rssi"], adv.rssi)

    async with BleakScanner(detection_callback=on_adv, scanning_mode="active"):
        await asyncio.sleep(duration)
    return sorted(found.values(), key=lambda e: -e["rssi"])


async def find_by_name(name: str, timeout: float = 10.0) -> dict | None:
    """Scan qui s'arrête dès que le module nommé est vu."""
    from bleak import BleakScanner

    hit = {}

    def match(device, adv):
        n = adv.local_name or device.name
        if n and n.upper() == name.upper():
            hit.update(mac=device.address.upper(), name=n, rssi=adv.rssi)
            return True
        return False

    dev = await BleakScanner.find_device_by_filter(match, timeout=timeout)
    return hit if dev else None


async def connect(mac: str, disconnected_callback=None, timeout: float = 20.0):
    """Connexion sans scan préalable, découverte limitée aux services utiles.

    ~3,5–5 s (le module doit d'abord émettre une annonce) ; ~0,3 s si Windows garde encore la
    liaison d'une session précédente. Sans cache GATT, la première fois, compter quelques secondes de plus.
    """
    from bleak import BleakClient
    from bleak.backends.device import BLEDevice

    last_error: Exception | None = None
    for cached, attempt_timeout in ((True, min(timeout, 8.0)), (False, timeout)):
        client = BleakClient(BLEDevice(mac.upper(), None, None),
                             disconnected_callback=disconnected_callback,
                             services=[SVC_COMMAND, SVC_STATE, SVC_POINTS],
                             winrt={"use_cached_services": cached},
                             timeout=attempt_timeout)
        try:
            await client.connect()
        except Exception as e:  # cache absent, module hors de portée, déjà occupé…
            last_error = e
            continue
        if client.services.get_characteristic(WRITE_COMMAND) is not None:
            return client
        last_error = ConnectionError("caractéristique de commande absente (cache GATT incomplet, "
                                     "ou module déjà tenu par un autre processus comme server.py)")
        await client.disconnect()
    raise ConnectionError(f"Connexion impossible à {mac} : {last_error}") from last_error


def request_link_profile(client):
    """Windows 11 : demande l'intervalle de connexion le plus court que le module tolère.

    Le module veut 150–300 ms (caractéristique 2A04) ; laissé à lui-même, une écriture prend
    ~700 ms. Les profils plus rapides (15 ms, 30–60 ms) sont refusés : le module raccroche après
    30–40 s. PowerOptimized (90–180 ms) chevauche sa plage : liaison stable à 180 ms, écriture
    ~360 ms (la charge bascule dès réception, < 180 ms). La requête doit rester vivante : fermer
    l'objet renvoyé la révoque. Renvoie None si l'API n'existe pas (Windows 10, autre OS).
    """
    try:
        import winrt.windows.devices.bluetooth as bt

        device = client._backend._requester  # BluetoothLEDevice de la session bleak
        return device.request_preferred_connection_parameters(
            bt.BluetoothLEPreferredConnectionParameters.power_optimized)
    except Exception:
        return None
