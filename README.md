# Télécommande pour modules Arcom

[![CI](https://github.com/aubayfab/arcom/actions/workflows/ci.yml/badge.svg)](https://github.com/aubayfab/arcom/actions/workflows/ci.yml)
[![Licence MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

Pilotez l'éclairage, les stores et le confort (ventilation, consigne, présence) des modules
Bluetooth **Arcom** depuis un PC, un téléphone ou un terminal, sans l'application myArcom, qui
n'est plus disponible sur les versions récentes d'Android.

Tout est local : Bluetooth direct, sans Wi-Fi ni cloud.

> **Outil non officiel**, sans lien avec le Groupe Arcom, fabricant des modules. Il n'envoie que les mêmes
> commandes que l'application d'origine. À utiliser uniquement sur les modules que vous
> êtes autorisé à piloter (ceux de votre zone).

## Livrables

À télécharger dans les **[Releases](https://github.com/aubayfab/arcom/releases/latest)** :

| Livrable | Pour qui | Fichier |
|---|---|---|
| Installateur Windows | tout le monde, potentiellement bloqué par la sécurité du poste | `TelecommandeArcom-Setup-<version>.exe` |
| Version portable Windows | sans rien installer | `Arcom-portable-<version>.zip` |
| Appli Android, avec widgets | téléphone, sans PC | `TelecommandeArcom-<version>.apk` |
| Ligne de commande (Python) | bricoleurs, scripts | `telecommande_arcom-<version>-py3-none-any.whl`, ou les scripts du dépôt |

Configuration requise : Windows 10 1809 ou plus récent, 64 bits, avec Bluetooth LE (Windows 11
conseillé : liaison plus réactive) ; Android 8 ou plus récent ; Python 3.10+ pour la ligne de
commande.

## Installer

### Windows : installateur

1. Double-cliquer sur `TelecommandeArcom-Setup-<version>.exe`, puis Suivant, Installer. Options :
   icône sur le Bureau (cochée), lancement au démarrage de Windows (décochée).
2. La télécommande s'ouvre dans le navigateur. Une icône près de l'horloge permet de la rouvrir,
   de voir le journal ou de quitter.
3. Au premier lancement, les modules à proximité sont recherchés automatiquement : mettez le vôtre
   en favori avec ★ et donnez-lui un nom.

L'exécutable n'est pas signé : SmartScreen affiche « Windows a protégé votre ordinateur »
(« Informations complémentaires » › « Exécuter quand même »). Sur un poste d'entreprise,
l'antivirus peut le bloquer : voyez avec votre service informatique, sans chercher à le contourner.

Désinstallation : Paramètres Windows › Applications › Télécommande pour modules Arcom (supprime aussi les
données, dans `%LOCALAPPDATA%\Arcom`).

### Windows : version portable

1. Si le zip vient d'Internet ou d'un e-mail : clic droit › Propriétés › cocher « Débloquer ».
2. L'extraire dans un dossier peu profond (Documents, par exemple : Windows limite la longueur des
   chemins, la télécommande vous préviendra si besoin).
3. Double-cliquer sur `Lancer la telecommande.bat`. Le fichier `LISEZMOI.txt` décrit le reste
   (raccourcis, arrêt, désinstallation).

Rien de compilé par nos soins : le Python officiel de python.org (signé) et nos fichiers `.py`,
lisibles dans `app\`.

### Android

1. Copier l'APK sur le téléphone et l'ouvrir ; autoriser « Installer des applis inconnues » pour
   l'appli qui l'ouvre (Fichiers, navigateur…). Sur un téléphone géré par l'entreprise,
   l'installation peut être bloquée.
2. Au premier lancement, accepter « Appareils à proximité » (Android 12+), ou la localisation
   (Android 11 et avant, qui l'exige pour la recherche Bluetooth). La recherche démarre seule.
3. Mettre son module en favori avec ★ et le renommer (toucher son nom ; le PIN se règle au même
   endroit).

### Ligne de commande

Avec pip (installe aussi `bleak` et la commande `arcom`) :

```bash
pip install telecommande_arcom-<version>-py3-none-any.whl   # fichier téléchargé depuis la release
# ou directement depuis le dépôt
pip install git+https://github.com/aubayfab/arcom.git
```

Ou simplement avec les scripts, pour les lire et les modifier : récupérer le dépôt (ou le
« Source code (zip) » de la release), puis

```bash
pip install bleak
python arcom_cli.py list
```

Si la politique du poste bloque la commande `arcom`, `python -m arcom_cli` fait la même chose.
Installée avec pip, la ligne de commande partage la liste des modules de l'appli Windows
(`%LOCALAPPDATA%\Arcom`).

## Utiliser

### Connexion aux modules

Un module n'accepte qu'une liaison Bluetooth à la fois. Chaque module a donc deux réglages,
**désactivés par défaut** (interrupteurs en bas de chaque carte, sur PC comme sur Android ;
`keep` et `auto` en ligne de commande) :

| Réglage | Comportement |
|---|---|
| aucun (défaut) | Chaque commande se connecte (3,5 à 5,5 s), envoie la trame, puis **libère le module** pour les autres. Un appui maintenu (intensité − / +, orientation des lames) garde la liaison jusqu'au relâchement. |
| **Maintenir la connexion** | Une fois connecté, le module reste connecté pour enchaîner les commandes, et se reconnecte s'il décroche, **jusqu'à « Se déconnecter »**. |
| **Connexion auto** | Connecté automatiquement et en permanence : commandes immédiates. **Pas de déconnexion possible** tant qu'elle est active. |

Désactiver un réglage libère aussitôt le module (sauf si « Maintenir la connexion » reste actif :
la liaison en place est alors tenue jusqu'à « Se déconnecter »). L'étoile ★ ne fait que classer
les favoris en tête de liste.

Un module ne pilote que **sa** zone, et le plus proche en ondes radio n'est pas forcément celui de
votre pièce : renommer les cartes au fur et à mesure aide à s'y retrouver.

### Sur PC

- **Allumer / Éteindre** : gros boutons de chaque carte.
- **Intensité − / +** : maintenir le bouton fait varier, le relâcher arrête.
- **Stores** : un clic sur ▲ ou ▼ lance la course (bouton surligné), un second clic l'arrête ;
  ■ arrête aussi. **Appui long** sur ▲ / ▼ : orientation des lames tant qu'on maintient. Inverser en
  pleine course est sans risque : l'arrêt est envoyé d'abord.
- **Se connecter / Se déconnecter** : à côté de l'état, en mode « Maintenir la connexion ».
- **Nom** : cliquer sur le titre d'une carte pour la renommer. **Rechercher** : ajoute les modules
  à portée.
- Bluetooth coupé ou absent : un bandeau l'indique ; tout reprend seul une fois activé.

### Sur Android

Les mêmes commandes, plus un panneau **Confort** (ventilation, consigne, présence) qui affiche
l'état relu sur le module ; ces réglages valent pour toute la zone.

- **Connexion auto** : la liaison tient appli fermée et après un redémarrage du téléphone ; Android
  l'impose, une notification discrète « Connexion aux modules » le signale. Hors de portée, le
  téléphone guette le module et s'y reconnecte dès son retour.
- **Maintenir la connexion** : la liaison tient appli fermée, jusqu'à « Se déconnecter » sur la
  carte, ou « Tout déconnecter » dans la notification.
- Les modules du téléphone sont indépendants de ceux du PC.

**Widgets** : appui long sur l'écran d'accueil › Widgets › Télécommande pour modules Arcom.

| Widget | Taille | Boutons |
|---|---|---|
| Arcom – télécommande | 4×2 | Allumer, Éteindre, − +, ▲ ■ ▼ |
| Arcom – lumière | 2×1 | allumer, éteindre |
| Arcom – stores | 2×1 | ▲ ■ ▼ |

À l'ajout, choisir le module et, si besoin, les groupes (tous par défaut) ; pour changer : appui
long sur le widget › Paramètres. En haut à droite s'affiche le dernier résultat (« ✓ 14:02 »,
« Connexion… », « ✗ module injoignable »). − et + font une variation de 0,7 s (un widget ne sait
pas qu'on maintient un bouton) ; l'orientation des lames reste dans l'appli.

### En ligne de commande

```bash
arcom list                       # modules connus et leur mode de connexion (★ = favori)
arcom scan                       # rechercher les modules à portée
arcom ARC_1302 light off         # par nom, libellé ou adresse MAC
arcom "Mon bureau" light on
arcom ARC_1302 light up          # début de variation (envoyer « light stop » ensuite)
arcom ARC_1302 blind down        # up | down | stop | rot_up | rot_down | rot_stop
arcom ARC_1302 vent 4            # ventilation 0..4 (4 = auto)
arcom ARC_1302 temp 6            # décalage de consigne 0..12 (6 = neutre)
arcom ARC_1302 occ on            # occupation
arcom ARC_1302 keep on           # « Maintenir la connexion » (alias : maintien)
arcom ARC_1302 auto on           # « Connexion auto »
arcom ARC_1302 connect           # se connecter / se déconnecter
arcom ARC_1302 disconnect
arcom ARC_1302                   # mode interactif (mêmes commandes)

# Options
--groups 13    # ne piloter que les groupes 1 et 3 (défaut : tous)
--pin 1234     # PIN du module s'il n'est pas celui par défaut (0000)
--direct       # connexion Bluetooth directe, sans l'appli Windows (qui ne doit pas tenir le module)
--version
```

(Avec les scripts : `python arcom_cli.py …` au lieu de `arcom …`.)

Si la télécommande Windows tourne, la commande passe par elle et suit les réglages du module :
immédiate si le module est déjà connecté. Sinon, elle se connecte elle-même (~1,5 s si Windows a
gardé la liaison en cache, 4 à 5 s sinon), puis libère le module.

## Pour aller plus loin

- [Le protocole](docs/protocole.md) : services GATT, trames, état lisible, mesures.
- [Architecture](docs/architecture.md) : serveur local, API, sécurité, latence.
- [Compiler et publier](docs/compilation.md) les livrables.
- [Outils d'étude du protocole](tools/README.md).
- [Cadre juridique et règles du projet](docs/cadre-juridique.md).

## Contribuer

Les contributions sont bienvenues : voir [CONTRIBUTING.md](CONTRIBUTING.md) et le
[code de conduite](CODE_OF_CONDUCT.md). Problème de sécurité : [SECURITY.md](SECURITY.md).
Historique des versions : [CHANGELOG.md](CHANGELOG.md).

## Licence

[MIT](LICENSE). Les livrables embarquent des composants tiers sous leur propre licence :
[LICENCES-TIERCES.md](LICENCES-TIERCES.md). « Arcom » et « myArcom » sont cités uniquement pour
désigner les modules compatibles.
