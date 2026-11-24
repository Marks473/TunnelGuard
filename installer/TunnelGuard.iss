#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef ReleaseDir
  #error ReleaseDir is required
#endif
#ifndef ProjectDir
  #error ProjectDir is required
#endif
#ifndef ReleaseVersion
  #define ReleaseVersion "1.1.0"
#endif

[Setup]
AppId={{0A2BD0D8-AC43-4C1C-ADD0-C3D12FC565C1}
AppName=TunnelGuard
AppVersion={#ReleaseVersion}
AppPublisher=TunnelGuard contributors
AppPublisherURL=https://github.com/Marks473/TunnelGuard
AppSupportURL=https://github.com/Marks473/TunnelGuard/issues
DefaultDirName={localappdata}\Programs\TunnelGuard
DefaultGroupName=TunnelGuard
OutputDir={#ReleaseDir}
OutputBaseFilename=TunnelGuard-Setup-{#ReleaseVersion}-x64
SetupIconFile={#ProjectDir}\TunnelGuard.ico
UninstallDisplayIcon={app}\TunnelGuard.exe
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.19041
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
CloseApplicationsFilter=TunnelGuard.exe
RestartApplications=no
VersionInfoVersion={#ReleaseVersion}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectDir}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectDir}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\TunnelGuard"; Filename: "{app}\TunnelGuard.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\TunnelGuard"; Filename: "{app}\TunnelGuard.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\TunnelGuard.exe"; Description: "{cm:LaunchProgram,TunnelGuard}"; Flags: nowait postinstall skipifsilent unchecked

[CustomMessages]
english.RuntimeRequired=Microsoft Visual C++ Redistributable x64 is required. Open the official Microsoft download page?
russian.RuntimeRequired=Для TunnelGuard нужен Microsoft Visual C++ Redistributable x64. Открыть официальную страницу Microsoft?

[Code]
function InitializeSetup(): Boolean;
var
  ErrorCode: Integer;
begin
  Result := FileExists(ExpandConstant('{sys}\msvcp140.dll')) and
            FileExists(ExpandConstant('{sys}\vcruntime140.dll')) and
            FileExists(ExpandConstant('{sys}\vcruntime140_1.dll'));
  if not Result then
    if SuppressibleMsgBox(ExpandConstant('{cm:RuntimeRequired}'), mbConfirmation, MB_YESNO, IDNO) = IDYES then
      ShellExec('open', 'https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist',
                '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;
