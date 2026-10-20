"""Ligne de commande : analyse des commandes, sans serveur ni Bluetooth."""
import io

import pytest

import arcom_cli
import arcomlib
from arcom_cli import Op


@pytest.mark.parametrize(("words", "op"), [
    ([], Op("noop")),
    (["quit"], Op("quit")),
    (["Q"], Op("quit")),
    (["groups", "13"], Op("groups", ["1", "3"])),
    (["groups", "all"], Op("groups", None)),
    (["groups"], Op("groups", None)),
    (["connect"], Op("link", "connect")),
    (["keep", "on"], Op("set", "keep_connected", True)),
    (["maintien", "non"], Op("set", "keep_connected", False)),
    (["auto", "OFF"], Op("set", "auto_connect", False)),
    (["light", "ON"], Op("cmd", "light", "on")),
])
def test_repl_parse(words, op):
    assert arcom_cli.repl_parse(words) == op


def test_repl_parse_rejects_bad_switch(capsys):
    assert arcom_cli.repl_parse(["keep", "peut-être"]) == Op("noop")
    assert "on ou off" in capsys.readouterr().out


@pytest.mark.parametrize(("module", "text"), [
    ({}, "ponctuel"),
    ({"keep_connected": True}, "maintien"),
    ({"auto_connect": True, "keep_connected": True}, "auto"),
])
def test_mode_text(module, text):
    assert arcom_cli.mode_text(module) == text


def test_module_path_escapes_labels():
    assert arcom_cli.module_path("Mon bureau/2") == "/api/modules/Mon%20bureau%2F2"


def test_version(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["arcom", "--version"])
    with pytest.raises(SystemExit) as exit_info:
        arcom_cli.main()
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"arcom {arcomlib.version()}"


def test_list_survives_redirected_cp1252_output(monkeypatch, tmp_path):
    """Sortie redirigée sous Windows : la page de code cp1252 n'a pas « ★ »."""
    registry = arcomlib.Registry(tmp_path / "modules.json")
    registry.seen("AA:BB:CC:DD:EE:01", "ARC_1302", -60)["pinned"] = True
    monkeypatch.setattr(arcomlib, "Registry", lambda: registry)
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.argv", ["arcom", "--direct", "list"])
    arcom_cli.main()
    out.flush()
    assert "? ARC_1302" in out.buffer.getvalue().decode("cp1252")


def test_invalid_action_is_reported_before_connecting(monkeypatch):
    monkeypatch.setattr("sys.argv", ["arcom", "--direct", "ARC_1302", "light", "dim"])
    with pytest.raises(SystemExit, match="Action lumière inconnue"):
        arcom_cli.main()
