"""Télécommande pour modules Arcom — lanceur de l'application installée.

Double-clic : démarre le serveur local (s'il ne tourne pas déjà) et ouvre l'interface dans le
navigateur. Une icône près de l'horloge permet de rouvrir l'interface, voir le journal ou quitter.

    ArcomTelecommande.exe               lance et ouvre l'interface
    ArcomTelecommande.exe --background  lance sans ouvrir le navigateur (démarrage de Windows)
    … --raccourcis    crée les raccourcis (Bureau, menu Démarrer, démarrage de Windows en option)
    … --arreter       arrête proprement l'instance en cours
    … --desinstaller  arrête, supprime raccourcis et données (version zip)

Dans la version zip, « ArcomTelecommande.exe » est remplacé par python\\pythonw.exe app\\arcom_app.py.

Données et journal : %LOCALAPPDATA%\\Arcom (voir arcomlib.data_dir).
"""
from __future__ import annotations

import asyncio
import ctypes
import http.client
import json
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Données de l'appli de l'utilisateur final dans %LOCALAPPDATA%\Arcom, quel que soit le mode de
# distribution (installateur ou zip) ; à fixer avant d'importer arcomlib, qui en dérive ses chemins.
os.environ.setdefault("ARCOM_DATA", str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Arcom"))

import arcomlib  # noqa: E402
import server  # noqa: E402

APP_NAME = "Télécommande pour modules Arcom"
PORT = int(os.environ.get("ARCOM_PORT", 8787))
URL = f"http://127.0.0.1:{PORT}/"
# Icône : dans l'archive PyInstaller, sinon dans packaging/ à côté de ce fichier (sources, zip portable).
RESOURCES = Path(getattr(sys, "_MEIPASS", Path(__file__).parent / "packaging"))
DATA = arcomlib.data_dir()
LOG_PATH = DATA / "arcom.log"
FIRST_RUN_FLAG = DATA / ".deja-lance"

log = logging.getLogger("arcom")


def message_box(text: str, error: bool = True):
    icon = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
    ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, icon | 0x10000)  # MB_SETFOREGROUND


def ask(text: str) -> bool:
    return ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x4 | 0x20 | 0x10000) == 6  # Oui/Non → IDYES


# --- Raccourcis, arrêt, désinstallation (utilisés par les .bat de la version zip) -------------

SHORTCUT = f"{APP_NAME}.lnk"
OLD_SHORTCUTS = ["Télécommande Arcom.lnk"]  # nom jusqu'à la 1.2.0 : remplacé à la création des raccourcis
FOLDERS = {  # FOLDERID Windows : suit les redirections (Bureau OneDrive, etc.)
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "programs": "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}",
    "startup": "{B97D20BB-F46A-4C97-BA10-5E3608430854}",
}


def known_folder(name: str) -> Path:
    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort),
                    ("d4", ctypes.c_ubyte * 8)]

    guid, path = GUID(), ctypes.c_wchar_p()
    ctypes.oledll.ole32.CLSIDFromString(FOLDERS[name], ctypes.byref(guid))
    ctypes.oledll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path))
    try:
        return Path(path.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path)


def launch_command() -> tuple[str, str, str]:
    """(cible, arguments, icône) pour relancer l'appli, en version installée comme en version zip."""
    if getattr(sys, "frozen", False):
        return sys.executable, "", sys.executable
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return str(pythonw), f'"{Path(__file__).resolve()}"', str(RESOURCES / "arcom.ico")


def write_shortcuts(links: list[tuple[Path, str]]):
    """Écrit des .lnk [(chemin, arguments)] qui relancent l'appli, via l'objet COM WScript.Shell.

    Les valeurs passent par l'environnement : aucun souci de guillemets ou d'accents dans les chemins
    (« | » et « ? » sont interdits dans les chemins Windows, d'où leur usage comme séparateurs).
    """
    target, _, icon = launch_command()
    script = ("$sh = New-Object -ComObject WScript.Shell; "
              "foreach ($l in ($env:ARCOM_LNK -split '\\|')) { $p, $a = $l -split '\\?', 2; "
              "$s = $sh.CreateShortcut($p); $s.TargetPath = $env:ARCOM_TARGET; $s.Arguments = $a; "
              "$s.WorkingDirectory = $env:ARCOM_WORKDIR; $s.IconLocation = $env:ARCOM_ICON; "
              "$s.Description = 'Pilotage des lumières et stores Arcom'; $s.Save() }")
    env = {**os.environ, "ARCOM_LNK": "|".join(f"{p}?{a}" for p, a in links), "ARCOM_TARGET": target,
           "ARCOM_WORKDIR": str(Path(target).parent), "ARCOM_ICON": icon}
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                   env=env, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    log.info("Raccourcis créés : %s", ", ".join(str(p) for p, _ in links))


def remove_shortcuts(names: list[str]):
    for folder in FOLDERS:
        for name in names:
            try:
                (known_folder(folder) / name).unlink(missing_ok=True)
            except OSError:
                log.warning("Raccourci non supprimé (%s, %s)", folder, name, exc_info=True)


def create_shortcuts():
    _, args, _ = launch_command()
    links = [(known_folder("desktop") / SHORTCUT, args), (known_folder("programs") / SHORTCUT, args)]
    startup = ask("Les raccourcis vont être créés sur le Bureau et dans le menu Démarrer.\n\n"
                  "Lancer aussi la télécommande au démarrage de Windows ?")
    if startup:
        links.append((known_folder("startup") / SHORTCUT, f"{args} --background".strip()))
    remove_shortcuts(OLD_SHORTCUTS)
    write_shortcuts(links)
    message_box(f"Raccourcis « {APP_NAME} » créés." +
                ("\nLa télécommande se lancera au démarrage de Windows." if startup else ""), error=False)


def stop_running(wait_s: float = 8.0) -> bool:
    """Demande l'arrêt propre de l'instance en cours ; True si elle tournait."""
    if running_instance() != "arcom":
        return False
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    try:
        conn.request("POST", "/api/shutdown", body="{}", headers={"Content-Type": "application/json"})
        conn.getresponse().read()
    finally:
        conn.close()
    deadline = time.monotonic() + wait_s
    while running_instance() is not None and time.monotonic() < deadline:
        time.sleep(0.3)
    return True


def uninstall():
    if not ask("Désinstaller la télécommande ?\n\nSes raccourcis et ses données (liste des modules, "
               "noms donnés, journal) seront supprimés."):
        return
    stop_running()
    remove_shortcuts([SHORTCUT, *OLD_SHORTCUTS])
    logging.shutdown()  # libère le journal avant de le supprimer
    for f in [DATA / "modules.json", FIRST_RUN_FLAG, *DATA.glob("arcom.log*")]:
        f.unlink(missing_ok=True)
    try:
        DATA.rmdir()  # seulement s'il est vide : on ne supprime que nos fichiers
    except OSError:
        pass
    folder = Path(__file__).resolve().parent.parent
    portable = (folder / "Lancer la telecommande.bat").exists()  # version zip : reste à supprimer le dossier
    message_box("Désinstallation terminée." +
                (f"\n\nVous pouvez maintenant supprimer ce dossier :\n{folder}" if portable else ""), error=False)


def setup_logging():
    DATA.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    for noisy in ("aiohttp.access", "bleak", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    sys.excepthook = lambda *exc: log.critical("Erreur non gérée", exc_info=exc)


def running_instance() -> str | None:
    """None si le port est libre, 'arcom' si notre serveur y répond déjà, 'other' s'il est pris par autre chose.

    La disponibilité se teste en réservant le port : sous Windows, une connexion vers un port
    local fermé n'est refusée qu'au bout de ~2 s, trop lent et trompeur avec un délai court.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", PORT))
        return None
    except OSError:
        pass
    finally:
        probe.close()
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    try:
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        ok = resp.status == 200 and json.loads(resp.read() or b"{}").get("ok") is True
        return "arcom" if ok else "other"
    except Exception:
        return "other"
    finally:
        conn.close()


def check_runtime() -> str | None:
    """Vérifie que les modules Bluetooth de Windows se chargent ; renvoie un message pour l'utilisateur sinon.

    Cas typique en version zip : dossier extrait trop profondément, Windows refuse alors de charger
    les bibliothèques dont le chemin dépasse 260 caractères.
    """
    try:
        import bleak.backends.winrt.client  # noqa: F401
        import bleak.backends.winrt.scanner  # noqa: F401
    except (ImportError, OSError) as e:
        log.exception("Modules Bluetooth de Windows indisponibles")
        folder = Path(__file__).resolve().parent.parent
        if "long" in str(e).lower():  # « Nom de fichier ou extension trop long » / « … too long »
            return ("Le dossier de la télécommande est rangé trop profondément : Windows refuse de charger "
                    "certains de ses fichiers (chemin trop long).\n\nDéplacez ce dossier plus près de la "
                    f"racine, par exemple dans Documents, puis relancez.\n\nEmplacement actuel :\n{folder}")
        return f"Les modules Bluetooth de Windows ne se chargent pas :\n{e}\n\nJournal : {LOG_PATH}"
    return None


def make_tray(request_stop, first_run: bool):
    import pystray
    from PIL import Image

    def open_ui(icon, item):
        webbrowser.open(URL)

    def open_log(icon, item):
        if LOG_PATH.exists():
            os.startfile(LOG_PATH)

    def quit_app(icon, item):
        icon.stop()
        request_stop()

    def setup(icon):
        icon.visible = True
        if first_run:
            icon.notify("La télécommande tourne en arrière-plan. Retrouvez-la ici, près de l'horloge.", APP_NAME)

    menu = pystray.Menu(
        pystray.MenuItem("Ouvrir la télécommande", open_ui, default=True),
        pystray.MenuItem("Voir le journal", open_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quitter", quit_app),
    )
    icon = pystray.Icon("arcom", Image.open(RESOURCES / "arcom.ico"), APP_NAME, menu)
    threading.Thread(target=icon.run, kwargs={"setup": setup}, daemon=True, name="tray").start()
    return icon


def stop_command():
    print("Télécommande arrêtée." if stop_running() else "La télécommande ne tournait pas.")


COMMANDS = {"--raccourcis": create_shortcuts, "--arreter": stop_command, "--desinstaller": uninstall}


def main():
    setup_logging()
    for flag, command in COMMANDS.items():
        if flag in sys.argv:
            return command()
    open_browser = "--background" not in sys.argv and not os.environ.get("ARCOM_NO_BROWSER")

    state = running_instance()
    if state == "arcom":
        if open_browser:
            webbrowser.open(URL)
        return
    if state == "other":
        message_box(f"Le port {PORT} est déjà utilisé par un autre programme.\n\n"
                    "Fermez ce programme puis relancez la télécommande.")
        return

    error = check_runtime()
    if error:
        message_box(error)
        return
    run(open_browser)


def run(open_browser: bool):
    """Fait tourner le serveur jusqu'à « Quitter » (icône), --arreter ou la fermeture de session."""
    first_run = not FIRST_RUN_FLAG.exists()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop = asyncio.Event()
    tray = None

    def request_stop():
        loop.call_soon_threadsafe(stop.set)

    def on_ready():
        nonlocal tray
        tray = make_tray(request_stop, first_run)
        FIRST_RUN_FLAG.touch()
        if open_browser:
            webbrowser.open(URL)

    log.info("Démarrage de %s (%s)", APP_NAME, sys.executable)
    try:
        loop.run_until_complete(server.serve("127.0.0.1", PORT, stop, on_ready))
    except OSError as e:
        if running_instance() == "arcom":  # double-clic rapide : une autre instance a pris le port
            if open_browser:
                webbrowser.open(URL)
        else:
            log.exception("Démarrage impossible")
            message_box(f"Impossible de démarrer la télécommande :\n{e}")
    except Exception as e:
        log.exception("Erreur fatale")
        message_box(f"Erreur inattendue :\n{e}\n\nJournal : {LOG_PATH}")
    finally:
        if tray is not None:
            tray.stop()
        loop.close()
        log.info("Arrêt de %s", APP_NAME)


if __name__ == "__main__":
    main()
