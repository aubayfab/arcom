# Historique des versions

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), numérotation
[SemVer](https://semver.org/lang/fr/). La section d'une version sert de notes à sa release GitHub.

## [Non publié]

## [1.2.0] - 2026-10-20

Première version publiée sur GitHub.

### Ajouté

- Ligne de commande installable avec pip (commande `arcom`, option `--version`). Installée ainsi,
  elle partage la liste des modules de l'appli Windows (`%LOCALAPPDATA%\Arcom`).
- Licences jointes aux livrables Windows : `LICENCE.txt` et `LICENCES-TIERCES.txt` (textes complets
  des composants embarqués).
- Documentation : protocole, architecture, compilation et publication, cadre juridique, guide de
  contribution, politique de sécurité.
- Tests automatisés du protocole et de la ligne de commande (Python), intégration continue (Python,
  interface web, appli Android) et publication automatique des releases.
- Fichier `VERSION` unique, lu par tous les scripts de compilation et par Gradle.

### Corrigé

- Ligne de commande : `list` échouait quand sa sortie était redirigée sous Windows (caractère ★).

### Modifié

- Outils d'étude du protocole rangés dans `tools/` ; l'adresse du module y est obligatoire.

## [1.1.0] - 2026-10-14

Diffusion interne (installateur Windows, version portable, appli Android).

### Modifié

- Connexion réglée module par module, avec deux interrupteurs désactivés par défaut :
  « Connexion auto » et « Maintenir la connexion ». Sans eux, chaque commande se connecte puis
  libère le module pour les autres appareils. L'étoile ★ ne fait plus que classer les favoris.
- « Se connecter » / « Se déconnecter » en mode maintien, sur PC, sur Android et en ligne de commande.
- Un appui maintenu (intensité, orientation des lames) garde la liaison jusqu'à son relâchement.

## [1.0.0] - 2026-10-07

Première version, diffusée en interne : interface locale et installateur Windows, version portable,
appli Android avec widgets, ligne de commande.

[Non publié]: https://github.com/aubayfab/arcom/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/aubayfab/arcom/releases/tag/v1.2.0
