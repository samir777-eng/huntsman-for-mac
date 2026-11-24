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
;   committed) runs silently. If that fails the install still finishes, and the Finish page says where to get it.
; - Upgrade and uninstall: the running copy is stopped first. Huntsman.exe --quit-service asks the lighting service
;   to quit over its IPC (it restores the keyboard's own lighting, like the tray's "Quit lighting service"); then
;   the window is closed and anything of this folder still running is ended.
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

var
  WebView2Failed: Boolean;

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
  if Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE,
          ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
    Log('WebView2 Runtime installed')
  else
  begin
    WebView2Failed := True;   { not fatal: the app is installed, the Finish page says how to get the runtime }
    Log(Format('WebView2 Runtime could not be installed (exit code %d)', [ResultCode]));
  end;
end;

function PowerShellQuote(const S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '''', '''''', True);
  Result := '''' + Result + '''';
end;

{ Stop the copy installed in Dir: ask its lighting service to quit (it restores the keyboard's lighting), then
  close its window, then end whatever of that folder is still running. }
procedure StopHuntsman(const Dir: String);
var
  Exe, Script: String;
  ResultCode: Integer;
begin
  Exe := AddBackslash(Dir) + 'Huntsman.exe';
  if not FileExists(Exe) then
    Exit;
  if Exec(Exe, '--quit-service', Dir, SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Log(Format('Huntsman.exe --quit-service exited with %d', [ResultCode]))
  else
    Log('Huntsman.exe --quit-service did not run: ' + SysErrorMessage(ResultCode));
  Script := '$d = ' + PowerShellQuote(AddBackslash(Dir)) + '; ' +
    '$p = @(Get-Process -Name Huntsman -ErrorAction SilentlyContinue | Where-Object { $_.Path -and ' +
    '$_.Path.StartsWith($d, [StringComparison]::OrdinalIgnoreCase) }); ' +
    'foreach ($x in $p) { [void]$x.CloseMainWindow() }; ' +
    'foreach ($x in $p) { if (-not $x.WaitForExit(5000)) { Stop-Process -Id $x.Id -Force -ErrorAction SilentlyContinue } }; ' +
    'Write-Output (''stopped '' + $p.Count)';
  if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
          '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' + Script + '"', '', SW_HIDE,
          ewWaitUntilTerminated, ResultCode) then
    Log(Format('Closing Huntsman.exe processes in %s exited with %d', [Dir, ResultCode]))
  else
    Log('Could not run PowerShell to close Huntsman.exe: ' + SysErrorMessage(ResultCode));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopHuntsman(WizardDirValue);   { an upgrade: the copy being replaced }
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    InstallWebView2;
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
  Dir, Exe, Value: String;
  ResultCode: Integer;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  Dir := ExpandConstant('{app}');
  StopHuntsman(Dir);
  Exe := AddBackslash(Dir) + 'Huntsman.exe';
  if FileExists(Exe) then
    if Exec(Exe, '--remove-autostart', Dir, SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Log(Format('Huntsman.exe --remove-autostart exited with %d', [ResultCode]));
  { Fallback when that couldn't run: the Run value, if it still starts this copy. Another copy's is left alone. }
  if RegQueryStringValue(HKCU, RunKey, RunValue, Value) and
     (Pos(Lowercase(AddBackslash(Dir)), Lowercase(Value)) > 0) then
    if RegDeleteValue(HKCU, RunKey, RunValue) then
      Log('Removed the Run value ' + RunValue);
end;
