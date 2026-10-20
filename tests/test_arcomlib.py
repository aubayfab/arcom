"""Protocole et registre (arcomlib) : sans Bluetooth ni module."""
import json

import pytest

import arcomlib

MAC = "AA:BB:CC:DD:EE:01"


@pytest.mark.parametrize(("pin", "expected"), [("0000", "00000000"), ("1234", "01020304"), ("9090", "09000900")])
def test_pin_bytes(pin, expected):
    assert arcomlib.pin_to_bytes(pin).hex() == expected


@pytest.mark.parametrize("pin", ["", "123", "12345", "12a4", "-123"])
def test_pin_rejected(pin):
    with pytest.raises(ValueError):
        arcomlib.pin_to_bytes(pin)


@pytest.mark.parametrize(("groups", "mask"), [(None, 0x0F), ([], 0x0F), ([1], 0x01), ([1, 3], 0x05),
                                              ("13", 0x05), ([1, 2, 3, 4], 0x0F), ([4, 4], 0x08)])
def test_groups_mask(groups, mask):
    assert arcomlib.groups_mask(groups) == mask


@pytest.mark.parametrize("groups", [[0], [5], ["x"]])
def test_groups_rejected(groups):
    with pytest.raises(ValueError):
        arcomlib.groups_mask(groups)


# Tableau « Trame de commande » de docs/protocole.md (tous groupes, PIN 0000).
@pytest.mark.parametrize(("kind", "action", "frame"), [
    ("light", "off", "0f00000000"),
    ("light", "on", "1f00000000"),
    ("light", "up", "2f00000000"),
    ("light", "down", "3f00000000"),
    ("light", "stop", "4f00000000"),
    ("blind", "up", "5f00000000"),
    ("blind", "down", "6f00000000"),
    ("blind", "stop", "7f00000000"),
    ("blind", "rot_up", "8f00000000"),
    ("blind", "rot_down", "9f00000000"),
    ("blind", "rot_stop", "af00000000"),
    ("vent", "4", "b400000000"),
    ("occ", "on", "c100000000"),
    ("occ", "off", "c000000000"),
    ("temp", "6", "d600000000"),
    ("LIGHT", "ON", "1f00000000"),
])
def test_frames(kind, action, frame):
    assert arcomlib.frame(arcomlib.build_action(kind, action)).hex() == frame


def test_frame_with_groups_and_pin():
    assert arcomlib.frame(arcomlib.build_action("light", "on", [1, 3]), "1234").hex() == "1501020304"


def test_hvac_ignores_groups():
    assert arcomlib.build_action("vent", "2", [1]) == 0xB2


@pytest.mark.parametrize(("kind", "action"), [("light", "dim"), ("blind", "left"), ("vent", "5"),
                                              ("temp", "13"), ("temp", "-1"), ("door", "open")])
def test_invalid_actions(kind, action):
    with pytest.raises(ValueError):
        arcomlib.build_action(kind, action)


def test_parse_state():
    assert arcomlib.parse_state(bytes.fromhex("010406000000")) == {
        "occupation": 1, "ventilation": 4, "offset_temp": 6, "window_alarm": 0, "alarm": 0, "count": 0}
    assert arcomlib.parse_state(b"\x01\x02") is None


def test_parse_points_skips_empty_slots():
    data = bytes.fromhex("b400" "23" "0100") + bytes(5) + bytes.fromhex("0201" "2d" "0000")
    assert arcomlib.parse_points(data) == {0x00B4: 0x23, 0x0102: 0x2D}


@pytest.mark.parametrize(("action", "direction"), [("up", "up"), ("rot_up", "up"), ("down", "down"),
                                                   ("rot_down", "down"), ("stop", None), ("rot_stop", None)])
def test_blind_direction(action, direction):
    assert arcomlib.blind_direction(action) == direction


def test_is_arcom():
    assert arcomlib.is_arcom("ARC_1302", [])
    assert arcomlib.is_arcom(None, [arcomlib.SVC_COMMAND.upper()])
    assert not arcomlib.is_arcom("Casque", ["0000180f-0000-1000-8000-00805f9b34fb"])


def test_registry_round_trip(tmp_path):
    path = tmp_path / "modules.json"
    reg = arcomlib.Registry(path)
    assert reg.modules == {}
    m = reg.seen(MAC.lower(), "ARC_1302", -60)
    assert m["mac"] == MAC
    assert (m["pin"], m["pinned"], m["auto_connect"], m["keep_connected"]) == ("0000", False, False, False)
    reg.update(MAC, label="Mon bureau", keep_connected=True)
    reg.save()

    again = arcomlib.Registry(path)
    assert again.get("mon BUREAU")["keep_connected"] is True
    assert again.get("arc_1302") is again.get(MAC.lower())
    assert again.get("inconnu") is None
    assert json.loads(path.read_text(encoding="utf-8"))["modules"][0]["label"] == "Mon bureau"


def test_registry_keeps_name_when_advertisement_has_none(tmp_path):
    reg = arcomlib.Registry(tmp_path / "modules.json")
    reg.seen(MAC, "ARC_1302", -60)
    m = reg.seen(MAC, None, None)
    assert (m["name"], m["rssi"]) == ("ARC_1302", -60)


def test_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCOM_DATA", str(tmp_path))
    assert arcomlib.data_dir() == tmp_path
    monkeypatch.delenv("ARCOM_DATA")
    # Depuis les sources (pyproject.toml à côté) : le dossier du projet.
    assert arcomlib.data_dir() == arcomlib.Path(arcomlib.__file__).parent


def test_version_matches_version_file():
    version = (arcomlib.Path(arcomlib.__file__).parent / "VERSION").read_text(encoding="utf-8").strip()
    assert arcomlib.version() == version
    assert version.count(".") == 2 and all(part.isdigit() for part in version.split("."))
