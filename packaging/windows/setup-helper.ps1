# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
#
# Run hidden by the Windows installer (packaging/windows/huntsman.iss), never by hand. Paths come in environment
# variables (no quoting on a command line); what happened is written, one line each, to $env:HUNTSMAN_SETUP_LOG,
# which the installer copies into its own log. Keep this file ASCII.
#
#   stop      Stop the copy $env:HUNTSMAN_EXE (an upgrade or an uninstall), in this order:
#             1. close its windows: an open window (the Studio tab asks the service for a preview every few
#                seconds) could start the lighting service again;
#             2. ask its lighting service to quit (Huntsman.exe --quit-service, 0.6.0 and later only: an older exe
#                would open its window instead), so it restores the keyboard's own lighting; with a time limit;
#             3. end whatever of that exact exe is still running.
#             Exit 10 when its lighting service was running (the installer starts it again after an upgrade),
#             else 0.
#   webview2  Run Microsoft's WebView2 bootstrapper $env:HUNTSMAN_WEBVIEW2 /silent /install, at most 10 minutes.
#             Exit with its exit code, 1460 (ERROR_TIMEOUT) when it was ended.
param([Parameter(Mandatory = $true)][ValidateSet('stop', 'webview2')][string]$Action)

$log = $env:HUNTSMAN_SETUP_LOG
function Say([string]$Line) {
  if ($log) { Add-Content -LiteralPath $log -Value $Line -Encoding UTF8 }
}

function Ours([string]$exe) {
  @(Get-CimInstance -ClassName Win32_Process -Filter "Name = 'Huntsman.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath -eq $exe })
}

if ($Action -eq 'stop') {
  $exe = $env:HUNTSMAN_EXE
  if (-not $exe -or -not (Test-Path -LiteralPath $exe)) { Say 'nothing installed there'; exit 0 }
  $running = Ours $exe
  $service = @($running | Where-Object { $_.CommandLine -match '(^|\s)--service(\s|$)' })
  $windows = @($running | Where-Object { $_.CommandLine -notmatch '(^|\s)--service(\s|$)' })
  Say ('lighting service was running: ' + $(if ($service.Count) { 'yes' } else { 'no' }))

  foreach ($w in $windows) {
    $p = Get-Process -Id $w.ProcessId -ErrorAction SilentlyContinue
    if ($p) { [void]$p.CloseMainWindow() }
  }
  foreach ($w in $windows) {
    $p = Get-Process -Id $w.ProcessId -ErrorAction SilentlyContinue
    if ($p -and -not $p.WaitForExit(10000)) { Say ('window did not close: ' + $w.ProcessId) }
  }
  Say ('windows closed: ' + $windows.Count)

  $vi = (Get-Item -LiteralPath $exe).VersionInfo
  $version = [version]::new($vi.FileMajorPart, $vi.FileMinorPart, $vi.FileBuildPart)
  if ($version -ge [version]'0.6.0') {
    $q = Start-Process -FilePath $exe -ArgumentList '--quit-service' -PassThru
    $null = $q.Handle
    if ($q.WaitForExit(30000)) {
      Say ('--quit-service exited with ' + $q.ExitCode)
    } else {
      Stop-Process -Id $q.Id -Force -ErrorAction SilentlyContinue
      Say '--quit-service timed out'
    }
  } else {
    Say ('--quit-service skipped: version ' + $version + ' does not have it')
  }

  $left = Ours $exe
  foreach ($p in $left) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
  Say ('ended: ' + $left.Count)
  if ($service.Count) { exit 10 }
  exit 0
}

if ($Action -eq 'webview2') {
  $p = Start-Process -FilePath $env:HUNTSMAN_WEBVIEW2 -ArgumentList '/silent', '/install' -PassThru
  $null = $p.Handle
  if (-not $p.WaitForExit(600000)) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Say 'WebView2 bootstrapper ended after 10 minutes'
    exit 1460
  }
  Say ('WebView2 bootstrapper exited with ' + $p.ExitCode)
  exit $p.ExitCode
}
