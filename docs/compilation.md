# Compiler et publier les livrables

Tous les livrables partent du même numéro de version : le fichier [`VERSION`](../VERSION) (`x.y.z`).
Les scripts le lisent par défaut ; `-Version 1.2.1` le remplace ponctuellement.

| Livrable | Commande | Sortie (dans `installer\`) |
|---|---|---|
| Installateur Windows | `.\build.ps1` | `TelecommandeArcom-Setup-<version>.exe` |
| Version portable Windows | `.\package.ps1` | `Arcom-portable-<version>.zip` |
| Appli Android | `.\build-apk.ps1` | `TelecommandeArcom-<version>.apk` |
| CLI Python (pip) | `.venv\Scripts\python -m pip wheel . --no-deps -w installer` | `telecommande_arcom-<version>-py3-none-any.whl` |

`installer\` et `build\` sont ignorés par Git : les livrables sont publiés dans les
[Releases](https://github.com/aubayfab/arcom/releases), jamais dans le dépôt.

## Prérequis communs

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-build.txt -r requirements-dev.txt
npm ci --prefix web
```

Python 3.13 conseillé (version utilisée par la CI et embarquée dans les livrables).

## Installateur Windows (`build.ps1`)

Prérequis en plus : [Inno Setup 6](https://jrsoftware.org/isdl.php).

1. interface web (Vite) → `web\dist`
2. icône (`packaging\make_icon.py`) et informations de version de l'exécutable
3. exécutable autonome PyInstaller (`build\app\ArcomTelecommande`, lanceur `arcom_app.py`), avec
   `LICENCE.txt` et `LICENCES-TIERCES.txt` (`packaging\collect_licenses.py`)
4. installateur Inno Setup (`packaging\arcom.iss`) : installation par utilisateur, sans droits
   administrateur, données dans `%LOCALAPPDATA%\Arcom` (supprimées à la désinstallation)

L'exécutable n'est pas signé : SmartScreen avertit, et l'antivirus d'un poste d'entreprise peut le
bloquer. Seule vraie solution : le signer avec un certificat de signature de code de l'entreprise.

## Version portable (`package.ps1`)

Aucun binaire maison : le Python « embeddable » officiel de python.org (de même version mineure
que `.venv`, signature PSF vérifiée), les dépendances dans `python\pkgs`, nos fichiers `.py`
lisibles dans `app\`, des `.bat` qui ne font qu'appeler `app\arcom_app.py`, un `LISEZMOI.txt`, et
les licences.

Windows refuse de charger une DLL dont le chemin dépasse 260 caractères, même avec les chemins
longs activés : le paquet n'a pas de dossier racine en double et la DLL la plus profonde fait
~95 caractères. Si l'utilisateur l'extrait trop profondément, le lanceur l'explique.

## Appli Android (`build-apk.ps1`)

Prérequis en plus : un JDK 17 ou plus récent, et le SDK Android avec la plateforme 36
(`ANDROID_HOME`, ou `%LOCALAPPDATA%\Android\Sdk`). Sans Android Studio :
[outils en ligne de commande](https://developer.android.com/studio#command-line-tools-only), puis
`android sdk install "platforms;android-36"` et `android sdk install "build-tools;36.0.0"`.

Le script lance les tests, compile, signe, vérifie la signature et copie l'APK dans `installer\`.
Les tests vérifient les trames, puis, avec Robolectric (le vrai framework Android sur la JVM,
versions 10 et 14), que l'écran, la configuration et le rendu des widgets et le service fonctionnent
sans module ni Bluetooth.

### Clé de signature

Créée au premier lancement : `android\keystore\arcom-release.p12`, mots de passe dans
`android\keystore.properties` (tous deux ignorés par Git).

- **À sauvegarder hors du dépôt** (coffre de mots de passe de l'équipe, par exemple). Android
  n'installe une mise à jour par-dessus l'ancienne que si elle est signée par la même clé : sans
  elle, il faudrait désinstaller, ce qui efface modules et noms.
- Un contributeur qui compile chez lui obtient sa propre clé : son APK s'installe, mais pas
  par-dessus une version officielle.
- Pour que la CI signe les APK des releases, ajouter dans *Settings › Secrets and variables ›
  Actions* :

  | Secret | Valeur |
  |---|---|
  | `ANDROID_KEYSTORE_BASE64` | `[Convert]::ToBase64String([IO.File]::ReadAllBytes("android\keystore\arcom-release.p12"))` |
  | `ANDROID_KEYSTORE_PASSWORD` | `storePassword` de `keystore.properties` |
  | `ANDROID_KEY_ALIAS` | `keyAlias` (`arcom`) |
  | `ANDROID_KEY_PASSWORD` | `keyPassword` |

## Réseau d'entreprise avec inspection TLS

Le proxy présente ses propres certificats, connus du magasin de Windows mais pas de celui de Java :
Gradle échoue alors avec `PKIX path building failed`. `build-apk.ps1` fait utiliser à Java le
magasin de Windows (`-Djavax.net.ssl.trustStoreType=Windows-ROOT`) : rien n'est désactivé, ce sont
les certificats auxquels Windows et le navigateur font déjà confiance. Pour lancer Gradle à la main :

```powershell
$env:GRADLE_OPTS = "-Djavax.net.ssl.trustStoreType=Windows-ROOT"
cd android; .\gradlew.bat testDebugUnitTest "-Dorg.gradle.jvmargs=-Xmx2g -Djavax.net.ssl.trustStoreType=Windows-ROOT"
```

`curl` sous Windows peut aussi avoir besoin de `--ssl-no-revoke`.

## Publier une version

1. Mettre à jour [`VERSION`](../VERSION) et ajouter la section correspondante dans
   [`CHANGELOG.md`](../CHANGELOG.md) (`## [x.y.z] - AAAA-MM-JJ`), par une pull request.
2. Une fois fusionnée sur `main` :

   ```powershell
   git tag -a vX.Y.Z -m "Télécommande pour modules Arcom X.Y.Z"
   git push origin vX.Y.Z
   ```

3. Le workflow [Release](../.github/workflows/release.yml) vérifie que le tag correspond à
   `VERSION`, compile l'installateur, la version portable et le paquet pip sur Windows, l'APK sur
   Linux (si les secrets de signature sont configurés), puis crée la release GitHub avec les notes
   du CHANGELOG.
4. Sans secrets de signature, la release est créée en **brouillon** sans APK : compiler l'APK en
   local (`.\build-apk.ps1`), puis

   ```powershell
   gh release upload vX.Y.Z installer\TelecommandeArcom-X.Y.Z.apk
   gh release edit vX.Y.Z --draft=false
   ```
