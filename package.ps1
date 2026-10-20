<#
.SYNOPSIS
  Produit la version portable (zip) de la Télécommande Arcom : rien à compiler ni à installer.

.DESCRIPTION
  Contenu du zip (sans dossier racine : « Extraire tout » de Windows en crée déjà un) :
    python\        distribution « embeddable » officielle de python.org (signée par la PSF)
    python\pkgs\   dépendances (bleak, aiohttp, pystray, Pillow…)
    app\           arcom_app.py, server.py, arcomlib.py, interface web compilée, icône
    *.bat          Lancer / Arreter / Creer les raccourcis / Desinstaller
    LISEZMOI.txt, LICENCE.txt, LICENCES-TIERCES.txt

  Les chemins sont gardés courts : Windows refuse de charger une DLL dont le chemin complet
  dépasse 260 caractères (la plus longue fait ~95 caractères depuis la racine du paquet).

  Sortie : installer\Arcom-portable-<version>.zip

.EXAMPLE
  .\package.ps1                  # version du fichier VERSION
  .\package.ps1 -Version 1.2.1
#>
param([string]$Version = "", [string]$PythonVersion = "")

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $Version) { $Version = (Get-Content (Join-Path $root "VERSION") -Raw).Trim() }
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version attendue au format x.y.z" }
$py = Join-Path $root ".venv\Scripts\python.exe"
$build = Join-Path $root "build"
$cache = Join-Path $build "cache"
$name = "Arcom-portable-$Version"
$stage = Join-Path $build "portable\$name"
$zip = Join-Path $root "installer\$name.zip"

if (-not (Test-Path $py)) { throw "Environnement Python absent : python -m venv .venv puis pip install -r requirements.txt" }

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

# Commande externe jugée sur son code de retour (npm/pip écrivent sur stderr).
function Invoke-Native([string]$what, [scriptblock]$command) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $command 2>&1 | ForEach-Object { "$_" } | Out-Host } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE) { throw "$what a échoué (code $LASTEXITCODE)" }
}

function Write-Text([string]$path, [string]$text, [bool]$bom) {
    $text = $text -replace "`r?`n", "`r`n"
    [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $bom))
}

Step "1/5 Interface web"
Push-Location (Join-Path $root "web")
try { Invoke-Native "npm run build" { npm run build } } finally { Pop-Location }

Step "2/5 Python embarquable officiel"
# Même version mineure que le venv : les dépendances compilées (aiohttp, winrt, Pillow) en dépendent.
$minor = (& $py -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
if (-not $PythonVersion) {
    $index = (Invoke-WebRequest "https://www.python.org/ftp/python/" -UseBasicParsing).Content
    $candidates = [regex]::Matches($index, "href=""($([regex]::Escape($minor))\.\d+)/""") |
        ForEach-Object { $_.Groups[1].Value } | Sort-Object { [version]$_ } -Descending
    foreach ($c in $candidates) {
        try {
            Invoke-WebRequest "https://www.python.org/ftp/python/$c/python-$c-embed-amd64.zip" -Method Head -UseBasicParsing | Out-Null
            $PythonVersion = $c; break
        } catch { }
    }
    if (-not $PythonVersion) { throw "Aucune distribution embarquable Python $minor trouvée sur python.org" }
}
New-Item -ItemType Directory -Force $cache | Out-Null
$embed = Join-Path $cache "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $embed)) {
    Write-Host "Téléchargement de Python $PythonVersion…"
    Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $embed -UseBasicParsing
}

# Dossier de préparation neuf (on ne supprime que sous build\portable).
$portable = Join-Path $build "portable"
if (Test-Path $stage) {
    if (-not (Resolve-Path $stage).Path.StartsWith((Resolve-Path $portable).Path)) { throw "Chemin inattendu : $stage" }
    Remove-Item -LiteralPath $stage -Recurse -Force
}
New-Item -ItemType Directory -Force $stage | Out-Null
Expand-Archive -LiteralPath $embed -DestinationPath (Join-Path $stage "python")

foreach ($exe in "python.exe", "pythonw.exe") {
    $sig = Get-AuthenticodeSignature (Join-Path $stage "python\$exe")
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Python Software Foundation") {
        throw "Signature inattendue pour $exe : $($sig.Status) $($sig.SignerCertificate.Subject)"
    }
}
Write-Host "Python $PythonVersion, signature PSF vérifiée."

# Chemins de recherche : la distribution embarquable ignore PYTHONPATH et lit ce fichier.
$pth = Get-ChildItem (Join-Path $stage "python") -Filter "python*._pth" | Select-Object -First 1
$zipName = (Get-ChildItem (Join-Path $stage "python") -Filter "python*.zip" | Select-Object -First 1).Name
Write-Text $pth.FullName "$zipName`n.`npkgs`n..\app`nimport site`n" $false

Step "3/5 Dépendances"
Invoke-Native "pip install" {
    & $py -m pip install --quiet --disable-pip-version-check --no-warn-script-location `
        --target (Join-Path $stage "python\pkgs") `
        --only-binary=:all: --platform win_amd64 --implementation cp --python-version $minor `
        -r (Join-Path $root "requirements.txt")
}

Step "4/5 Application et scripts"
$app = Join-Path $stage "app"
New-Item -ItemType Directory -Force (Join-Path $app "packaging"), (Join-Path $app "web") | Out-Null
Copy-Item (Join-Path $root "arcom_app.py"), (Join-Path $root "server.py"), (Join-Path $root "arcomlib.py") $app
Copy-Item (Join-Path $root "web\dist") (Join-Path $app "web\dist") -Recurse
Invoke-Native "make_icon" { & $py (Join-Path $root "packaging\make_icon.py") (Join-Path $app "packaging\arcom.ico") }
# Licences : la nôtre, et celles des dépendances réellement copiées dans python\pkgs
# (celle de Python est déjà fournie par la distribution embarquable : python\LICENSE.txt).
Copy-Item (Join-Path $root "LICENSE") (Join-Path $stage "LICENCE.txt")
Invoke-Native "Licences tierces" {
    & $py (Join-Path $root "packaging\collect_licenses.py") (Join-Path $stage "LICENCES-TIERCES.txt") `
        --path (Join-Path $stage "python\pkgs")
}

# .bat en ASCII : cmd.exe lit ces fichiers dans la page de code OEM, les accents y seraient abîmés.
Write-Text (Join-Path $stage "Lancer la telecommande.bat") @'
@echo off
rem Lance la telecommande (icone pres de l'horloge) et ouvre l'interface dans le navigateur.
rem Si elle tourne deja, rouvre simplement l'interface.
start "" "%~dp0python\pythonw.exe" "%~dp0app\arcom_app.py"
'@ $false
Write-Text (Join-Path $stage "Arreter la telecommande.bat") @'
@echo off
rem Arrete proprement la telecommande (comme "Quitter" dans l'icone pres de l'horloge).
"%~dp0python\python.exe" "%~dp0app\arcom_app.py" --arreter
timeout /t 3 /nobreak >nul
'@ $false
Write-Text (Join-Path $stage "Creer les raccourcis.bat") @'
@echo off
rem Cree les raccourcis sur le Bureau et dans le menu Demarrer (et, au choix, au demarrage de Windows).
start "" "%~dp0python\pythonw.exe" "%~dp0app\arcom_app.py" --raccourcis
'@ $false
Write-Text (Join-Path $stage "Desinstaller.bat") @'
@echo off
rem Arrete la telecommande, supprime ses raccourcis et ses donnees. Supprimer ensuite ce dossier.
start "" "%~dp0python\pythonw.exe" "%~dp0app\arcom_app.py" --desinstaller
'@ $false

Write-Text (Join-Path $stage "LISEZMOI.txt") @"
TÉLÉCOMMANDE ARCOM $Version — version portable
==================================================

Pilote depuis ce PC, en Bluetooth, l'éclairage et les stores des modules Arcom.
Rien à installer : tout est dans ce dossier. Outil non officiel.

1. AVANT DE COMMENCER
   - Windows 10 ou 11 (64 bits), avec le Bluetooth activé.
   - Si le zip vient d'Internet ou d'un e-mail : clic droit sur le zip > Propriétés >
     cocher « Débloquer » > OK, AVANT de l'extraire.
   - Extraire le zip (clic droit > Extraire tout…) dans un dossier qui ne bougera plus et
     peu profond, par exemple « Documents ». Évitez les dossiers très imbriqués : Windows
     limite la longueur des chemins (la télécommande vous préviendra si c'est le cas).
   - Sur un PC d'entreprise, vérifiez avec votre service informatique que vous pouvez
     utiliser cet outil.

2. LANCER
   Double-cliquer sur « Lancer la telecommande ».
   La télécommande s'ouvre dans le navigateur, et une ampoule apparaît près de l'horloge
   (parfois cachée derrière la petite flèche ^) : clic pour rouvrir la télécommande,
   clic droit > Quitter pour l'arrêter.

   Au premier lancement, les modules proches sont recherchés automatiquement et classés
   du plus proche au plus lointain. Mettez le vôtre en favori avec l'étoile ★ (il passe en
   tête de liste), puis cliquez sur son titre pour lui donner un nom (« Mon bureau »…).

   CONNEXION : en bas de chaque carte, deux interrupteurs, désactivés au départ.
   - Aucun : chaque commande se connecte au module (3 à 5 secondes), agit, puis le libère
     pour les autres (un module n'accepte qu'une connexion à la fois).
   - « Maintenir la connexion » : le module reste connecté pour enchaîner les commandes,
     jusqu'à ce que vous cliquiez sur « Se déconnecter ».
   - « Connexion auto » : connecté automatiquement et en permanence, commandes immédiates ;
     pas de déconnexion possible tant qu'elle est activée.

3. RACCOURCIS (conseillé)
   Double-cliquer sur « Creer les raccourcis » : icône sur le Bureau et dans le menu
   Démarrer, et, si vous le souhaitez, lancement automatique au démarrage de Windows.
   Ne déplacez plus ce dossier ensuite (sinon, recréez les raccourcis).

4. ARRÊTER
   Ampoule près de l'horloge > Quitter, ou « Arreter la telecommande ».

5. DÉSINSTALLER
   « Desinstaller » (supprime raccourcis et données), puis supprimer ce dossier.

EN CAS DE PROBLÈME
   - Bandeau « Bluetooth désactivé » : activez le Bluetooth (Paramètres Windows >
     Bluetooth et appareils), la télécommande reprend toute seule.
   - Journal : ampoule > Voir le journal (fichier %LOCALAPPDATA%\Arcom\arcom.log).

LICENCES
   Logiciel libre sous licence MIT (LICENCE.txt), non affilié au fabricant des modules.
   Composants tiers inclus et leurs licences : LICENCES-TIERCES.txt.
"@ $true

Step "5/5 Archive"
New-Item -ItemType Directory -Force (Split-Path $zip) | Out-Null
Invoke-Native "zip" {
    & $py -c @"
import sys, zipfile, pathlib
stage, out = pathlib.Path(sys.argv[1]), sys.argv[2]
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in sorted(stage.rglob('*')):
        if f.is_file():  # __pycache__ compris : premier lancement plus rapide
            z.write(f, f.relative_to(stage))
"@ $stage $zip
}
$size = (Get-Item $zip).Length / 1MB
$unzipped = (Get-ChildItem $stage -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("`nPaquet portable : {0} ({1:N1} Mo, {2:N0} Mo une fois extrait)" -f $zip, $size, $unzipped) -ForegroundColor Green
