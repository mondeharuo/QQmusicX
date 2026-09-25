#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef PackageDir
  #error PackageDir must point to the staged Windows distribution directory.
#endif

[Setup]
AppId={{AF8AADE0-7F89-4A81-AC36-C818E3943C29}
AppName=QQmusicX
AppVersion={#AppVersion}
AppPublisher=QQmusicX contributors
DefaultDirName={localappdata}\Programs\QQmusicX
DefaultGroupName=QQmusicX
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=QQmusicX-Setup-x64-v{#AppVersion}
UninstallDisplayIcon={app}\QQmusicX.exe
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
ChangesAssociations=no
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\QQmusicX"; Filename: "{app}\QQmusicX.exe"
Name: "{autodesktop}\QQmusicX"; Filename: "{app}\QQmusicX.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\QQmusicX.exe"; Description: "Launch QQmusicX"; Flags: postinstall nowait skipifsilent
