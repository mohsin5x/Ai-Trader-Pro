; AI Trader Pro - Inno Setup script
; ------------------------------------------------------------
; Produces a single "AI Trader Pro Setup.exe" that installs the
; PyInstaller-built app on any Windows PC -- no Python, no MT5 needed.
;
; Build order (see packaging/BUILD_INSTRUCTIONS.md):
;   1. pyinstaller packaging/AI_Trader_Pro.spec --noconfirm
;      -> produces dist/AI Trader Pro/
;   2. Install Inno Setup (https://jrsoftware.org/isinfo.php)
;   3. Compile this script (ISCC.exe packaging\installer.iss) or open
;      it in the Inno Setup IDE and click Build.
;   -> produces packaging/output/AI Trader Pro Setup.exe

#define MyAppName "AI Trader Pro"
#define MyAppVersion "2.0"
#define MyAppExeName "AI Trader Pro.exe"
#define MyAppPublisher "AI Trader Pro"

[Setup]
AppId={{6C6E6B2E-6B2A-4E2B-9A6D-AITRADERPRO01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=AI Trader Pro Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Everything PyInstaller collected into dist/AI Trader Pro/
Source: "..\dist\AI Trader Pro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Ship the .env.example so users can see how to add their API key;
; never ship a real .env with a live API key inside the installer.
Source: "..\.env.example"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Messages]
FinishedLabel=Setup has installed {#MyAppName}.%n%nBefore first launch, copy .env.example to .env in the install folder and add your Twelve Data / Finnhub / Alpha Vantage API key.
