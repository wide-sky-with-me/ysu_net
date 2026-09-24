; Inno Setup script for the Windows installer; build.py passes AppVersion and SourceDir.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{98C89A4C-D492-429C-9E0B-079A766F6EE7}
AppName=YSU Net
AppVersion={#AppVersion}
AppPublisher=ysu-net
DefaultDirName={localappdata}\Programs\YSU Net
DefaultGroupName=YSU Net
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputBaseFilename=YSU-Net-{#AppVersion}-windows-setup
SetupIconFile={#SourceDir}\..\ysu-net.ico
UninstallDisplayIcon={app}\ysu-net.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl")
Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\YSU Net"; Filename: "{app}\ysu-net.exe"
Name: "{autodesktop}\YSU Net"; Filename: "{app}\ysu-net.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ysu-net.exe"; Description: "{cm:LaunchProgram,YSU Net}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C reg delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v ""YSU Net"" /f"; Flags: runhidden; RunOnceId: "RemoveAutostart"
