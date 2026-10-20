"""Serveur local Arcom : tient les connexions BLE des modules pour l'interface et la CLI.

    API REST + WebSocket sur http://127.0.0.1:8787/api/…  (utilisée par web/ et par arcom_cli.py)
    Sert aussi l'interface compilée (web/dist) si elle existe : http://127.0.0.1:8787/

Deux réglages par module (modules.json), désactivés par défaut :
- Aucun : chaque commande se connecte, envoie la trame, puis libère le module. Un appui maintenu
  (intensité, lames) garde la liaison jusqu'à son « stop ». Un module n'accepte qu'une liaison à
  la fois : il reste ainsi libre pour les autres (téléphone, collègues).
- « Maintenir la connexion » (keep_connected) : une fois connecté (« Se connecter » ou première
  commande), le module reste tenu, et reconnecté s'il décroche, jusqu'à « Se déconnecter ».
- « Connexion auto » (auto_connect) : connecté en permanence, dès le démarrage ; pas de déconnexion.
Keep-alive des liaisons tenues : relecture de l'état (…c69) toutes les 10 s, comme l'app d'origine.
Stores : une inversion de sens en pleine course envoie d'abord STOP puis attend 0,5 s
(l'app d'origine l'imposait en désactivant le bouton opposé pendant la course).

Usage : python server.py [--host 127.0.0.1] [--port 8787]   (port aussi via ARCOM_PORT)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

import arcomlib

KEEPALIVE_S = 10
RECONNECT_MAX_S = 60
WRITE_TIMEOUT_S = 3
READ_TIMEOUT_S = 5
HVAC_REFLECT_S = 1.5        # délai avant que …c69 reflète une commande CVC (aller-retour régulateur)
BLIND_REVERSE_PAUSE_S = 0.5  # temps mort moteur entre STOP et le sens opposé
BLIND_MOTION_TTL_S = 120     # au-delà, le store est supposé arrivé en butée
HOLD_MAX_S = 30              # appui maintenu dont le « stop » n'arrive pas (page fermée) : abandonné
# Interface compilée : à côté du script en développement, dans l'archive pour l'appli installée.
DIST = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "web" / "dist"

log = logging.getLogger("arcom")


class Link:
    """Connexion à un module, ouverte et libérée selon ses réglages."""

    def __init__(self, mgr: Manager, mac: str):
        self.mgr = mgr
        self.mac = mac
        self.client = None
        self.status = "disconnected"  # disconnected | connecting | connected | error
        self.error: str | None = None
        self.state: dict | None = None
        self.points: dict[int, int] = {}
        self.last_ms: float | None = None
        self.retry_at = 0.0
        self.backoff = 2.0
        self.held = False    # « Maintenir la connexion » : tenue jusqu'à « Se déconnecter »
        self.pending = 0     # commandes en cours : le mode ponctuel ne libère qu'après la dernière
        self.gesture: float | None = None  # début d'un appui maintenu, en attente de son « stop »
        self.blind: dict[int, tuple[str, float]] = {}  # groupe -> (sens, début de course)
        # Les écritures sont ordonnées entre elles ; les lectures (keep-alive) ne les bloquent pas.
        self.write_lock = asyncio.Lock()
        self.read_lock = asyncio.Lock()
        self._connect_task: asyncio.Task | None = None
        self._link_profile = None  # requête d'intervalle de connexion, à garder tant que la liaison vit

    @property
    def connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    @property
    def name(self) -> str:
        m = self.mgr.registry.modules.get(self.mac, {})
        return m.get("label") or m.get("name") or self.mac

    @property
    def auto(self) -> bool:
        return bool(self.mgr.registry.modules.get(self.mac, {}).get("auto_connect"))

    @property
    def keep(self) -> bool:
        """Liaison gardée entre les commandes (« Maintenir la connexion », implicite en connexion auto)."""
        return self.auto or bool(self.mgr.registry.modules.get(self.mac, {}).get("keep_connected"))

    @property
    def wanted(self) -> bool:
        """Liaison à tenir, et à rétablir si elle tombe."""
        return self.auto or (self.keep and self.held)

    @property
    def busy(self) -> bool:
        return self.pending > 0 or self.gesture is not None

    def _set(self, status: str, error: str | None = None):
        self.status, self.error = status, error
        self.mgr.notify(self.mac)

    # --- Connexion -------------------------------------------------------------

    async def ensure(self):
        if self.connected:
            return self.client
        if self._connect_task is None or self._connect_task.done():
            self._connect_task = asyncio.create_task(self._connect())
        return await asyncio.shield(self._connect_task)

    async def _connect(self):
        self._set("connecting")
        t0 = time.perf_counter()
        try:
            client = await arcomlib.connect(self.mac, disconnected_callback=self._on_disconnect)
        except Exception as e:
            self.retry_at = time.monotonic() + self.backoff
            self.backoff = min(self.backoff * 2, RECONNECT_MAX_S)
            log.warning("%s : échec de connexion (%s)", self.name, e)
            self._set("error", str(e))
            raise
        self.client = client
        self._link_profile = arcomlib.request_link_profile(client)
        self.backoff = 2.0
        log.info("%s : connecté en %.2f s", self.name, time.perf_counter() - t0)
        self._set("connected")
        self.mgr.spawn(self.refresh())
        if self.keep:  # inutile pour une liaison libérée aussitôt la commande partie
            self.mgr.spawn(self._watch_points(client))
        self.mgr.spawn(self.release())  # réglage désactivé pendant la connexion : plus voulue
        return client

    def _release_link_profile(self):
        if self._link_profile is not None:
            try:
                self._link_profile.close()
            except Exception:
                pass
            self._link_profile = None

    def _on_disconnect(self, client):
        if client is self.client:
            self.client = None
            self._release_link_profile()
            log.info("%s : déconnecté", self.name)
            self._set("disconnected")

    async def drop(self):
        client, self.client = self.client, None
        self._release_link_profile()
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
        self._set("disconnected")

    async def release(self):
        """Libère le module s'il n'a pas à rester connecté et que rien n'est en cours."""
        if self.wanted or self.busy or not self.connected:
            return
        async with self.read_lock:  # après la relecture d'état lancée à la connexion
            if self.connected and not (self.wanted or self.busy):
                log.info("%s : libéré", self.name)
                await self.drop()

    def tick(self, now: float):
        """Entretien périodique : rétablit la liaison voulue, entretient la liaison tenue, libère les autres."""
        self.expire_blind()
        if self.gesture is not None and now - self.gesture > HOLD_MAX_S:
            self.gesture = None  # « stop » jamais reçu (page fermée en plein appui)
        if self.connected:
            self.mgr.spawn(self.refresh() if self.wanted else self.release())
        elif self.wanted and self.status != "connecting" and now >= self.retry_at:
            self.mgr.spawn(self.ensure())

    # --- Commandes ---------------------------------------------------------------

    def blind_state(self) -> str | None:
        """Sens de la course en cours (la plus récente), None si à l'arrêt ou supposé en butée."""
        now = time.monotonic()
        live = [(since, d) for d, since in self.blind.values() if now - since < BLIND_MOTION_TTL_S]
        return max(live)[1] if live else None

    def expire_blind(self):
        now = time.monotonic()
        expired = [g for g, (_, since) in self.blind.items() if now - since >= BLIND_MOTION_TTL_S]
        for g in expired:
            del self.blind[g]
        if expired:
            self.mgr.notify(self.mac)

    @staticmethod
    def _groups(groups) -> list[int]:
        mask = arcomlib.groups_mask(groups)
        return [g for g in range(1, 5) if mask & (1 << (g - 1))]

    def _frames(self, kind: str, action: str, groups, pin: str) -> list[tuple[bytes, float]]:
        """(trame, pause après) : inverser un store en pleine course envoie d'abord STOP, puis un temps mort."""
        data = arcomlib.frame(arcomlib.build_action(kind, action, groups), pin)  # valide la commande
        direction = arcomlib.blind_direction(action) if kind == "blind" else None
        if direction:
            now = time.monotonic()
            if any(self.blind[g][0] != direction and now - self.blind[g][1] < BLIND_MOTION_TTL_S
                   for g in self._groups(groups) if g in self.blind):
                stop = arcomlib.frame(arcomlib.build_action("blind", "stop", groups), pin)
                return [(stop, BLIND_REVERSE_PAUSE_S), (data, 0.0)]
        return [(data, 0.0)]

    async def _write(self, frames: list[tuple[bytes, float]]):
        """Écrit les trames dans l'ordre ; une liaison morte est rétablie une fois.

        Liaison tenue : Write Command (sans accusé), ~10 ms au lieu de ~2 intervalles de connexion.
        Liaison libérée juste après : avec accusé, sinon la déconnexion pourrait partir avant la trame.
        """
        async with self.write_lock:
            for attempt in (1, 2):
                client = await self.ensure()
                try:
                    for frame_bytes, pause in frames:
                        await asyncio.wait_for(
                            client.write_gatt_char(arcomlib.WRITE_COMMAND, frame_bytes, response=not self.keep),
                            WRITE_TIMEOUT_S)
                        if pause:
                            await asyncio.sleep(pause)
                    return
                except Exception:
                    await self.drop()
                    if attempt == 2:
                        raise

    def _track(self, kind: str, action: str, groups):
        """Course des stores en cours, appui maintenu en attente de son « stop »."""
        if kind == "blind":
            direction = arcomlib.blind_direction(action)
            for g in self._groups(groups):
                if direction:
                    self.blind[g] = (direction, time.monotonic())
                else:
                    self.blind.pop(g, None)
        if kind in ("light", "blind"):
            self.gesture = time.monotonic() if (kind, action) in arcomlib.HOLD_ACTIONS else None

    async def command(self, kind: str, action: str, groups, pin: str) -> dict:
        kind, action = kind.lower(), str(action).lower()
        frames = self._frames(kind, action, groups, pin)
        if self.keep:
            self.held = True
        t0 = time.perf_counter()
        self.pending += 1
        try:
            await self._write(frames)
        finally:
            self.pending -= 1
        ms = (time.perf_counter() - t0) * 1000

        self._track(kind, action, groups)
        self.last_ms = round(ms)
        self.mgr.notify(self.mac)
        self.mgr.spawn(self._settle(hvac=frames[-1][0][0] >= arcomlib.VENT))
        return {"frames": [f.hex() for f, _ in frames], "ms": ms}

    async def _settle(self, hvac: bool):
        """Après une commande : relit l'état CVC une fois répercuté, puis libère le module si besoin."""
        if hvac:
            self.pending += 1  # la liaison attend la relecture
            try:
                await self.refresh(delay=HVAC_REFLECT_S)
            finally:
                self.pending -= 1
        await self.release()

    # --- Lectures ------------------------------------------------------------------

    async def refresh(self, delay: float = 0.0):
        if delay:
            await asyncio.sleep(delay)
        client = self.client
        if client is None or not client.is_connected:
            return
        try:
            async with self.read_lock:
                raw = await asyncio.wait_for(client.read_gatt_char(arcomlib.READ_COMMAND), READ_TIMEOUT_S)
        except Exception as e:
            log.info("%s : lecture d'état impossible (%s), liaison abandonnée", self.name, e)
            await self.drop()
            return
        state = arcomlib.parse_state(raw)
        if state != self.state:
            self.state = state
            self.mgr.notify(self.mac)

    async def _watch_points(self, client):
        """Journalise les points de donnée du module (sert à repérer fins de course, retours d'état…)."""
        def on_change(_, data: bytearray):
            new = arcomlib.parse_points(bytes(data))
            changes = [(rid, self.points.get(rid), v) for rid, v in new.items() if self.points.get(rid) != v]
            self.points.update(new)
            if changes:
                log.info("%s : points %s", self.name,
                         ", ".join(f"0x{rid:04x} {old}→{v}" for rid, old, v in changes))

        try:
            for uuid in arcomlib.POINT_CHARS:
                if client.services.get_characteristic(uuid) is None:
                    continue
                async with self.read_lock:
                    raw = await asyncio.wait_for(client.read_gatt_char(uuid), READ_TIMEOUT_S)
                self.points.update(arcomlib.parse_points(bytes(raw)))
                await client.start_notify(uuid, on_change)
        except Exception as e:
            log.info("%s : points de donnée indisponibles (%s)", self.name, e)


class Manager:
    def __init__(self):
        self.registry = arcomlib.Registry()
        self.links: dict[str, Link] = {}
        self.sockets: set[web.WebSocketResponse] = set()
        self.scanning = False
        self.bluetooth = "unknown"  # on | off | absent | unknown
        self._scan_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    async def check_bluetooth(self):
        state = await arcomlib.bluetooth_state()
        if state == self.bluetooth:
            return
        previous, self.bluetooth = self.bluetooth, state
        log.info("Bluetooth : %s", state)
        self.broadcast({"type": "bluetooth", "state": state})
        if state == "on" and previous != "unknown" and not self.registry.modules:
            self.spawn(self.scan(8))

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(self._log_failure)
        return task

    @staticmethod
    def _log_failure(task: asyncio.Task):
        """Journalise les échecs des tâches de fond (les échecs de connexion le sont déjà par Link)."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None and not isinstance(exc, ConnectionError):
            log.warning("Tâche de fond en échec : %r", exc, exc_info=exc)

    def link(self, mac: str) -> Link:
        mac = mac.upper()
        if mac not in self.links:
            self.links[mac] = Link(self, mac)
        return self.links[mac]

    def resolve(self, key: str) -> dict:
        m = self.registry.get(key)
        if m is None:
            raise web.HTTPNotFound(text=f"Module inconnu : {key} (lance un scan)")
        return m

    def public(self, mac: str) -> dict:
        m = self.registry.modules[mac]
        link = self.links.get(mac)
        return {
            "mac": mac, "name": m.get("name"), "label": m.get("label") or "",
            "pinned": bool(m.get("pinned")), "rssi": m.get("rssi"), "last_seen": m.get("last_seen"),
            "auto_connect": bool(m.get("auto_connect")),
            "keep_connected": bool(m.get("keep_connected")),
            "held": link.held if link else False,
            "status": link.status if link else "disconnected",
            "error": link.error if link else None,
            "state": link.state if link else None,
            "last_ms": link.last_ms if link else None,
            "blind": link.blind_state() if link else None,
            "points": {f"0x{k:04x}": v for k, v in sorted(link.points.items())} if link else {},
        }

    def snapshot(self) -> list[dict]:
        return [self.public(mac) for mac in self.registry.modules]

    def notify(self, mac: str):
        if mac in self.registry.modules:
            self.broadcast({"type": "module", "module": self.public(mac)})

    def broadcast(self, payload: dict):
        for ws in self.sockets:
            self.spawn(self._send(ws, payload))

    async def _send(self, ws, payload):
        try:
            await ws.send_json(payload)
        except Exception:
            self.sockets.discard(ws)

    async def scan(self, duration: float) -> list[dict]:
        if self.bluetooth in ("off", "absent"):
            raise RuntimeError("Bluetooth désactivé : active-le dans les paramètres Windows."
                               if self.bluetooth == "off" else "Aucun adaptateur Bluetooth détecté.")
        async with self._scan_lock:
            self.scanning = True
            self.broadcast({"type": "scanning", "scanning": True})
            try:
                for f in await arcomlib.scan(duration):
                    self.registry.seen(f["mac"], f["name"], f["rssi"])
                self.registry.save()
            finally:
                self.scanning = False
                self.broadcast(self.snapshot_message())
            return self.snapshot()

    def snapshot_message(self) -> dict:
        return {"type": "snapshot", "modules": self.snapshot(), "scanning": self.scanning,
                "bluetooth": self.bluetooth}

    async def maintenance(self):
        """Toutes les 10 s : (re)connecte ce qui doit l'être, entretient les liaisons tenues, libère les autres."""
        while True:
            await self.check_bluetooth()
            if self.bluetooth in ("off", "absent"):  # inutile d'empiler des échecs de connexion
                await asyncio.sleep(KEEPALIVE_S)
                continue
            now = time.monotonic()
            for mac in self.registry.modules:
                self.link(mac).tick(now)
            await asyncio.sleep(KEEPALIVE_S)

    async def shutdown(self):
        await asyncio.gather(*(link.drop() for link in self.links.values() if link.connected),
                             return_exceptions=True)
        for ws in list(self.sockets):
            await ws.close()


# --- HTTP -------------------------------------------------------------------

LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}


@web.middleware
async def local_only(request, handler):
    """N'accepte que l'interface locale et la CLI.

    Sans cela, n'importe quel site ouvert dans le navigateur pourrait piloter les lumières en
    envoyant une requête à 127.0.0.1 (CSRF), ou via un nom de domaine qui pointe vers 127.0.0.1
    (DNS rebinding). Les navigateurs envoient toujours l'en-tête Origin sur ces requêtes.
    """
    if urlsplit(f"//{request.host}").hostname not in LOCAL_HOSTNAMES:
        raise web.HTTPForbidden(text="Hôte non autorisé")
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).hostname not in LOCAL_HOSTNAMES:
        raise web.HTTPForbidden(text="Origine non autorisée")
    if request.method in ("POST", "PATCH") and request.can_read_body and request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType(text="JSON attendu")
    return await handler(request)


routes = web.RouteTableDef()


def mgr_of(request) -> Manager:
    return request.app["mgr"]


@routes.get("/api/health")
async def health(request):
    return web.json_response({"ok": True, "app": "arcom", "bluetooth": mgr_of(request).bluetooth})


@routes.post("/api/shutdown")
async def shutdown(request):
    """Arrêt propre (déconnexion des modules), utilisé par « Arreter la telecommande.bat »."""
    log.info("Arrêt demandé")
    asyncio.get_running_loop().call_later(0.2, request.app["stop"].set)
    return web.json_response({"ok": True})


@routes.get("/api/modules")
async def list_modules(request):
    mgr = mgr_of(request)
    return web.json_response({"modules": mgr.snapshot(), "scanning": mgr.scanning})


@routes.get("/api/modules/{key}")
async def get_module(request):
    mgr = mgr_of(request)
    return web.json_response(mgr.public(mgr.resolve(request.match_info["key"])["mac"]))


@routes.post("/api/scan")
async def scan(request):
    body = await request.json() if request.can_read_body else {}
    try:
        modules = await mgr_of(request).scan(float(body.get("duration", 8)))
    except Exception as e:
        raise web.HTTPServiceUnavailable(text=str(e) or "Recherche Bluetooth impossible")
    return web.json_response({"modules": modules})


@routes.post("/api/modules/{key}/command")
async def command(request):
    mgr = mgr_of(request)
    m = mgr.resolve(request.match_info["key"])
    body = await request.json()
    link = mgr.link(m["mac"])
    t0 = time.perf_counter()
    try:
        result = await link.command(body["kind"], str(body["action"]), body.get("groups"),
                                    body.get("pin") or m.get("pin") or arcomlib.DEFAULT_PIN)
    except (KeyError, ValueError) as e:
        raise web.HTTPBadRequest(text=str(e))
    except Exception as e:
        raise web.HTTPBadGateway(text=f"{link.name} : {e}")
    total_ms = (time.perf_counter() - t0) * 1000
    log.info("%s : %s %s -> %s (%.0f ms)", link.name, body["kind"], body["action"],
             " puis ".join(result["frames"]), total_ms)
    return web.json_response({"ok": True, "frame": result["frames"][-1], "frames": result["frames"],
                              "write_ms": round(result["ms"]), "total_ms": round(total_ms)})


@routes.post("/api/modules/{key}/connect")
async def connect(request):
    """« Se connecter » : uniquement avec « Maintenir la connexion » (sinon chaque commande se connecte)."""
    mgr = mgr_of(request)
    m = mgr.resolve(request.match_info["key"])
    link = mgr.link(m["mac"])
    if not link.keep:
        raise web.HTTPConflict(text=f"{link.name} : activez « Maintenir la connexion » pour garder le module "
                                    "connecté (sinon, chaque commande se connecte puis le libère)")
    link.held = True
    try:
        await link.ensure()
    except Exception as e:
        raise web.HTTPBadGateway(text=str(e))
    return web.json_response(mgr.public(m["mac"]))


@routes.post("/api/modules/{key}/disconnect")
async def disconnect(request):
    """« Se déconnecter » : rend la main (refusé en connexion auto)."""
    mgr = mgr_of(request)
    m = mgr.resolve(request.match_info["key"])
    link = mgr.link(m["mac"])
    if link.auto:
        raise web.HTTPConflict(text=f"{link.name} : connexion auto active, désactivez-la pour déconnecter le module")
    link.held = False
    await link.drop()
    return web.json_response(mgr.public(m["mac"]))


def apply_link_settings(mgr: Manager, link: Link, was_auto: bool, was_keep: bool):
    """Après un changement de réglage : activer connecte tout de suite, désactiver libère le module."""
    if not link.keep:
        link.held = False
    elif (link.auto and not was_auto) or not was_keep:
        link.held = True
    else:  # connexion auto retirée, maintien gardé : la liaison en place reste tenue jusqu'à « Se déconnecter »
        link.held = link.connected or link.status == "connecting"
    mgr.spawn(link.ensure() if link.wanted else link.release())


@routes.patch("/api/modules/{key}")
async def update(request):
    """Nom affiché, favori (★, simple classement), connexion auto, maintien de la connexion."""
    mgr = mgr_of(request)
    m = mgr.resolve(request.match_info["key"])
    body = await request.json()
    fields = {}
    if "label" in body:
        fields["label"] = str(body["label"]).strip()[:60]
    for key in ("pinned", "auto_connect", "keep_connected"):
        if key in body:
            fields[key] = bool(body[key])
    link = mgr.link(m["mac"])
    was_auto, was_keep = link.auto, link.keep
    mgr.registry.update(m["mac"], **fields)
    mgr.registry.save()
    if (link.auto, link.keep) != (was_auto, was_keep):
        apply_link_settings(mgr, link, was_auto, was_keep)
    mgr.notify(m["mac"])
    return web.json_response(mgr.public(m["mac"]))


@routes.get("/api/ws")
async def websocket(request):
    mgr = mgr_of(request)
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    mgr.sockets.add(ws)
    await ws.send_json(mgr.snapshot_message())
    try:
        async for _ in ws:
            pass
    finally:
        mgr.sockets.discard(ws)
    return ws


@routes.get("/{tail:.*}")
async def static(request):
    """Interface compilée (npm run build). En dev, c'est Vite qui la sert."""
    index = DIST / "index.html"
    if not index.exists():
        return web.Response(text="Interface non compilée : lance « npm run dev » ou « npm run build » dans web/.",
                            content_type="text/plain")
    path = (DIST / request.match_info["tail"]).resolve()
    if path.is_file() and DIST.resolve() in path.parents:
        return web.FileResponse(path)
    return web.FileResponse(index)


async def on_startup(app):
    mgr: Manager = app["mgr"]
    await mgr.check_bluetooth()
    if not mgr.registry.modules and mgr.bluetooth == "on":
        log.info("Registre vide : scan initial…")
        mgr.spawn(mgr.scan(8))
    app["maintenance"] = asyncio.create_task(mgr.maintenance())


async def on_cleanup(app):
    app["maintenance"].cancel()
    await app["mgr"].shutdown()


def build_app(stop: asyncio.Event) -> web.Application:
    app = web.Application(middlewares=[local_only])
    app["mgr"] = Manager()
    app["stop"] = stop
    app.add_routes(routes)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


async def serve(host: str, port: int, stop: asyncio.Event | None = None, on_ready=None):
    """Sert jusqu'à ce que `stop` soit levé (ou POST /api/shutdown), puis libère les liaisons BLE.

    Lève OSError si le port est déjà pris.
    """
    stop = stop or asyncio.Event()
    runner = web.AppRunner(build_app(stop), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, host, port).start()
        log.info("Arcom : http://%s:%d (données : %s)", host, port, arcomlib.data_dir())
        if on_ready:
            on_ready()
        await stop.wait()
    finally:
        await runner.cleanup()


def main():
    p = argparse.ArgumentParser(description="Serveur local Arcom (BLE persistant + API).")
    p.add_argument("--host", default="127.0.0.1",
                   help="adresse d'écoute (défaut : 127.0.0.1, local uniquement)")
    p.add_argument("--port", type=int, default=int(os.environ.get("ARCOM_PORT", 8787)))
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    try:
        asyncio.run(serve(args.host, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
