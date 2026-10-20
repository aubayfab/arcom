# Composants tiers

Le code de ce dépôt est sous licence [MIT](LICENSE). Les livrables embarquent aussi les composants
ci-dessous, chacun sous sa propre licence. Les livrables Windows contiennent les textes complets
(`LICENCES-TIERCES.txt`, produit à la compilation par
[`packaging/collect_licenses.py`](packaging/collect_licenses.py), avec les versions exactes).

## Appli Windows (installateur et version portable)

| Composant | Licence | Projet |
|---|---|---|
| Python | PSF-2.0 | https://www.python.org |
| Chargeur PyInstaller (installateur seulement) | GPL-2.0 avec exception de distribution | https://pyinstaller.org |
| bleak | MIT | https://github.com/hbldh/bleak |
| winrt-runtime, winrt-Windows.* (pywinrt) | MIT | https://github.com/pywinrt/pywinrt |
| aiohttp | Apache-2.0 et MIT | https://github.com/aio-libs/aiohttp |
| aiohappyeyeballs | PSF-2.0 | https://github.com/aio-libs/aiohappyeyeballs |
| aiosignal, frozenlist, multidict, propcache, yarl | Apache-2.0 | https://github.com/aio-libs |
| attrs | MIT | https://github.com/python-attrs/attrs |
| idna | BSD-3-Clause | https://github.com/kjd/idna |
| typing_extensions | PSF-2.0 | https://github.com/python/typing_extensions |
| Pillow | MIT-CMU | https://github.com/python-pillow/Pillow |
| six | MIT | https://github.com/benjaminp/six |
| **pystray** | **LGPL-3.0** | https://github.com/moses-palmer/pystray |

**pystray (LGPL-3.0)** est utilisé sans modification, pour l'icône près de l'horloge. Ses sources
sont publiées par son auteur et celles de ce projet sont ici : chacun peut reconstruire les
livrables avec une version modifiée de pystray (`build.ps1`, `package.ps1`), ou, dans la version
portable, remplacer directement `python\pkgs\pystray`.

L'installateur est produit avec [Inno Setup](https://jrsoftware.org/isinfo.php), dont la licence
n'impose rien aux installateurs créés.

L'interface web ne contient que notre code, compilé par [Vite](https://vite.dev) (MIT).

## Appli Android

| Composant | Licence | Projet |
|---|---|---|
| Bibliothèque standard Kotlin | Apache-2.0 | https://github.com/JetBrains/kotlin |
| kotlinx.coroutines | Apache-2.0 | https://github.com/Kotlin/kotlinx.coroutines |

## CLI Python (paquet pip)

Le paquet ne contient que notre code. `pip` installe à part sa dépendance
[bleak](https://github.com/hbldh/bleak) (MIT) et les dépendances de celle-ci.
