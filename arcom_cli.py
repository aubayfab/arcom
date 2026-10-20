#!/usr/bin/env python3
"""
arcom_cli.py — Télécommande en ligne de commande pour modules Arcom (ex-application myArcom).

Si le serveur (server.py) tourne, la commande passe par lui et suit les réglages de connexion du
module. Sinon, connexion directe (1,5 à 5 s), puis déconnexion.

    python arcom_cli.py scan                       # découvrir les modules (alimente modules.json)
    python arcom_cli.py list                       # modules connus et leur mode de connexion
    python arcom_cli.py ARC_1302 light off         # par nom, libellé ou MAC
    python arcom_cli.py ARC_1302 light on
    python arcom_cli.py ARC_1302 blind down        # up | down | stop | rot_up | rot_down | rot_stop
    python arcom_cli.py ARC_1302 vent 4            # ventilation 0..4 (4 = auto)
    python arcom_cli.py ARC_1302 temp 6            # offset de consigne 0..12 (6 = neutre)
    python arcom_cli.py ARC_1302 occ on
    python arcom_cli.py ARC_1302 keep on           # « Maintenir la connexion » (alias : maintien)
    python arcom_cli.py ARC_1302 auto on           # « Connexion auto »
    python arcom_cli.py ARC_1302 connect           # se connecter / se déconnecter (via le serveur,
    python arcom_cli.py ARC_1302 disconnect        #   ou en mode interactif)
    python arcom_cli.py ARC_1302                   # mode interactif

Connexion, réglée par module (« keep » et « auto » sont désactivés par défaut) :
    par défaut   chaque commande se connecte, envoie la trame, puis libère le module ; un appui
                 maintenu (light up/down, blind rot_up/rot_down) garde la liaison jusqu'à son stop
    keep on      la connexion reste ouverte entre les commandes, jusqu'à « disconnect »
    auto on      connecté en permanence (dès le démarrage du serveur) ; « disconnect » refusé

Options : --groups 13 (groupes 1 et 3 ; défaut tous)  --pin 1234 (défaut 0000)
          --direct (connexion BLE sans le serveur ; impossible tant que server.py tient le module)
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import sys
import time
from typing import NamedTuple
from urllib.parse import quote

import arcomlib

# 127.0.0.1 et non « localhost » : sous Windows, localhost tente d'abord ::1 et perd ~2 s.
PORT = int(os.environ.get("ARCOM_PORT", 8787))

SETTINGS = {"auto": "auto_connect", "keep": "keep_connected", "maintien": "keep_connected"}
SWITCH = {"on": True, "oui": True, "1": True, "true": True, "off": False, "non": False, "0": False, "false": False}
LINK_ACTIONS = ("connect", "disconnect")
STATUS_TEXT = {"connected": "connecté", "connecting": "connexion…", "disconnected": "déconnecté",
               "error": "injoignable"}
NO_SERVER = ("connect / disconnect passent par la télécommande (server.py), qui tient la connexion : "
             "lance-la, ou utilise le mode interactif (python arcom_cli.py <module>).")


class ServerDown(Exception):
    pass


class Op(NamedTuple):
    """Ligne du mode interactif : quit, noop, groups (arg = groupes ou None), link (arg = connect |
    disconnect), set (arg = réglage, value = bool), cmd (arg = catégorie, value = action)."""
    tag: str
    arg: object = None
    value: object = None


def mode_text(m: dict) -> str:
    if m.get("auto_connect"):
        return "auto"
    return "maintien" if m.get("keep_connected") else "ponctuel"


def parse_switch(value: str) -> bool:
    try:
        return SWITCH[value.lower()]
    except KeyError:
        raise ValueError(f"on ou off attendu, reçu « {value} »") from None


# --- Passage par le serveur ---------------------------------------------------

def call(method: str, path: str, body: dict | None = None, timeout: float = 30.0) -> dict:
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    try:
        conn.request(method, path, body=json.dumps(body) if body is not None else None,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
    except ConnectionRefusedError as e:
        raise ServerDown from e
    finally:
        conn.close()
    if resp.status >= 400:
        raise RuntimeError(data.decode(errors="replace") or f"HTTP {resp.status}")
    return json.loads(data or b"{}")


def server_listening() -> bool:
    """Teste le port en le réservant : sous Windows, un refus de connexion locale prend ~2 s."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", PORT))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def module_path(key: str) -> str:
    return f"/api/modules/{quote(key, safe='')}"


# --- Connexion directe ----------------------------------------------------------

async def resolve(key: str, reg: arcomlib.Registry) -> dict:
    m = reg.get(key)
    if m:
        return m
    if key.count(":") == 5:
        return reg.seen(key, None, None)
    print(f"{key} absent du registre, recherche…", file=sys.stderr)
    hit = await arcomlib.find_by_name(key)
    if not hit:
        raise SystemExit(f"Module « {key} » introuvable. Lance « python arcom_cli.py scan ».")
    m = reg.seen(hit["mac"], hit["name"], hit["rssi"])
    reg.save()
    return m


async def direct_send(args):
    reg = arcomlib.Registry()
    m = await resolve(args.target, reg)
    pin = args.pin or m.get("pin") or arcomlib.DEFAULT_PIN
    data = arcomlib.frame(arcomlib.build_action(args.kind, args.action, args.groups), pin)
    t0 = time.perf_counter()
    client = await arcomlib.connect(m["mac"])
    t1 = time.perf_counter()
    try:
        await client.write_gatt_char(arcomlib.WRITE_COMMAND, data, response=True)
        t2 = time.perf_counter()
    finally:
        await client.disconnect()
    print(f"OK · {m.get('name') or m['mac']} · {args.kind} {args.action} -> {data.hex()} "
          f"(connexion {t1 - t0:.2f} s, envoi {1000 * (t2 - t1):.0f} ms, direct)")


class DirectLink:
    """Mode interactif sans serveur, mêmes règles que lui : la liaison est libérée après chaque
    commande, sauf maintien ou connexion auto, ou appui maintenu en attente de son « stop »."""

    def __init__(self, m: dict, reg: arcomlib.Registry):
        self.m, self.reg = m, reg
        self.client = None
        self.held = False
        self.gesture = False

    @property
    def auto(self) -> bool:
        return bool(self.m.get("auto_connect"))

    @property
    def keep(self) -> bool:
        return self.auto or bool(self.m.get("keep_connected"))

    async def ensure(self):
        if self.client is None or not self.client.is_connected:
            t0 = time.perf_counter()
            self.client = await arcomlib.connect(self.m["mac"])
            print(f"  connecté ({time.perf_counter() - t0:.1f} s)")
        return self.client

    async def drop(self):
        client, self.client = self.client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def release(self):
        if not (self.auto or (self.keep and self.held) or self.gesture):
            await self.drop()

    async def send(self, kind: str, action: str, groups, pin: str) -> str:
        data = arcomlib.frame(arcomlib.build_action(kind, action, groups), pin)
        if self.keep:
            self.held = True
        client = await self.ensure()
        t0 = time.perf_counter()
        try:
            await client.write_gatt_char(arcomlib.WRITE_COMMAND, data, response=True)
        except Exception:
            await self.drop()  # liaison morte : la prochaine commande se reconnecte
            raise
        ms = 1000 * (time.perf_counter() - t0)
        if kind in ("light", "blind"):
            self.gesture = (kind, action) in arcomlib.HOLD_ACTIONS
        await self.release()
        return f"-> {data.hex()} ({ms:.0f} ms)"

    async def link(self, action: str) -> str:
        if action == "connect":
            if not self.keep:
                return "active d'abord « keep on » (sinon chaque commande se connecte, puis libère le module)"
            self.held = True
            await self.ensure()
            return "connecté"
        if self.auto:
            return "connexion auto active : « auto off » pour pouvoir déconnecter"
        self.held = False
        await self.drop()
        return "déconnecté"

    async def configure(self, key: str, value: bool) -> str:
        """Activer connecte tout de suite, désactiver libère le module (comme le serveur)."""
        was_auto, was_keep = self.auto, self.keep
        self.m[key] = value
        self.reg.save()
        if not self.keep:
            self.held = False
        elif (self.auto and not was_auto) or not was_keep:
            self.held = True
        if self.auto or (self.keep and self.held):
            await self.ensure()
        else:
            await self.release()
        return f"connexion : {mode_text(self.m)}"


async def direct_op(link: DirectLink, op: Op, groups, pin: str) -> str:
    if op.tag == "link":
        return await link.link(op.arg)
    if op.tag == "set":
        return await link.configure(op.arg, op.value)
    return await link.send(op.arg, op.value, groups, pin)


async def direct_repl(args):
    import asyncio

    reg = arcomlib.Registry()
    m = await resolve(args.target, reg)
    pin = args.pin or m.get("pin") or arcomlib.DEFAULT_PIN
    groups = args.groups
    link = DirectLink(m, reg)
    print(f"Connexion : {mode_text(m)}")
    try:
        if link.auto:
            await link.ensure()
        while True:
            try:
                op = repl_parse((await asyncio.to_thread(input, "arcom> ")).split())
            except (EOFError, KeyboardInterrupt):
                return
            if op.tag == "quit":
                return
            if op.tag == "groups":
                groups = op.arg
            elif op.tag != "noop":
                try:
                    print("  " + await direct_op(link, op, groups, pin))
                except Exception as e:  # trame invalide, module injoignable, liaison perdue…
                    print(f"  {e}")
    finally:
        await link.drop()


# --- Commandes ------------------------------------------------------------------

def cmd_scan(args, use_server: bool):
    print(f"Scan des modules Arcom ({args.timeout:.0f} s)…")
    if use_server:
        try:
            return print_modules(call("POST", "/api/scan", {"duration": args.timeout},
                                      timeout=args.timeout + 30)["modules"])
        except ServerDown:
            pass
    import asyncio
    reg = arcomlib.Registry()
    for f in asyncio.run(arcomlib.scan(args.timeout)):
        reg.seen(f["mac"], f["name"], f["rssi"])
    reg.save()
    print_modules(list(reg.modules.values()))


def cmd_list(use_server: bool):
    if use_server:
        try:
            return print_modules(call("GET", "/api/modules")["modules"])
        except ServerDown:
            pass
    print_modules(list(arcomlib.Registry().modules.values()))


def print_modules(modules):
    if not modules:
        print("Aucun module connu. Lance « python arcom_cli.py scan ».")
        return
    modules = sorted(modules, key=lambda m: (not m.get("pinned"), -(m.get("rssi") or -999)))
    print(f"   {'MODULE':<10} {'MAC':<17}  {'SIGNAL':>8}  {'CONNEXION':<9}  {'ÉTAT':<12} NOM")
    for m in modules:
        star = "★" if m.get("pinned") else " "
        rssi = f"{m['rssi']} dBm" if m.get("rssi") is not None else ""
        status = STATUS_TEXT.get(m.get("status", ""), "")
        print(f" {star} {m.get('name') or '?':<10} {m['mac']}  {rssi:>8}  {mode_text(m):<9}  {status:<12} "
              f"{m.get('label') or ''}")


def cmd_action(args, use_server: bool):
    if use_server:
        body = {"kind": args.kind, "action": args.action, "groups": args.groups, "pin": args.pin}
        try:
            r = call("POST", f"{module_path(args.target)}/command", body)
            print(f"OK · {args.target} · {args.kind} {args.action} -> {r['frame']} ({r['total_ms']} ms, serveur)")
            return
        except ServerDown:
            pass
    import asyncio
    asyncio.run(direct_send(args))


def cmd_setting(target: str, key: str, value: bool, use_server: bool):
    """« auto on|off », « keep on|off » : appliqué tout de suite par le serveur, sinon enregistré."""
    if use_server:
        try:
            m = call("PATCH", module_path(target), {key: value})
            print(f"OK · {m.get('label') or m.get('name') or target} · connexion : {mode_text(m)}")
            return
        except ServerDown:
            pass
    reg = arcomlib.Registry()
    m = reg.get(target)
    if m is None:
        raise SystemExit(f"Module « {target} » inconnu. Lance « python arcom_cli.py scan ».")
    m[key] = value
    reg.save()
    print(f"OK · {m.get('label') or m.get('name') or target} · connexion : {mode_text(m)} "
          "(enregistré, appliqué au prochain lancement de la télécommande)")


def cmd_link(target: str, action: str, use_server: bool):
    if not use_server:
        raise SystemExit(NO_SERVER)
    try:
        m = call("POST", f"{module_path(target)}/{action}")
    except ServerDown:
        raise SystemExit(NO_SERVER) from None
    print(f"OK · {m.get('label') or m.get('name') or target} · {STATUS_TEXT.get(m['status'], m['status'])}")


REPL_HELP = """\
  light on|off|up|down|stop     blind up|down|stop|rot_up|rot_down|rot_stop
  vent 0..4    temp 0..12    occ on|off    groups 13|all
  keep on|off    auto on|off    connect    disconnect    help    quit"""


def repl_parse(words: list[str]) -> Op:
    if not words:
        return Op("noop")
    head = words[0].lower()
    arg = words[1].lower() if len(words) > 1 else ""
    if head in ("quit", "exit", "q"):
        return Op("quit")
    if head == "help":
        print(REPL_HELP)
        return Op("noop")
    if head == "groups":
        return Op("groups", None if arg in ("", "all") else list(arg))
    if head in LINK_ACTIONS:
        return Op("link", head)
    if head in SETTINGS:
        try:
            return Op("set", SETTINGS[head], parse_switch(arg))
        except ValueError as e:
            print(f"  {e}")
            return Op("noop")
    return Op("cmd", head, arg)


def server_op(path: str, op: Op, groups, pin) -> str:
    if op.tag == "link":
        status = call("POST", f"{path}/{op.arg}")["status"]
        return STATUS_TEXT.get(status, status)
    if op.tag == "set":
        return f"connexion : {mode_text(call('PATCH', path, {op.arg: op.value}))}"
    r = call("POST", f"{path}/command", {"kind": op.arg, "action": op.value, "groups": groups, "pin": pin})
    return f"-> {r['frame']} ({r['total_ms']} ms)"


def cmd_repl(args, use_server: bool):
    if use_server:
        try:
            m = call("GET", module_path(args.target), timeout=2)
        except ServerDown:
            use_server = False
        except RuntimeError:
            m = {}  # module inconnu du serveur : la première commande le dira
    print(f"{args.target} — mode interactif ({'via serveur' if use_server else 'connexion directe'})")
    print(REPL_HELP)
    if not use_server:
        import asyncio
        asyncio.run(direct_repl(args))
        return
    if m:
        print(f"Connexion : {mode_text(m)}")
    groups = args.groups
    path = module_path(args.target)
    while True:
        try:
            op = repl_parse(input("arcom> ").split())
        except (EOFError, KeyboardInterrupt):
            return
        if op.tag == "quit":
            return
        if op.tag == "groups":
            groups = op.arg
        elif op.tag != "noop":
            try:
                print("  " + server_op(path, op, groups, args.pin))
            except (RuntimeError, ServerDown) as e:
                print(f"  {e or 'serveur arrêté'}")


class ShowVersion(argparse.Action):
    """--version, lue seulement à la demande : les autres commandes n'en paient pas le coût."""

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, help="affiche la version et quitte")

    def __call__(self, parser, namespace, values, option_string=None):
        print(f"{parser.prog} {arcomlib.version()}")
        parser.exit()


def main():
    # Sortie redirigée sous Windows (page de code cp1252) : « ★ » ne doit pas faire échouer la commande.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="Télécommande BLE pour modules Arcom.",
                                usage="%(prog)s [options] (scan | list | <cible> [<catégorie> <action>"
                                      " | keep|auto on|off | connect | disconnect])")
    p.add_argument("--version", action=ShowVersion)
    p.add_argument("--pin", default=None, help="code PIN à 4 chiffres (défaut : celui du registre, sinon 0000)")
    p.add_argument("--groups", default=None, help="groupes à piloter, ex. 13 (défaut : tous)")
    p.add_argument("--timeout", type=float, default=8.0, help="durée du scan (s)")
    p.add_argument("--direct", action="store_true",
                   help="connexion BLE directe, sans le serveur (qui ne doit alors pas tourner)")
    p.add_argument("rest", nargs="*")
    args = p.parse_args()
    args.groups = list(args.groups) if args.groups else None
    rest = args.rest

    if not rest:
        p.print_help()
        return
    use_server = not args.direct and server_listening()

    try:
        if not run(args, rest, use_server):
            p.print_help()
    except (ValueError, RuntimeError, ConnectionError) as e:
        raise SystemExit(f"Erreur : {e}")


def run(args, rest: list[str], use_server: bool) -> bool:
    """Exécute la commande ; False si elle n'est pas reconnue."""
    first, second = rest[0].lower(), rest[1].lower() if len(rest) > 1 else ""
    if first == "scan":
        cmd_scan(args, use_server)
    elif first == "list":
        cmd_list(use_server)
    elif len(rest) == 1:
        args.target = rest[0]
        cmd_repl(args, use_server)
    elif len(rest) == 2 and second in LINK_ACTIONS:
        cmd_link(rest[0], second, use_server)
    elif len(rest) == 3 and second in SETTINGS:
        cmd_setting(rest[0], SETTINGS[second], parse_switch(rest[2]), use_server)
    elif len(rest) == 3:
        args.target, args.kind, args.action = rest[0], second, rest[2].lower()
        arcomlib.build_action(args.kind, args.action, args.groups)  # valide avant d'envoyer
        cmd_action(args, use_server)
    else:
        return False
    return True


if __name__ == "__main__":
    main()
