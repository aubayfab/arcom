<#
.SYNOPSIS
  Compile l'installateur Windows de la Télécommande pour modules Arcom.

.DESCRIPTION
  1. interface web (Vite)  ->  web\dist
  2. icône + informations de version
  3. exécutable autonome (PyInstaller, Python embarqué) + licences  ->  build\app\ArcomTelecommande
  4. installateur (Inno Setup)  ->  installer\TelecommandeArcom-Setup-<version>.exe

  Prérequis : .venv avec requirements.txt + requirements-build.txt, Node (web\node_modules),
  Inno Setup 6 (https://jrsoftware.org/isdl.php).

.EXAMPLE
  .\build.ps1                  # version du fichier VERSION
  .\build.ps1 -Version 1.2.1
#>
param([string]$Version = "")

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $Version) { $Version = (Get-Content (Join-Path $root "VERSION") -Raw).Trim() }
$py = Join-Path $root ".venv\Scripts\python.exe"
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not (Test-Path $py)) { throw "Environnement Python absent : python -m venv .venv puis pip install -r requirements.txt -r requirements-build.txt" }
if (-not $iscc) { throw "Inno Setup 6 introuvable (https://jrsoftware.org/isdl.php)" }
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version attendue au format x.y.z" }

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

# Commande externe jugée sur son code de retour : PyInstaller et npm écrivent leurs messages
# d'information sur stderr, que Windows PowerShell 5.1 transformerait sinon en erreurs bloquantes.
function Invoke-Native([string]$what, [scriptblock]$command) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $command 2>&1 | ForEach-Object { "$_" } | Out-Host } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE) { throw "$what a échoué (code $LASTEXITCODE)" }
}

Step "1/4 Interface web"
Push-Location (Join-Path $root "web")
try { Invoke-Native "npm run build" { npm run build } } finally { Pop-Location }

Step "2/4 Icône et version $Version"
$build = Join-Path $root "build"
New-Item -ItemType Directory -Force $build | Out-Null
Invoke-Native "make_icon" { & $py (Join-Path $root "packaging\make_icon.py") (Join-Path $root "packaging\arcom.ico") }
$v = ($Version.Split('.') + '0') -join ', '
$versionInfo = @"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($v), prodvers=($v), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040C04B0', [
      StringStruct('FileDescription', 'Télécommande pour modules Arcom'),
      StringStruct('FileVersion', '$Version'),
      StringStruct('InternalName', 'ArcomTelecommande'),
      StringStruct('OriginalFilename', 'ArcomTelecommande.exe'),
      StringStruct('ProductName', 'Télécommande pour modules Arcom'),
      StringStruct('ProductVersion', '$Version'),
      StringStruct('Comments', 'Outil non officiel de pilotage local des modules Bluetooth Arcom')])]),
    VarFileInfo([VarStruct('Translation', [0x040C, 1200])])
  ]
)
"@
# UTF-8 sans BOM : PyInstaller évalue ce fichier comme du Python.
[IO.File]::WriteAllText((Join-Path $build "version_info.txt"), $versionInfo, (New-Object Text.UTF8Encoding $false))

Step "3/4 Exécutable autonome (PyInstaller)"
Invoke-Native "PyInstaller" {
    & $py -m PyInstaller --noconfirm --clean --log-level WARN `
        --windowed --name ArcomTelecommande `
        --icon (Join-Path $root "packaging\arcom.ico") `
        --version-file (Join-Path $build "version_info.txt") `
        --add-data "$(Join-Path $root 'web\dist');web\dist" `
        --add-data "$(Join-Path $root 'packaging\arcom.ico');." `
        --collect-submodules bleak.backends.winrt --collect-submodules winrt `
        --exclude-module bleak.backends.corebluetooth --exclude-module bleak.backends.bluezdbus `
        --exclude-module bleak.backends.p4android `
        --hidden-import pystray._win32 `
        --distpath (Join-Path $build "app") --workpath (Join-Path $build "work") --specpath $build `
        (Join-Path $root "arcom_app.py")
}
# Licences : la nôtre, et celles de Python, du chargeur PyInstaller et des dépendances embarquées.
$appDir = Join-Path $build "app\ArcomTelecommande"
Copy-Item (Join-Path $root "LICENSE") (Join-Path $appDir "LICENCE.txt")
Invoke-Native "Licences tierces" {
    & $py (Join-Path $root "packaging\collect_licenses.py") (Join-Path $appDir "LICENCES-TIERCES.txt") --pyinstaller
}

Step "4/4 Installateur (Inno Setup)"
Invoke-Native "Inno Setup" {
    & $iscc /Qp "/DAppVersion=$Version" "/DAppDir=$(Join-Path $build 'app\ArcomTelecommande')" `
        (Join-Path $root "packaging\arcom.iss")
}

$setup = Join-Path $root "installer\TelecommandeArcom-Setup-$Version.exe"
Write-Host ("`nInstallateur : {0} ({1:N1} Mo)" -f $setup, ((Get-Item $setup).Length / 1MB)) -ForegroundColor Green
