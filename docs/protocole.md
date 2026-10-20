# Le protocole des modules Arcom

Ce que l'on sait du dialogue Bluetooth LE avec les modules Arcom (capteurs multifonctions et
régulateurs de zone : éclairage, stores, CVC), établi pour faire fonctionner ce logiciel avec eux et
vérifié sur les modules eux-mêmes (table GATT relue, état relu après chaque commande).

Implémentations de référence : [`arcomlib.py`](../arcomlib.py) (Python) et
[`Protocol.kt`](../android/app/src/main/java/local/telecommande/arcom/Protocol.kt) (Android), toutes
deux couvertes par des tests ([`tests/`](../tests), [`ProtocolTest.kt`](../android/app/src/test/java/local/telecommande/arcom/ProtocolTest.kt)).

## Découverte

- Les modules s'annoncent sous le nom `ARC_xxxx` (`ARC_1302`…) et/ou avec le service de commande.
- Un module n'accepte **qu'une liaison à la fois**, et un module connecté **n'émet plus d'annonces** :
  pour le retrouver, il faut avoir gardé son adresse MAC (d'où le registre `modules.json`).

## Services et caractéristiques GATT

Base d'UUID : `854dbb8e-f11e-11e5-9ce9-5e5517507cXX` (seul le dernier octet `XX` change).

| Rôle | UUID (`…cXX`) |
|------|---------------|
| Service de commande | `…c66` |
| **Écriture d'une commande** | `…c67` (write) |
| Service / lecture de l'état CVC | `…c68` / `…c69` (read, notify) |
| Version logicielle | `…c6f` |
| Disponibilité du PIN | `…c7d` (`01` = pas de saisie de PIN) |
| Passerelle DALI (lecture / écriture) | `…c6d` / `…c6b` |
| Passerelle BLE / code de maintenance | `…c75` / `…c79` |
| Points de donnée (non utilisés par l'appli d'origine) | service `…c86`, caractéristiques `…c87`, `…c88`, `…c89`, `…cae`, `…caf` |

## Trame de commande (sur `…c67`)

```
[ 1 octet d'action ] [ PIN sur 4 octets ]
```

- **PIN** : code à 4 chiffres, un octet par chiffre. `"0000"` → `00 00 00 00` ; `"1234"` → `01 02 03 04`.
  **Indispensable** : sans ce suffixe, le module acquitte la trame au niveau BLE mais **ne l'exécute pas**.
- **Octet d'action** = `(nibble haut = action) | (nibble bas = masque de groupes)`.
  Masque : bit0 = G1, bit1 = G2, bit2 = G3, bit3 = G4 ; `F` = tous les groupes.

| Action | Nibble haut | Exemple « tous groupes », PIN 0000 |
|--------|:-----------:|------------------------------------|
| Lumière éteinte | `0x00` | `0F 00000000` |
| Lumière allumée | `0x10` | `1F 00000000` |
| Lumière + (début de variation) | `0x20` | `2F 00000000` |
| Lumière − (début de variation) | `0x30` | `3F 00000000` |
| Lumière, fin de variation | `0x40` | `4F 00000000` |
| Store, montée | `0x50` | `5F 00000000` |
| Store, descente | `0x60` | `6F 00000000` |
| Store, arrêt | `0x70` | `7F 00000000` |
| Lames : orientation +, −, arrêt | `0x80` / `0x90` / `0xA0` | `8F 00000000` |
| Ventilation 0..4 (4 = auto) | `0xB0` \| v | `B4 00000000` |
| Occupation non / oui | `0xC0` \| (0/1) | `C1 00000000` |
| Décalage de consigne 0..12 (6 = neutre) | `0xD0` \| t | `D6 00000000` |

Pour les commandes CVC (ventilation, occupation, consigne), le nibble bas porte la valeur et non
des groupes : elles valent pour toute la zone du module.

Les variations (lumière ±, orientation des lames) durent tant que la commande « fin » n'est pas
envoyée : c'est ainsi que l'appli d'origine gérait l'appui maintenu.

## État lisible (sur `…c69`)

6 octets : `[occupation][ventilation][décalage de consigne][alarme fenêtre][alarme][comptage]`.
Exemple : `01 04 06 00 00 00` = occupé, ventilation auto, consigne neutre.

Les commandes CVC s'y reflètent en ~1,5 s : pratique pour vérifier qu'un module exécute bien les
trames sans toucher à une charge visible (voir [`tools/probe.py`](../tools/probe.py)).
L'état des lumières et des stores, lui, n'est pas lisible ici.

## Points de donnée (service `…c86`)

Enregistrements de 5 octets `[id sur 2 octets, petit-boutiste][valeur][type sur 2 octets]`, lus et
notifiés ; un id nul marque un emplacement vide. Seul `0x00b4` est identifié : il suit l'éclairage
(35 allumé, 45 éteint), avec 3,3 à 3,6 s de retard sur la trame.

## Comportements mesurés

- **Écriture sans accusé (Write Command)** : la caractéristique ne l'annonce pas, mais le module
  l'exécute (vérifié sur le décalage de consigne, relu sur `…c69`). Sur une liaison tenue, on gagne
  ~2 intervalles de connexion. Avant de libérer le module juste après, garder l'accusé : sinon la
  déconnexion peut partir avant la trame.
- **Intervalle de connexion** : le module réclame 150–300 ms (caractéristique `2A04`). Les profils
  plus rapides (15 ms, 30–60 ms) sont acceptés puis le module **raccroche au bout de 30 à 40 s**.
  Sous Windows 11, le profil « PowerOptimized » (90–180 ms) recoupe sa plage : liaison stable à 180 ms.
- **Lumières : ~3,5 s en aval de la liaison.** Le point `0x00b4` change 3,3 à 3,6 s après la
  trame, dans les deux sens, même interrogé toutes les 150 ms : le délai se situe entre le module et
  l'éclairage (bus LonWorks → régulateur → DALI, rampe éventuelle des ballasts), pas en Bluetooth.
- **Connexion** : 3,5 à 5,5 s, le temps que le module émette une annonce.
- **Stores** : inverser le sens en pleine course sans arrêt préalable n'est pas souhaitable ; nos
  clients envoient l'arrêt, attendent 0,5 s, puis le sens opposé.
- **DALI** : l'appli d'origine n'utilise `…c6b` qu'en maintenance (adressage des ballasts) ; le
  pilotage courant passe toujours par les groupes, sur `…c67`.

## Sécurité

La seule protection est le PIN du module (`0000` par défaut). Tout appareil Bluetooth à portée qui
connaît le PIN peut piloter la zone : c'est le fonctionnement prévu par le fabricant, ce logiciel ne
le contourne pas et n'ajoute aucune possibilité. Voir [SECURITY.md](../SECURITY.md).
