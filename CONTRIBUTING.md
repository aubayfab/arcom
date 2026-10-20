# Contribuer

Merci de votre intérêt ! Corrections, idées, nouveaux modules pris en charge, traductions :
tout est bienvenu. Le projet est rédigé en français (code commenté, documentation, interface,
messages de commit).

## Avant tout : les règles du projet

Ce logiciel dialogue avec du matériel d'un fabricant tiers. Quelques règles sont donc
**impératives** (détails et raisons dans le [cadre juridique](docs/cadre-juridique.md)) :

1. aucun code ni aucune ressource issus de l'application myArcom ou d'un logiciel du fabricant,
   même retouchés, et pas de sources décompilées dans le dépôt, les issues ou les pull requests ;
2. aucune donnée réelle : adresses MAC, noms de bureaux, captures de scan ; utiliser des valeurs
   fictives (`AA:BB:CC:DD:EE:01`) ;
3. aucun secret (clé de signature Android, mots de passe) ;
4. pas de contournement de sécurité ni d'envoi de trames au hasard sur des modules en service.

## Organisation

```
arcomlib.py          protocole, registre des modules, connexion BLE (partagé)
arcom_cli.py         ligne de commande
server.py            serveur local : liaisons BLE, API REST + WebSocket
arcom_app.py         lanceur de l'appli Windows (icône près de l'horloge)
web/                 interface (Vite + TypeScript)
android/             appli Android (Kotlin) et ses tests
packaging/           icône, installateur Inno Setup, licences tierces
tools/               outils d'étude du protocole
tests/               tests Python
docs/                protocole, architecture, compilation, cadre juridique
build.ps1, package.ps1, build-apk.ps1   compilation des livrables
```

Plus de détails : [architecture](docs/architecture.md) et [protocole](docs/protocole.md).

## Environnement de développement

Windows 10 ou 11 avec Bluetooth LE pour essayer sur de vrais modules (les tests, eux, s'en
passent), [Python 3.13](https://www.python.org/downloads/), [Node 22](https://nodejs.org/) ;
pour l'appli Android, un JDK 17+ et le SDK Android (voir [compilation](docs/compilation.md)).

```powershell
git clone https://github.com/aubayfab/arcom.git
cd arcom
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt
npm ci --prefix web
```

## Lancer

```powershell
cd web; npm start                       # interface sur http://127.0.0.1:5173, lance server.py
.venv\Scripts\python arcom_cli.py list  # ligne de commande
```

Vite lance `server.py` (sauf s'il tourne déjà) et le relance s'il s'arrête. Sans Vite :
`npm run build` dans `web`, puis `.venv\Scripts\python server.py` sert l'interface compilée sur
http://127.0.0.1:8787.

En développement, la liste des modules est enregistrée dans `modules.json` à la racine du dépôt
(ignoré par Git) ; `ARCOM_DATA` permet de la mettre ailleurs.

Essayer sans gêner personne : l'état CVC (`…c69`) se relit, ce qui permet de vérifier qu'un module
exécute une commande sans toucher à une charge visible (voir `tools/probe.py`). Uniquement sur les
modules de sa zone.

## Vérifier avant de proposer

Ce que lance l'intégration continue :

```powershell
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m pytest
npm run typecheck --prefix web
npm run build --prefix web
cd android; .\gradlew.bat testDebugUnitTest   # derrière un proxy d'entreprise : voir docs/compilation.md
```

## Conventions

- **Commentaires** : expliquer le *pourquoi* (mesure, contrainte du module, piège de Windows), pas
  le *quoi*. Les mesures qui justifient un choix sont précieuses : les garder.
- **Protocole** : `arcomlib.py`, `Protocol.kt`, [docs/protocole.md](docs/protocole.md) et leurs
  tests vont ensemble ; toute découverte les met à jour tous.
- **Python** : `ruff` (règles dans `pyproject.toml`), lignes de 120 caractères au plus.
  `arcomlib` n'importe `bleak` et `asyncio` qu'à l'usage, pour que la CLI démarre vite.
- **Réseau** : toujours `127.0.0.1`, jamais `localhost` (sous Windows, ~2 s perdues en IPv6).
- **PowerShell** : compatible Windows PowerShell 5.1, fichiers en UTF-8 **avec BOM** (sinon les
  accents sont abîmés) ; voir `.editorconfig`.
- **Interface** : TypeScript strict, sans bibliothèque ; elle doit rester utilisable au doigt.

## Proposer une modification

1. Créer une branche depuis `main` (`fix/…`, `feat/…`, `docs/…`).
2. Des commits courts, au présent : « Corrige la reconnexion après mise en veille ».
3. Mettre à jour la documentation et la section « Non publié » du [CHANGELOG](CHANGELOG.md).
4. Ouvrir une pull request : décrire ce qui a été essayé, et sur quoi (modèle de module, version de
   Windows ou d'Android). La CI doit passer.

Bug ou idée : ouvrir une [issue](https://github.com/aubayfab/arcom/issues/new/choose).
Faille de sécurité : pas d'issue, voir [SECURITY.md](SECURITY.md).

## Publier une version

Réservé aux mainteneurs : voir [docs/compilation.md](docs/compilation.md#publier-une-version).
