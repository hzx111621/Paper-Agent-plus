; 中文说明：这是 Windows 安装包脚本。默认安装到当前用户目录，不需要管理员权限，
; 用户可以在向导里改安装位置，并自行选择是否创建桌面图标。
#define MyAppName "Paper-Agent · 河海大学"
#define MyAppVersion "1.0.4"
#define MyAppPublisher "河海大学人工智能与多媒体安全实验室"
#define MyAppExeName "Paper-Agent-Hohai.exe"

[Setup]
AppId={{C4B20B05-1455-4BDE-BA4F-7C53BC77A7F4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Paper-Agent-Hohai
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=Paper-Agent-Hohai-Setup
SetupIconFile=hohai.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "创建桌面图标"; GroupDescription: "附加图标："; Flags: unchecked

[Files]
Source: "..\release\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
