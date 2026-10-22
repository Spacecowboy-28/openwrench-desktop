; OpenWrench Windows installer (Inno Setup 6).
;
; Build with scripts/make_installer.py, which passes /DAppVersion and /DSourceDir.
; This file is intentionally static; the version and source paths come from the
; build script so a version bump never has to edit this file.
;
; Data preservation contract: the user's workspace lives under
;   %LOCALAPPDATA%\OpenWrench\OpenWrench   (Qt AppLocalDataLocation)
; which is *not* the install directory. Uninstall therefore never removes the
; workspace; it only removes program files. The optional "remove my data" prompt is
; offered at uninstall time and defaults to No.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\OpenWrench"
#endif
#ifndef AppNumericVersion
  #define AppNumericVersion "0.0.0.0"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

#define AppName "OpenWrench"
#define AppPublisher "OpenWrench"
#define AppExeName "OpenWrench.exe"
#define AppURL "https://github.com/Spacecowboy-28/openwrench-desktop"

[Setup]
AppId={{7C4B2E6A-9D3F-4A5B-9C1E-6F0A1B2C3D4E}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppNumericVersion}
VersionInfoProductTextVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile={#SourceDir}\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=OpenWrench-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#SourceDir}\_internal\assets\openwrench.ico
MinVersion=10.0.17763
SetupLogging=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The app is a PyInstaller onedir bundle; never let Setup reuse a running copy.
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
; Install and launch as the current user, without an administrator prompt.
; {autopf} resolves to the per-user Programs directory in this mode.
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole onedir bundle. recursesubdirs + createallsubdirs keeps the layout
; PyInstaller expects; ignoreversion is safe because an upgrade replaces all files.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove only untracked runtime files Setup created. The workspace under
; %LOCALAPPDATA% is left alone here; see CurUninstallStepChanged below.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
// Uninstall: the workspace is user data, so removing it is an explicit choice that
// defaults to No. This is the only place OpenWrench deletes user data.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\OpenWrench\OpenWrench');
    // Automation and silent uninstall always retain data and never open a prompt.
    if (not UninstallSilent) and DirExists(DataDir) then
    begin
      if MsgBox('Also delete your OpenWrench workspace (vehicle records, repair library and backups) in:' + #13#10 +
                DataDir + #13#10#13#10 +
                'Choose No to keep your data for a future reinstall.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
