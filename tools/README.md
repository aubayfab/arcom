# Outils d'étude du protocole

Petits scripts autonomes qui ont servi à établir le [protocole](../docs/protocole.md), gardés
pour aller plus loin (identifier d'autres points de donnée, d'autres modèles de modules…).
Seule dépendance : [bleak](https://github.com/hbldh/bleak) (`pip install bleak`).

| Script | Ce qu'il fait | Écrit sur le module ? |
|---|---|---|
| `scan.py [secondes]` | Écoute les annonces BLE et enregistre tout ce qui passe dans `scan_<date>.json` | non |
| `introspect.py <MAC>` | Affiche la table GATT complète et lit tout ce qui est lisible | non |
| `monitor.py <MAC> [secondes] [étiquette]` | S'abonne aux notifications, relit les points de donnée, enregistre un instantané au début et à la fin (`snapshot_<étiquette>.json`) | non |
| `probe.py <MAC> [--pad]` | Change le décalage de consigne, vérifie qu'il est relu sur `…c69`, puis le rétablit | **oui** (réversible) |
| `send.py <MAC> <hex>… [--pad] [--delay 2.0]` | Envoie des trames brutes sur `…c67` | **oui** |

`--pad` ajoute le PIN par défaut (`00 00 00 00`) à la trame : sans lui, le module ignore la commande.

Avant de s'en servir :

- **Uniquement sur les modules de sa propre zone**, et jamais de trames au hasard (voir le
  [cadre juridique](../docs/cadre-juridique.md)).
- Les fichiers produits (`scan_*.json`, `snapshot_*.json`) contiennent des adresses réelles, et
  pour `scan.py` celles des appareils voisins (téléphones, montres…) : ils sont ignorés par Git,
  ne pas les publier.
- Fermer l'interface ou arrêter `server.py` : un module n'accepte qu'une liaison à la fois.
