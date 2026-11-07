; =====================================================================================================================
;  Kestrel - Windows installer (Inno Setup 6). build_installer.bat compiles it; you do not need to open it.
;  In:  dist\Kestrel.exe (from build_bot_exe.bat) + .env.example + the guide
;  Out: installer\Kestrel_Setup_3.12.0.exe  - copy that one file to any Windows 10/11 PC and run it.
;
;  - Installs for the current Windows user only (no administrator rights): %LOCALAPPDATA%\Programs\Kestrel.
;    The app folder stays writable, so the bot's .env file lives next to Kestrel.exe as usual.
;  - NEVER packs your .env (your keys): every PC gets its own .env (see the last page of the installer).
;  - Uninstall removes the program files only. Your .env, settings, journals and candle cache stay
;    (%LOCALAPPDATA%\Kestrel\ and the .env in the app folder) - an update keeps them too.
; =====================================================================================================================
#define AppName "Kestrel"
#define AppVersion "3.12.0"
#define AppExe "Kestrel.exe"

[Setup]
AppId={{8C4F2A71-3B5E-4D2A-9C61-5E0B7A1D3F11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Kestrel
DefaultDirName={localappdata}\Programs\Kestrel
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=Kestrel_Setup_{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "USER_GUIDE_BOT.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "CHANGES_3.12.0.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "img\*"; DestDir: "{app}\img"; Flags: ignoreversion skipifsourcedoesntexist
Source: "extra_tickers.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist skipifsourcedoesntexist
; .env is NOT listed on purpose - your keys never go into the installer.

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autoprograms}\{#AppName} - keys and settings (.env)"; Filename: "{win}\notepad.exe"; Parameters: """{app}\.env"""; WorkingDir: "{app}"
Name: "{autoprograms}\{#AppName} - app folder"; Filename: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent unchecked

[Messages]
FinishedLabel=Kestrel is installed.%n%nOn this PC the bot needs its own .env file with your keys: start the app once (it creates .env in the app folder), then open Start menu > Kestrel - keys and settings (.env) and fill in the TradeZero keys and the Discord webhook. Or copy your .env from your main PC into the app folder.%n%nIB Gateway must be installed and logged in on this PC too.%n%nRun the bot on ONE PC at a time per TradeZero account - two running bots would both place orders.

[Code]
const
  WV2Key = '\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function WV2Version(Root: Integer; Key: String): String;
var
  V: String;
begin
  Result := '';
  if RegQueryStringValue(Root, Key, 'pv', V) then
    if (V <> '') and (V <> '0.0.0.0') then
      Result := V;
end;

function WebView2Installed(): Boolean;
begin
  Result := (WV2Version(HKLM, 'SOFTWARE\WOW6432Node' + WV2Key) <> '') or
            (WV2Version(HKLM, 'SOFTWARE' + WV2Key) <> '') or
            (WV2Version(HKCU, 'Software' + WV2Key) <> '');
end;

function InitializeSetup(): Boolean;
var
  Code: Integer;
begin
  Result := True;
  if not WebView2Installed() then
  begin
    if MsgBox('Kestrel draws its window with Microsoft Edge WebView2, which is not installed on this PC.' + #13#10 + #13#10 +
              'Open the Microsoft download page now? (Install "Evergreen Bootstrapper", then run this setup again.)',
              mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', 'https://go.microsoft.com/fwlink/p/?LinkId=2124703', '', '', SW_SHOWNORMAL, ewNoWait, Code);
    Result := MsgBox('Continue the installation anyway? (The app will not open until WebView2 is installed.)',
                     mbConfirmation, MB_YESNO) = IDYES;
  end;
end;
