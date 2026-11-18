; installer.iss - Inno Setup script for the Shelfrip installer.
; Don't run this by hand: "Build Installer.bat" builds the app first and passes these values.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "installer\dist\Shelfrip"
#endif
#ifndef OutputDir
  #define OutputDir "installer"
#endif

[Setup]
; Never change AppId: it's how Windows knows a new version replaces the old one.
AppId={{A7C1E2B4-5D3F-4E8A-9B61-2C7D0F4E9A13}
AppName=Shelfrip
AppVersion={#AppVersion}
AppVerName=Shelfrip {#AppVersion}
AppPublisher=Shelfrip
DefaultDirName={autopf}\Shelfrip
DefaultGroupName=Shelfrip
DisableProgramGroupPage=yes
; Installs for the current user without asking for admin rights (choice offered in the wizard).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=Shelfrip Setup {#AppVersion}
LicenseFile={#SourceDir}\LICENSE.txt
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Shelfrip.exe
SetupIconFile=icon.ico
UninstallDisplayName=Shelfrip
; Close a running Shelfrip before replacing its files.
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Put a shortcut on the desktop"; Flags: unchecked
Name: "startup"; Description: "Start Shelfrip in the background when I sign in (so auto-rip is always ready)"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; files from an older version that no longer exist in this one
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Shelfrip"; Filename: "{app}\Shelfrip.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall Shelfrip"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Shelfrip"; Filename: "{app}\Shelfrip.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\Shelfrip"; Filename: "{app}\Shelfrip.exe"; Parameters: "--background"; WorkingDir: "{app}"; Tasks: startup

[Run]
Filename: "{app}\Shelfrip.exe"; Description: "Open Shelfrip now"; Flags: nowait postinstall skipifsilent

; Your settings and disc database (%APPDATA%\Shelfrip) are kept when uninstalling, so a
; reinstall picks up where you left off. Delete that folder by hand to remove them too.
