<#
.SYNOPSIS
  Compile l'appli Android de la Télécommande Arcom (APK signé, avec widgets).

.DESCRIPTION
  android\ (Kotlin, Gradle)  ->  installer\TelecommandeArcom-<version>.apk

  Prérequis : un JDK 17 ou plus récent ; le SDK Android (plateforme 36) dans ANDROID_HOME ou
  %LOCALAPPDATA%\Android\Sdk. Gradle et les dépendances se téléchargent au premier lancement.

  Clé de signature : créée au premier lancement dans android\keystore\ (mots de passe dans
  android\keystore.properties). À SAUVEGARDER : une mise à jour doit être signée avec la même clé,
  sinon Android refuse de l'installer par-dessus (il faudrait désinstaller, et perdre les réglages).

.EXAMPLE
  .\build-apk.ps1                  # version du fichier VERSION
  .\build-apk.ps1 -Version 1.2.1
#>
param([string]$Version = "")

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $Version) { $Version = (Get-Content (Join-Path $root "VERSION") -Raw).Trim() }
$android = Join-Path $root "android"
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version attendue au format x.y.z" }

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

# Commande externe jugée sur son code de retour : Gradle et keytool écrivent sur stderr des messages
# d'information, que Windows PowerShell 5.1 transformerait sinon en erreurs bloquantes.
function Invoke-Native([string]$what, [scriptblock]$command) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $command 2>&1 | ForEach-Object { "$_" } | Out-Host } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE) { throw "$what a échoué (code $LASTEXITCODE)" }
}

# Version majeure d'un JDK d'après son fichier « release » (0 si ce n'est pas un JDK).
function Get-JdkMajor([string]$dir) {
    $release = Join-Path $dir "release"
    if (-not (Test-Path (Join-Path $dir "bin\javac.exe")) -or -not (Test-Path $release)) { return 0 }
    $match = Select-String -Path $release -Pattern '^JAVA_VERSION="(\d+)' | Select-Object -First 1
    if ($match) { return [int]$match.Matches[0].Groups[1].Value }
    return 0
}

Step "1/3 Outils"
# Le JDK 17+ le plus ancien : c'est la version qu'Android Gradle Plugin et Kotlin éprouvent le plus.
$candidates = @($env:JAVA_HOME, "$env:ProgramFiles\Android\Android Studio\jbr") + @(
    Get-ChildItem "$env:ProgramFiles\Java", "$env:ProgramFiles\Eclipse Adoptium", "$env:ProgramFiles\Microsoft" `
        -Directory -Filter "jdk*" -ErrorAction SilentlyContinue | ForEach-Object FullName)
$jdk = $candidates | Where-Object { $_ -and (Test-Path $_) } | Sort-Object -Unique |
    ForEach-Object { [pscustomobject]@{ Path = $_; Major = Get-JdkMajor $_ } } |
    Where-Object { $_.Major -ge 17 } | Sort-Object Major | Select-Object -First 1
if (-not $jdk) { throw "JDK 17 ou plus récent introuvable (https://adoptium.net)" }

$sdk = @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT, "$env:LOCALAPPDATA\Android\Sdk") |
    Where-Object { $_ -and (Test-Path (Join-Path $_ "platforms")) } | Select-Object -First 1
if (-not $sdk) { throw "SDK Android introuvable : installez Android Studio, ou les outils en ligne de commande (plateforme android-36)" }
Write-Host "JDK $($jdk.Major) : $($jdk.Path)"
Write-Host "SDK : $sdk"
# Fichier .properties : « : » s'échappe, et « / » évite d'avoir à doubler les « \ ».
"sdk.dir=$($sdk -replace '\\', '/' -replace ':', '\:')" | Set-Content (Join-Path $android "local.properties") -Encoding ascii

$props = Join-Path $android "keystore.properties"
if (-not (Test-Path $props)) {
    Write-Host "Création de la clé de signature (android\keystore\) : à sauvegarder." -ForegroundColor Yellow
    $dir = Join-Path $android "keystore"
    New-Item -ItemType Directory -Force $dir | Out-Null
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = [Convert]::ToBase64String($bytes) -replace '[+/=]', ''
    $store = Join-Path $dir "arcom-release.p12"
    $keytool = Join-Path $jdk.Path "bin\keytool.exe"
    Invoke-Native "keytool" {
        & $keytool -genkeypair -noprompt -keystore $store -storetype PKCS12 -alias arcom `
            -keyalg RSA -keysize 3072 -validity 10000 -storepass $password -keypass $password `
            -dname "CN=Telecommande Arcom"
    }
    @("storeFile=keystore/arcom-release.p12", "storePassword=$password", "keyAlias=arcom", "keyPassword=$password") |
        Set-Content $props -Encoding ascii
}

Step "2/3 Tests et compilation $Version (le premier lancement télécharge Gradle et les dépendances)"
$env:JAVA_HOME = $jdk.Path
# Réseau d'entreprise (inspection TLS) : Java fait confiance aux mêmes certificats que Windows et
# le navigateur, au lieu de son propre magasin qui ignore le certificat de l'entreprise.
$trust = "-Djavax.net.ssl.trustStoreType=Windows-ROOT"
$env:GRADLE_OPTS = $trust
Push-Location $android
try {
    Invoke-Native "Gradle" {
        # --no-daemon : rien ne reste en mémoire après coup, et la sortie redirigée se ferme bien.
        & .\gradlew.bat --console=plain --no-daemon "-Dorg.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8 $trust" `
            "-PappVersion=$Version" testDebugUnitTest assembleRelease
    }
} finally { Pop-Location }

Step "3/3 Signature et livrable"
$apk = Join-Path $android "app\build\outputs\apk\release\app-release.apk"
if (-not (Test-Path $apk)) { throw "APK signé introuvable : $apk" }
$apksigner = Get-ChildItem (Join-Path $sdk "build-tools") -Directory | Sort-Object { [version]($_.Name -replace '-.*$', '') } |
    Select-Object -Last 1 | ForEach-Object { Join-Path $_.FullName "apksigner.bat" }
Invoke-Native "apksigner" { & $apksigner verify --print-certs $apk }
$out = Join-Path $root "installer\TelecommandeArcom-$Version.apk"
New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
Copy-Item $apk $out -Force
Write-Host ("`nAPK : {0} ({1:N1} Mo)" -f $out, ((Get-Item $out).Length / 1MB)) -ForegroundColor Green
