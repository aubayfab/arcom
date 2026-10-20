# Architecture

```
navigateur ──HTTP/WebSocket──► Vite :5173 ──proxy /api──► server.py :8787 ──BLE──► modules ARC_xxxx
arcom_cli.py ──────────HTTP (si le serveur tourne)───────► server.py
arcom_cli.py ──────────BLE direct (sinon)─────────────────────────────────────────► modules
appli Android + widgets ──────BLE direct──────────────────────────────────────────► modules
```

En production, Vite disparaît : `server.py` sert lui-même l'interface compilée (`web/dist`) sur
http://127.0.0.1:8787, lancé par `arcom_app.py` (icône près de l'horloge).

## Fichiers

| Fichier | Rôle |
|---|---|
| [`arcomlib.py`](../arcomlib.py) | Protocole, registre `modules.json`, connexion BLE rapide. Partagé par la CLI et le serveur ; `bleak` et `asyncio` ne sont importés qu'à l'usage. |
| [`server.py`](../server.py) | Serveur local (aiohttp) : tient les liaisons BLE, API REST + WebSocket, sert l'interface compilée. |
| [`arcom_app.py`](../arcom_app.py) | Lanceur de l'appli Windows : serveur + icône de notification + navigateur ; raccourcis, arrêt, désinstallation. |
| [`arcom_cli.py`](../arcom_cli.py) | Ligne de commande : passe par le serveur s'il tourne, sinon connexion directe. |
| [`web/`](../web) | Interface Vite + TypeScript (`src/main.ts`, `src/style.css`, `index.html`). En dev, `vite.config.ts` lance et relance `server.py`. |
| [`android/`](../android) | Appli Android (Kotlin) : `Protocol.kt` (trames), `Link.kt` (liaison BLE), `Arcom.kt` (registre, entretien, scan), `LinkService.kt` (service de premier plan), `Widgets.kt`, `MainActivity.kt` / `ModuleCard.kt` (écran). |
| [`packaging/`](../packaging) | Icône, installateur Inno Setup, collecte des licences tierces. |
| [`tools/`](../tools) | Outils d'étude du protocole (scan brut, table GATT, notifications…). |

## Le serveur (`server.py`)

- Ouvre et libère les liaisons selon les réglages de chaque module (voir « Connexion aux modules »
  dans le [README](../README.md)).
- Relit l'état CVC des liaisons tenues toutes les 10 s (keep-alive, comme l'appli d'origine),
  reconnecte les modules en connexion auto (ou en maintien, tant que « Se déconnecter » n'a pas été
  demandé), et pousse chaque changement par WebSocket.
- Chaque opération BLE a un délai maximal (3 s en écriture, 5 s en lecture) : une liaison morte est
  abandonnée puis rétablie, au lieu de bloquer les commandes suivantes.
- Écritures et lectures ont des verrous séparés : le keep-alive ne retarde jamais une commande.
- Journalise les changements des points de donnée du module (`points 0x00b4 35→45`).
- Tant qu'il tient un module, un autre processus (dont `arcom_cli.py --direct`) ne parvient pas à
  s'y connecter (constaté sous Windows) : passer par le serveur.

### Sécurité

- N'écoute que sur `127.0.0.1`. `--host 0.0.0.0` l'ouvrirait à tout le réseau (de l'entreprise) :
  à éviter.
- Refuse les requêtes venues d'autres sites ouverts dans le navigateur : en-tête `Origin` étranger
  → 403, corps non JSON → 415, nom d'hôte autre que local → 403. Sans cela, une page web quelconque
  pourrait piloter les lumières via `127.0.0.1` (CSRF, DNS rebinding).

### API

| Méthode et chemin | Effet |
|---|---|
| `GET /api/modules` | Modules connus, avec leur état |
| `GET /api/modules/{nom\|mac}` | Un module |
| `POST /api/scan` | Recherche des modules à portée |
| `POST /api/modules/{nom\|mac}/command` | Commande : `{"kind": "light", "action": "off", "groups": [1, 3]}` |
| `PATCH /api/modules/{nom\|mac}` | Réglages : `{"label": "…", "pinned": true, "auto_connect": false, "keep_connected": true}` |
| `POST /api/modules/{nom\|mac}/connect` | Se connecter (409 sans « Maintenir la connexion ») |
| `POST /api/modules/{nom\|mac}/disconnect` | Se déconnecter (409 en connexion auto) |
| `GET /api/ws` | WebSocket des changements d'état |
| `GET /api/health` | Santé du serveur |
| `POST /api/shutdown` | Arrêt propre |

## Données

`modules.json` : registre partagé (MAC, nom, libellé, favori, PIN, `auto_connect`,
`keep_connected`). Emplacement (voir `arcomlib.data_dir`) :

| Contexte | Dossier |
|---|---|
| Variable `ARCOM_DATA` définie | ce dossier |
| Sources (développement) | la racine du dépôt (fichier ignoré par Git) |
| Appli Windows (installateur ou zip), CLI installée avec pip | `%LOCALAPPDATA%\Arcom` |
| Appli Android | données privées de l'appli (même format, registre indépendant) |

## Latence : ce qui a été optimisé

| Étape | Avant | Après |
|---|---|---|
| Trouver le module | scan fixe de 8 s | MAC lue dans `modules.json`, aucun scan |
| Connexion + découverte GATT | ~11 s (16 services, sans cache) | ~0,3 s (2 services, cache Windows) |
| Écriture, liaison ouverte | ~700 ms | **~10 ms** (trame reçue par le module en < 180 ms) |
| Commande depuis l'interface | — | ~35 ms d'aller-retour |
| Commande bloquée par la relecture d'état | jusqu'à ~400 ms | jamais (verrous séparés) |
| CLI via le serveur | — | Python démarre sans charger `bleak` ni `asyncio` |

Détails des mesures (écriture sans accusé, intervalle de connexion, retard des lumières) :
[protocole.md](protocole.md#comportements-mesurés).

Piège Windows : `localhost` tente d'abord l'IPv6 (`::1`) et perd ~2 s par requête quand le serveur
n'écoute qu'en IPv4. Tout le code vise donc `127.0.0.1`.

## L'appli Android : ce qui diffère du PC

- **Écriture avec accusé**, comme l'appli d'origine : la trame part au même événement de connexion
  qu'une écriture sans accusé, et une liaison morte est détectée au lieu d'avaler les commandes.
- **Aucun intervalle de connexion imposé** : le module négocie ses 150–300 ms ; un profil plus
  rapide le fait raccrocher.
- **Service de premier plan** (`connectedDevice`) : sans lui, Android gèle l'appli en arrière-plan
  et les liaisons tombent. Il ne tourne que tant qu'une liaison est ouverte ou qu'une commande de
  widget est en cours.
- **Widgets** : un widget ne peut pas savoir qu'on maintient un bouton ; − et + font une variation
  de 0,7 s (`Arcom.NUDGE_MS`) et l'orientation des lames reste dans l'appli.
