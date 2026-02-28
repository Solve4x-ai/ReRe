; Inno Setup 6 script for ReRe
; Optional: Sign Setup.exe with a code-signing certificate (Signtool in Inno Setup or external)
#define MyAppName "ReRe"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "Solve4x LLC"
#define MyAppExeName "ReRe.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; DefaultDirName: use {autopf}\SystemUtilities for generic folder name
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; OutputDir relative to this .iss -> installer\Output\ReRe_Setup_v1.0.exe
OutputDir=Output
OutputBaseFilename=ReRe_Setup_v1.2
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
LicenseFile=license.txt
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; SignTool=signcmd /d $qReRe$q $f

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\ReRe\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "Run as administrator (right-click if needed)"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "Run as administrator (right-click if needed)"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runascurrentuser

[UninstallDelete]
Type: dirifempty; Name: "{app}"
