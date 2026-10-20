## Quoi et pourquoi

<!-- Ce que change cette pull request, et le problème qu'elle résout (« Corrige #12 »). -->

## Essais

<!-- Ce qui a été essayé, et sur quoi : livrable, version de Windows ou d'Android, modèle de module.
     « Tests seulement » est une réponse valable. -->

## Vérifications

- [ ] La CI passe (ruff, pytest, interface web, tests Android).
- [ ] Documentation et section « Non publié » du CHANGELOG mises à jour si besoin.
- [ ] Protocole modifié : `arcomlib.py`, `Protocol.kt`, `docs/protocole.md` et leurs tests vont ensemble.
- [ ] Rien d'issu de l'appli du fabricant (code décompilé, images, textes), aucune donnée réelle
      (adresse MAC, nom de bureau, capture de scan), aucun secret (voir le [cadre juridique](https://github.com/aubayfab/arcom/blob/main/docs/cadre-juridique.md)).
