# Sécurité

## Signaler une faille

Ne pas ouvrir d'issue. Utiliser l'onglet **Security › Report a vulnerability** du dépôt s'il est
proposé, sinon contacter un mainteneur directement (auteurs des derniers commits). Décrire le
problème, comment le reproduire, et ce qu'il permet. Nous accusons réception et tenons au courant de
la correction.

Seule la dernière version publiée est corrigée.

## Ce que le logiciel protège

- **Serveur local** (appli Windows, `server.py`) : il n'écoute que sur `127.0.0.1`, et refuse les
  requêtes venues d'autres sites ouverts dans le navigateur (en-tête `Origin` étranger, corps non
  JSON, nom d'hôte autre que local), pour qu'une page web ne puisse pas piloter les modules (CSRF,
  DNS rebinding). L'option `--host 0.0.0.0` l'ouvrirait à tout le réseau : à éviter.
- **Données** : la liste des modules (adresses MAC, noms donnés, PIN) reste sur le poste ou le
  téléphone (`%LOCALAPPDATA%\Arcom`, données privées de l'appli Android) ; rien n'est envoyé ailleurs.

## Ce qu'il ne protège pas

La sécurité des modules eux-mêmes relève du fabricant et du gestionnaire du bâtiment : leur seule
protection est un PIN à 4 chiffres, `0000` par défaut, et tout appareil Bluetooth à portée qui le
connaît peut piloter la zone. Ce logiciel ne contourne pas cette protection et n'ajoute aucune
possibilité par rapport à l'application d'origine. Aux gestionnaires de bâtiment : définir un PIN
autre que celui par défaut limite le pilotage aux personnes qui le connaissent.
