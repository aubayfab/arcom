# Cadre juridique et règles du projet

Ce projet est un logiciel **indépendant**, écrit de zéro, qui dialogue avec les modules Bluetooth
du Groupe Arcom. Il ne contient aucun code, aucune ressource (image, texte, mise en page) ni aucun
élément graphique de l'application myArcom ou d'un autre logiciel du fabricant. Ce document
explique sur quoi il repose et les règles qui en découlent pour les contributions. Ce n'est pas un
avis juridique.

## Sur quoi repose le projet

- **Interopérabilité.** Le droit d'auteur sur les logiciels permet à qui a le droit d'utiliser un
  programme d'en observer, étudier et tester le fonctionnement pour en dégager les idées et
  principes, et, si c'est indispensable, d'en décompiler les parties nécessaires pour obtenir les
  informations permettant de faire fonctionner un logiciel créé indépendamment avec d'autres
  programmes ; une clause contractuelle contraire est nulle (article L. 122-6-1 du code de la
  propriété intellectuelle, articles 5 et 6 de la directive 2009/24/CE). C'est le cadre dans
  lequel le protocole a été établi, pour piloter les modules sans l'application d'origine, qui
  n'est plus disponible. Il a ensuite été vérifié par observation directe des modules (table GATT,
  état relu après chaque commande).
- **Un protocole n'est pas une œuvre.** Les fonctionnalités d'un programme, ses formats de données
  et son langage ne sont pas protégés par le droit d'auteur, seule l'expression du code l'est (CJUE,
  2 mai 2012, *SAS Institute*, C-406/10). Ce dépôt décrit des trames, des UUID et des valeurs, et
  les met en œuvre avec son propre code.
- **Marques.** « Arcom » et « myArcom » désignent les produits du Groupe Arcom. Ils ne sont cités
  que pour indiquer avec quels modules l'outil fonctionne. Le projet n'est ni affilié au Groupe
  Arcom, ni approuvé ou soutenu par lui.
- **Licences.** Le code est sous licence [MIT](../LICENSE). Les composants tiers embarqués dans les
  livrables gardent leur licence : voir [LICENCES-TIERCES.md](../LICENCES-TIERCES.md).

## Règles impératives pour contribuer

1. **Aucun code ni aucune ressource du fabricant**, même retouchés : pas de copie ni de traduction
   de code décompilé, pas d'image, d'icône, de texte ou de mise en page issus de l'APK. On écrit sa
   propre implémentation à partir du comportement observé.
2. **Pas de sources décompilées** dans le dépôt, les issues, les pull requests ou les discussions.
   Pour expliquer une découverte, on décrit le comportement (trame envoyée, UUID, valeur relue),
   pas le code qui le produit. Les fichiers d'étude restent sur le poste, dans `_local/` (ignoré par
   Git).
3. **Pas de données réelles** : adresses MAC, noms donnés aux modules, plans ou noms de bureaux,
   captures de scan (elles contiennent aussi les appareils voisins : téléphones, montres…). Dans les
   tests et la documentation, utiliser des valeurs fictives (`AA:BB:CC:DD:EE:01`).
4. **Pas de contournement de sécurité** : le projet n'envoie que des commandes que l'appli
   d'origine envoyait, avec le PIN du module. Pas de recherche de PIN par essais, pas d'envoi de
   trames au hasard (fuzzing) sur des modules en service.
5. **Pas de secrets** : clé de signature Android, mots de passe, jetons.

## Utilisation responsable

- Ne piloter que les modules que l'on est autorisé à piloter : ceux de sa zone, dans le respect des
  consignes du gestionnaire du bâtiment. Accéder sans droit à un système informatique est puni par
  la loi (article 323-1 du code pénal).
- Les réglages CVC (ventilation, consigne, occupation) valent pour toute la zone du module.
- Les outils de [`tools/`](../tools) qui écrivent sur les modules (`send.py`, `probe.py`) sont à
  réserver aux modules de sa propre zone.
- Un problème de sécurité se signale en privé : voir [SECURITY.md](../SECURITY.md).
