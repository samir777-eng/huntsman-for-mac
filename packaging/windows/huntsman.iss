; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 Huntsman for Mac contributors
;
; The Windows installer wizard (Inno Setup 6, experimental, unsigned): Welcome -> License (GPL) -> folder -> Install
; -> Finish ("Open Huntsman for Mac"). It installs the PyInstaller folder dist\Huntsman (packaging/windows/huntsman.spec)
; for the current user only, no administrator rights: to %LOCALAPPDATA%\Programs\Huntsman for Mac, a Start menu
; shortcut, an optional desktop icon (off by default), and an uninstaller in Settings > Apps.
;
; - WebView2: the window needs the Microsoft Edge WebView2 Runtime (built into Windows 11, may be missing on Windows
;   10). When the registry says it is missing, Microsoft's Evergreen bootstrapper (downloaded by the build, never
;   committed) runs silently, at most 10 minutes. Run without elevation, as here, it installs the runtime per-user
;   (no UAC prompt); a per-machine Edge updater, when there is one, later replaces that with a per-machine install
;   (learn.microsoft.com/microsoft-edge/webview2/concepts/distribution, "Installing the Runtime as per-machine or
;   per-user", read 2026-11-24). If it fails the install still finishes, and the Finish page says where to get it.
; - Upgrade and uninstall: the running copy is stopped first by setup-helper.ps1 ("stop"): its window is closed,
;   then Huntsman.exe --quit-service asks the lighting service to quit over its IPC (it restores the keyboard's own
;   lighting, like the tray's "Quit lighting service"), then anything of that exact exe still running is ended.
;   After an upgrade the lighting service is started again, only when it was running before.
; - Uninstall: also removes the start-at-login Run value "Huntsman for Mac lighting" when it starts this copy
;   (Huntsman.exe --remove-autostart, with a fallback here). Settings in %APPDATA%\Huntsman for Mac are kept.
;
; Built by .github/workflows/windows-build.yml, from the repository root:
;   ISCC /DAppVersion=<huntsman_core.__version__> packaging\windows\huntsman.iss
; -> dist\Huntsman-for-Windows-<version>-Setup.exe
; Keep this file ASCII (Inno Setup reads a script without a BOM as ANSI).

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=<huntsman_core.__version__>
#endif
#ifndef WebView2Bootstrapper
  #define WebView2Bootstrapper "..\..\dist\MicrosoftEdgeWebview2Setup.exe"
#endif

[Setup]
; Never change AppId: upgrades find the existing install by it.
AppId={{3B18B4A2-4894-4CDB-9662-6307C10A5D1F}
AppName=Huntsman for Mac
AppVersion={#AppVersion}
AppPublisher=Huntsman for Mac contributors
AppPublisherURL=https://github.com/samir777-eng/huntsman-for-mac
AppSupportURL=https://github.com/samir777-eng/huntsman-for-mac/issues
AppUpdatesURL=https://github.com/samir777-eng/huntsman-for-mac/releases
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Huntsman for Mac (Windows build) Setup
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Huntsman for Mac
DisableProgramGroupPage=yes
DisableWelcomePage=no
DisableDirPage=auto
LicenseFile=..\..\LICENSE
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\Huntsman.exe
UninstallDisplayName=Huntsman for Mac
CloseApplications=yes
RestartApplications=no
OutputDir=..\..\dist
OutputBaseFilename=Huntsman-for-Windows-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This installs [name/ver] for you only. No administrator password is needed.%n%nThe Windows build is experimental: it is tested automatically, but not yet on a PC with a Huntsman keyboard.
ConfirmUninstall=Remove %1 from this PC?%n%nThe lighting service is stopped first, and the keyboard goes back to its own lighting. Your settings and Studio presets are kept (in AppData\Roaming\Huntsman for Mac).

[Tasks]
Name: "desktopicon"; Description: "Put an icon on the desktop"; Flags: unchecked

[Files]
Source: "..\..\dist\Huntsman\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "setup-helper.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#WebView2Bootstrapper}"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\Huntsman for Mac"; Filename: "{app}\Huntsman.exe"
Name: "{autodesktop}\Huntsman for Mac"; Filename: "{app}\Huntsman.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Huntsman.exe"; Description: "Open Huntsman for Mac"; Flags: nowait postinstall skipifsilent

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  RunValue = 'Huntsman for Mac lighting';
  WebView2Client = 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2Page = 'https://developer.microsoft.com/microsoft-edge/webview2/';
  ServiceWasRunningCode = 10;   { setup-helper.ps1 stop: the lighting service was running }

var
  WebView2Failed: Boolean;
  ServiceWasRunning: Boolean;

function SetEnvironmentVariable(lpName: String; lpValue: String): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

{ Run setup-helper.ps1 (Helper) with Action, hidden, waiting; Name=Value pairs go in the environment, never on the
  command line. Its own log lines are copied into this log. False when PowerShell couldn't be started (ResultCode
  is then a Win32 error); otherwise ResultCode is the helper's exit code. }
function RunHelper(const Action, Helper: String; var ResultCode: Integer): Boolean;
var
  HelperLog: String;
  Lines: TArrayOfString;
  I: Integer;
begin
  HelperLog := AddBackslash(GetTempDir) + 'huntsman-setup-helper.log';
  DeleteFile(HelperLog);
  SetEnvironmentVariable('HUNTSMAN_SETUP_LOG', HelperLog);
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
                 '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + Helper + '" ' + Action, '',
                 SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if LoadStringsFromFile(HelperLog, Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
      Log('setup-helper ' + Action + ': ' + Lines[I]);
  DeleteFile(HelperLog);
  if not Result then
    Log('setup-helper ' + Action + ': PowerShell could not be started: ' + SysErrorMessage(ResultCode));
end;

{ The runtime is there when its EdgeUpdate client key has a real version ('pv'): per machine (the 32-bit
  registry view on 64-bit Windows) or per user. }
function UsableVersion(const Version: String): Boolean;
begin
  Result := (Version <> '') and (Version <> '0.0.0.0');
end;

function WebView2Installed: Boolean;
var
  Version: String;
begin
  Result := (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\' + WebView2Client, 'pv', Version) and UsableVersion(Version))
    or (RegQueryStringValue(HKCU, 'Software\' + WebView2Client, 'pv', Version) and UsableVersion(Version));
  if Result then
    Log('WebView2 Runtime found: ' + Version)
  else
    Log('WebView2 Runtime not found');
end;

procedure InstallWebView2;
var
  ResultCode: Integer;
begin
  if WebView2Installed then
    Exit;
  WizardForm.StatusLabel.Caption := 'Installing the Microsoft Edge WebView2 Runtime...';
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  ExtractTemporaryFile('setup-helper.ps1');
  SetEnvironmentVariable('HUNTSMAN_WEBVIEW2', ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'));
  if not RunHelper('webview2', ExpandConstant('{tmp}\setup-helper.ps1'), ResultCode) then
  begin
    WebView2Failed := True;   { not fatal: the app is installed, the Finish page says how to get the runtime }
    Log('WebView2 Runtime could not be installed: ' + SysErrorMessage(ResultCode));
  end
  else if ResultCode = 0 then
    Log('WebView2 Runtime installed')
  else
  begin
    WebView2Failed := True;
    Log(Format('WebView2 Runtime could not be installed (bootstrapper exit code %d)', [ResultCode]));
  end;
end;

{ Stop the copy installed in Dir (setup-helper.ps1 stop: its window, then its lighting service, then the rest).
  True when its lighting service was running. }
function StopHuntsman(const Dir, Helper: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if not FileExists(AddBackslash(Dir) + 'Huntsman.exe') then
    Exit;
  SetEnvironmentVariable('HUNTSMAN_EXE', AddBackslash(Dir) + 'Huntsman.exe');
  if RunHelper('stop', Helper, ResultCode) then
  begin
    Log(Format('setup-helper stop exited with %d', [ResultCode]));
    Result := ResultCode = ServiceWasRunningCode;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  ExtractTemporaryFile('setup-helper.ps1');   { this version's helper: the copy being replaced may be older }
  ServiceWasRunning := StopHuntsman(WizardDirValue, ExpandConstant('{tmp}\setup-helper.ps1'));
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep <> ssPostInstall then
    Exit;
  InstallWebView2;
  { An upgrade: the lighting service comes back only when it was running before. }
  if ServiceWasRunning then
    if Exec(ExpandConstant('{app}\Huntsman.exe'), '--service', '', SW_HIDE, ewNoWait, ResultCode) then
      Log('Lighting service started again')
    else
      Log('Lighting service could not be started again: ' + SysErrorMessage(ResultCode));
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and WebView2Failed then
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 +
      'The Microsoft Edge WebView2 Runtime could not be installed, and the Huntsman window needs it. ' +
      'Get it from ' + WebView2Page + ' (or Windows Update), then open Huntsman for Mac again.';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dir, Exe, Ours, Value: String;
  ResultCode: Integer;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  Dir := ExpandConstant('{app}');
  StopHuntsman(Dir, AddBackslash(Dir) + 'setup-helper.ps1');
  Exe := AddBackslash(Dir) + 'Huntsman.exe';
  if FileExists(Exe) then
    if Exec(Exe, '--remove-autostart', Dir, SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Log(Format('Huntsman.exe --remove-autostart exited with %d', [ResultCode]));
  { Fallback when that couldn't run: the Run value, if it starts exactly this exe. Another copy's is left alone. }
  Ours := '"' + ExpandConstant('{app}\Huntsman.exe') + '"';
  if RegQueryStringValue(HKCU, RunKey, RunValue, Value) and (Pos(Lowercase(Ours), Lowercase(Value)) = 1) then
    if RegDeleteValue(HKCU, RunKey, RunValue) then
      Log('Removed the Run value ' + RunValue);
end;
