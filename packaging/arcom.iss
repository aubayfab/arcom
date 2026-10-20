; Installateur Windows de la Télécommande Arcom (Inno Setup 6).
; Compilé par build.ps1 : ISCC /DAppVersion=x.y.z packaging\arcom.iss
; Installation par utilisateur, sans droits administrateur, dans %LOCALAPPDATA%\Programs.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef AppDir
  #define AppDir "..\build\app\ArcomTelecommande"
#endif
#define AppName "Télécommande Arcom"
#define AppExe "ArcomTelecommande.exe"

[Setup]
AppId={{6F2C3E1A-8B4D-4C7E-9A51-2D7F0B3C9E84}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppComments=Pilotage local des modules Bluetooth Arcom (éclairage, stores). Outil non officiel.
DefaultDirName={autopf}\Telecommande Arcom
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 1809 minimum (API Bluetooth LE utilisée par bleak)
MinVersion=10.0.17763
SetupIconFile=arcom.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\installer
OutputBaseFilename=TelecommandeArcom-Setup-{#AppVersion}

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Lancer la télécommande au démarrage de Windows"; GroupDescription: "Démarrage :"; Flags: unchecked

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Une mise à jour remplace entièrement l'ancienne version (bibliothèques obsolètes comprises).
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "--background"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "StopApp"

[UninstallDelete]
; Données (liste des modules, noms donnés, journal)
Type: filesandordirs; Name: "{localappdata}\Arcom"

[Code]
// Ferme la télécommande si elle tourne, pour pouvoir remplacer ses fichiers.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
