# 0.6.0: Windows installer wizard (Inno Setup)

## Baseline (2026-11-24)
- master = v0.5.0. Windows ships `Huntsman-for-Windows-<version>.zip`: a PyInstaller one-folder build
  (packaging/windows/huntsman.spec → `dist\Huntsman\Huntsman.exe`; `--service` runs the lighting service,
  `--version`/`--self-test` the smoke test). The user unzips it anywhere and runs Huntsman.exe; opening the app adds the
  HKCU Run value `Huntsman for Mac lighting` = `"<folder>\Huntsman.exe" --service` (platforms/win_autostart.py).
  Settings in `%APPDATA%\Huntsman for Mac\`. The window needs the Microsoft Edge WebView2 Runtime (built into
  Windows 11; may be missing on Windows 10).
- The Windows build has never run on a real Windows PC with a keyboard (only CI). That stays true after this change.

## Problem
Users must unzip by hand, may hit a missing WebView2 with no help, get no Start menu entry, and have no uninstaller
(the Run value stays behind). The owner wants a normal wizard: Next → License → Install → Finish.

## Decisions (owner, 2026-11-24)
- Inno Setup wizard, unsigned (SmartScreen "More info → Run anyway" accepted).
- WebView2: installed automatically if missing (Microsoft's Evergreen bootstrapper inside the installer).
- The zip stays on releases. CI on GitHub-hosted windows runners only (public repo, never the fleet).

## Design
- `packaging/windows/huntsman.iss`: per-user install, no admin (`PrivilegesRequired=lowest`), to
  `{localappdata}\Programs\Huntsman for Mac` (HKCU Run and per-user data already need no admin). Pages: Welcome →
  License (GPL) → (Select folder) → Install → Finish with "Open Huntsman for Mac". Start menu shortcut (desktop icon
  optional task, off by default). AppId fixed (GUID) so upgrades replace in place; version from `__version__`;
  x64 only (the build is x64); minimum Windows 10.
- WebView2: bundle `MicrosoftEdgeWebview2Setup.exe` (Evergreen bootstrapper, downloaded in CI from Microsoft's fwlink,
  never committed) and run it `/silent /install` only when the runtime is missing (registry check of the
  EdgeUpdate client key `{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`, HKLM WOW6432Node and HKCU, `pv` not empty/0.0.0.0).
  A failure doesn't fail the install; the Finish page/README say how to get it.
- Upgrade/uninstall: before installing or uninstalling, stop running Huntsman.exe processes of that install
  (the service restores the keyboard's lighting on a normal stop; implementer finds/adds the cleanest stop, e.g. a
  `--quit-service` command over the existing IPC, falling back to closing the processes). Uninstall removes the
  program files, the Start menu entries and the HKCU Run value `Huntsman for Mac lighting`; settings in %APPDATA%
  are kept (said on the uninstall confirmation).
- Run-key path: after install the app's own `ensure_autostart` points the Run value at the installed exe (existing
  behaviour; check it repoints an old zip-folder value).
- CI (`.github/workflows/windows-build.yml`): after the PyInstaller build, fetch the bootstrapper, compile with
  Inno Setup (preinstalled on windows-latest or installed with choco; pinned), smoke-test: silent install
  (`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`), `--version`/`--self-test` from the install folder, silent uninstall,
  assert files + Run value gone and %APPDATA% kept. Upload and attach `Huntsman-for-Windows-<version>-Setup.exe` to
  releases next to the zip.

## Tests first
- pytest (run on Mac and Windows CI): .iss static checks (AppId fixed, PrivilegesRequired=lowest, per-user dir,
  license, version source, WebView2 check + silent bootstrapper, Run-value removal on uninstall, %APPDATA% not
  deleted, x64, Windows 10 minimum); workflow checks (hosted runner only, bootstrapper downloaded not committed,
  silent install/uninstall smoke test, release attach with tag == version).
- Any new Python (e.g. `--quit-service`): unit tests with fakes, both platforms.

## Not possible here
No Windows PC: the wizard pages, SmartScreen, WebView2 install on a Windows 10 without it, the tray icon and the
keyboard are unchecked on hardware. Docs say so; CI evidence only.

## Docs
README Windows install (Setup.exe first, zip as portable), uninstall, CHANGELOG 0.6.0, HANDOFF, landing page.

## Rollback
The zip stays; a bad Setup.exe is removed from the release.
