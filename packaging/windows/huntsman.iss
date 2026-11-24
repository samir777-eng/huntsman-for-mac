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
;   When PowerShell can't run the helper (policy, Constrained Language Mode), --quit-service is run directly.
;   After an upgrade the lighting service is started again when it was (or may have been) running before. The
;   helper and the service run as the original user (ExecAsOriginalUser), also when Setup itself was run as
;   administrator: an elevated service would lock the normal window out of its pipe. That covers elevating the same
;   account (the usual UAC prompt) only: when another admin account's password is typed in, the registry (HKCU),
;   the temp folder and %LOCALAPPDATA% Setup sees are that admin's, not the user's.
; - Moving from an unzipped copy: when the start-at-login Run value starts another Huntsman.exe, that copy is
;   stopped and the installed service started; the service then points the Run value at itself (ensure_autostart).
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

{ A path as hex digits of its UTF-16 code units, 4 per character: setup-helper.ps1 reads it back (FromHex), and
  nothing on its command line needs quoting. }
function Hex(const S: String): String;
var
  I: Integer;
begin
  Result := '';
  for I := 1 to Length(S) do
    Result := Result + Format('%.4x', [Ord(S[I])]);
end;

{ As the original (non-elevated) user when Setup runs as administrator on the same account (not another admin
  account's); the uninstaller runs as it was started. }
function RunAsUser(const Filename, Params, WorkingDir: String; Wait: TExecWait; var ResultCode: Integer): Boolean;
begin
  if IsUninstaller then
    Result := Exec(Filename, Params, WorkingDir, SW_HIDE, Wait, ResultCode)
  else
    Result := ExecAsOriginalUser(Filename, Params, WorkingDir, SW_HIDE, Wait, ResultCode);
end;

function HasLine(const Lines: TArrayOfString; const Line: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 0 to GetArrayLength(Lines) - 1 do
    if Lines[I] = Line then
      Result := True;
end;

{ Run setup-helper.ps1 (Helper) with Action on Target, hidden, waiting (AsUser: as the original user). Its own
  lines come back in Lines and are copied into this log. False when PowerShell couldn't be started (ResultCode
  is then a Win32 error); otherwise ResultCode is the helper's exit code. }
function RunHelper(const Action, Helper, Target: String; AsUser: Boolean; var Lines: TArrayOfString;
                   var ResultCode: Integer): Boolean;
var
  HelperLog, PowerShell, Params: String;
  I: Integer;
begin
  HelperLog := AddBackslash(GetTempDir) + 'huntsman-setup-helper.log';
  DeleteFile(HelperLog);
  PowerShell := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + Helper + '" ' + Action + ' ' +
            Hex(Target) + ' ' + Hex(HelperLog);
  if AsUser then
    Result := RunAsUser(PowerShell, Params, '', ewWaitUntilTerminated, ResultCode)
  else
    Result := Exec(PowerShell, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  SetArrayLength(Lines, 0);
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
  Lines: TArrayOfString;
begin
  if WebView2Installed then
    Exit;
  WizardForm.StatusLabel.Caption := 'Installing the Microsoft Edge WebView2 Runtime...';
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  ExtractTemporaryFile('setup-helper.ps1');
  { Not as the original user: an elevated Setup may install the runtime for the whole machine. }
  if not RunHelper('webview2', ExpandConstant('{tmp}\setup-helper.ps1'),
                   ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), False, Lines, ResultCode) then
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

{ Huntsman.exe 0.6.0 and later know --quit-service; an older one would open its window instead. }
function KnowsQuitService(const Exe: String): Boolean;
var
  MS, LS: Cardinal;
begin
  Result := GetVersionNumbers(Exe, MS, LS) and (((MS shr 16) > 0) or ((MS and $FFFF) >= 6));
end;

{ Without the helper: ask the lighting service to quit directly. Bounded by Huntsman.exe itself (its IPC timeout
  plus app.QUIT_WAIT, about 20 s). }
procedure QuitServiceDirectly(const Exe: String);
var
  ResultCode: Integer;
begin
  if not KnowsQuitService(Exe) then
  begin
    Log('Not asking ' + Exe + ' to quit: older than 0.6.0');
    Exit;
  end;
  if RunAsUser(Exe, '--quit-service', ExtractFileDir(Exe), ewWaitUntilTerminated, ResultCode) then
    Log(Format('--quit-service exited with %d', [ResultCode]))
  else
    Log('--quit-service did not run: ' + SysErrorMessage(ResultCode));
end;

{ Stop the copy installed in Dir (setup-helper.ps1 stop: its window, then its lighting service, then the rest).
  True when its lighting service was running, or when that isn't known. }
function StopHuntsman(const Dir, Helper: String): Boolean;
var
  Exe: String;
  ResultCode: Integer;
  Lines: TArrayOfString;
begin
  Result := False;
  Exe := AddBackslash(Dir) + 'Huntsman.exe';
  if not FileExists(Exe) then
    Exit;
  if RunHelper('stop', Helper, Exe, True, Lines, ResultCode) and
     ((ResultCode = 0) or (ResultCode = ServiceWasRunningCode)) then
  begin
    Log(Format('setup-helper stop exited with %d', [ResultCode]));
    if HasLine(Lines, 'lighting service was running: yes') or (ResultCode = ServiceWasRunningCode) then
      Result := True
    else if HasLine(Lines, 'lighting service was running: no') then
      Result := False
    else
      Result := True;   { no marker line: unknown, counted as running }
  end
  else
  begin
    Log(Format('setup-helper stop failed (%d): asking the lighting service to quit directly', [ResultCode]));
    QuitServiceDirectly(Exe);
    Result := True;   { unknown: counted as running, so an upgrade starts it again }
  end;
end;

{ The start-at-login Run value starts another Huntsman.exe (an unzipped copy): True, with its path in OldExe. }
function OtherCopyInRunValue(var OldExe: String): Boolean;
var
  Value: String;
  P: Integer;
begin
  Result := False;
  if not RegQueryStringValue(HKCU, RunKey, RunValue, Value) then
    Exit;
  if Pos(Lowercase('"' + ExpandConstant('{app}\Huntsman.exe') + '"'), Lowercase(Value)) = 1 then
    Exit;
  if (Length(Value) < 2) or (Value[1] <> '"') then
    Exit;
  Value := Copy(Value, 2, Length(Value) - 1);
  P := Pos('"', Value);
  if P = 0 then
    Exit;
  OldExe := Copy(Value, 1, P - 1);
  Result := (Lowercase(ExtractFileName(OldExe)) = 'huntsman.exe') and FileExists(OldExe);
end;

{ The installed lighting service, as the original user, in its own folder. }
procedure StartService;
var
  ResultCode: Integer;
begin
  if ExecAsOriginalUser(ExpandConstant('{app}\Huntsman.exe'), '--service', ExpandConstant('{app}'), SW_HIDE,
                        ewNoWait, ResultCode) then
    Log('Lighting service started')
  else
    Log('Lighting service could not be started: ' + SysErrorMessage(ResultCode));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  ExtractTemporaryFile('setup-helper.ps1');   { this version's helper: the copy being replaced may be older }
  ServiceWasRunning := StopHuntsman(WizardDirValue, ExpandConstant('{tmp}\setup-helper.ps1'));
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  OldExe: String;
  Migrated: Boolean;
begin
  if CurStep <> ssPostInstall then
    Exit;
  InstallWebView2;
  { Moving from an unzipped copy: its service would start first at every login. Stop it; the installed service
    started below points the Run value at itself (service.py ensure_autostart). }
  Migrated := False;
  if OtherCopyInRunValue(OldExe) then
  begin
    Log('The Run value starts another copy, ' + OldExe + ': stopping it');
    StopHuntsman(ExtractFileDir(OldExe), ExpandConstant('{tmp}\setup-helper.ps1'));
    Migrated := True;
  end;
  { An upgrade: the lighting service comes back when it was (or may have been) running before. }
  if ServiceWasRunning or Migrated then
    StartService;
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
