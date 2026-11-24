# HANDOFF

Current state of Huntsman for Mac, updated 2026-11-24.

## Status
- **0.6.0 (Windows installer) on branch `windows-installer`; PR to master and the v0.6.0 release still pending.**
  Plan docs/plans/2026-11-24-windows-installer.md. `Huntsman-for-Windows-<version>-Setup.exe` (Inno Setup, unsigned):
  Welcome → License (GPL) → folder → Install → Finish ("Open Huntsman for Mac"); per user, no admin, to
  `%LOCALAPPDATA%\Programs\Huntsman for Mac`, Start menu entry, Settings → Apps entry, optional desktop icon (off).
  Installs the WebView2 Runtime silently if missing. The zip stays as the portable option. Review fixes in the same
  branch: a quit while the service starts restores the lighting (Mac and Windows); `Api.studio_preview` never starts
  the service; after a quit `gui_ready` and `set_studio_enabled` do nothing / refuse (under `_life`, the same lock
  as start()); the tray's `run()` returns at once after `remove()`. Setup runs the helper, `--quit-service` and the
  restarted service as the original user (`ExecAsOriginalUser`: same account only, not another admin's); if the
  helper fails (PowerShell blocked, Constrained Language Mode exit 3, any error exit 1) it runs `--quit-service`
  directly (0.6+ only) and counts the service as running; the helper's marker line "lighting service was running:
  yes/no/unknown" decides the restart (unknown = running). Zip move: if the Run value starts another Huntsman.exe,
  Setup stops that copy and starts the installed service, whose `ensure_autostart` repoints the Run value.
- **0.6.0 CI evidence (GitHub's Windows runner, Windows Server 10.0.26100, run 45475092330, 2026-11-24):** silent
  install to the per-user folder without admin, Start menu and Settings → Apps entries; installed app's self-test
  passes; upgrade over a running lighting service stops it first and restarts it after; uninstall closes an open
  window, stops the service, removes files, Start menu entry and Run value, keeps %APPDATA%; WebView2 check ran and
  found the runtime; zip move with a 0.6 copy (its service stopped, the installed one running, Run value repointed).
  **Not verified (no real PC):** the wizard pages as a person sees them, SmartScreen (More info →
  Run anyway), the WebView2 bootstrapper actually installing on a PC without the runtime, the whole app with a
  keyboard.
- **Released v0.5.0 (2026-11-24, https://github.com/samir777-eng/huntsman-for-mac/releases/tag/v0.5.0; v0.5.0 = merge of
  PR #11 (e2b9196); plan docs/plans/2026-11-24-mac-pkg.md). Assets: `Huntsman-for-Mac-0.5.0.pkg` (build 8; the apps inside are signed with the project
  cert, checked) and `Huntsman-for-Windows-0.5.0.zip`, both attached by CI.**
  `Huntsman-for-Mac-<version>.pkg` (Apple silicon, macOS 14+), wizard Introduction → License (GPL) → Install (admin
  password) → done; installs `/Applications/Huntsman for Mac.app` with Python and libusb inside, the service as a
  nested full-copy `Huntsman Lighting.app`. Keyboard tab → **Uninstall…**. Service fix: requests that arrive while it
  starts wait for it (`service.START_WAIT`) instead of failing (seen on the first frozen build).
- **0.5.0 checked on the owner's Mac (V3 Pro, macOS 27.2, 2026-11-24, CI-built pkg whose apps are signed with the project cert):**
  the pkg moved the install.sh copy (`~/Applications/Huntsman for Mac.app`) to the Trash and switched the lighting
  service to the new app, settings kept; first launch set up the LaunchAgent, menu bar icon shows; lighting, actuation
  and the key tester work from the installed app; Input Monitoring for the key tester is listed as "Huntsman for Mac";
  installing a newer build over it kept that permission (no new prompt); Uninstall… removed the app, the service, its
  login item and the receipt, kept settings, keyboard back to typing with its own lighting; reinstall worked.
  Gatekeeper blocks the pkg on first open ("Apple could not verify … is free of malware", Move to Trash / Done). The
  owner did not get through System Settings → Open Anyway (found it frustrating); the install went through after
  `xattr -d com.apple.quarantine <pkg>`. Docs give Open Anyway as the macOS route (unchecked) plus that command.
- **Signing certificate (self-signed, valid to 2036-11-21; reuse it: a new cert changes the apps' designated
  requirement, so macOS permissions would likely reset):** GitHub secrets `MAC_SIGN_P12` / `MAC_SIGN_P12_PASSWORD`. Backup in the macOS Keychain:
  `security find-generic-password -s claude-mind/huntsman-mac-sign-p12 -w` and
  `security find-generic-password -s claude-mind/huntsman-mac-sign-p12-password -w`. Never paste the values anywhere.
- **Earlier:** v0.4.2 (2026-11-24): ⌘ ends the live view, notice buttons, Actuation gap, verified live-view results.
  v0.1.0–v0.4.2 are tagged. Media: `tools/make_media.py` remakes `docs/screenshot-actuation.png` and
  `docs/demo-key-tester.gif` from demo mode.
- **0.4.2 (PR #9, plan docs/plans/2026-11-24-live-view-fixes.md):** ⌘ (Windows key, LEFT_GUI) on
  the Huntsman ends live view from the stream thread (`depth_stream.LEAVE`, 0.5 mm); notice buttons are real buttons;
  the Actuation gap is gone.
- **Live view checked on the V3 Pro, 2026-11-24 (all pass):** click another window → types at once; back → live
  again; tab switch; lock screen; Input Monitoring off → notice + Open Privacy settings + Try again; 5-min pause +
  Resume; opens on the last tab; 0.4.2: ⌘ stops it, Cmd-Tab in one motion works, ⌘ held stops once, gap gone.
  Finding behind 0.4.2: in driver mode the Huntsman's own shortcuts (Cmd-Tab, Cmd-Q) never reach macOS.
- 0.4.0 checks done on the V3 Pro: window, menu bar, actuation, lighting, Studio after quit, key tester (2026-11-18);
  no-keyboard screen + Reconnect (2026-11-20); Mixed readout + Apply confirmation, Snap Tap switch/board picking,
  Studio preview while off, the 6 new presets (2026-11-22). The Windows build has still never run on a Windows PC
  with a keyboard.
- **Repo:** public, GitHub `samir777-eng/huntsman-for-mac`, default branch `master`, SEO description + 18 topics.
- **Tests:** 1592 passing (5 skipped) on the Mac: `python -m pytest -q tests` (simulated keyboard, fake transports,
  headless Chromium UI tests in demo mode). Dev env: `requirements.txt` + `requirements-dev.txt`, then
  `playwright install chromium`. GitHub Actions `CI` (.github/workflows/ci.yml) runs it on macos-latest and
  windows-latest (Windows: `requirements-win.txt`; 37 `mac_only` tests skipped, see tests/conftest.py).
- **Installed on the maintainer's Mac:** a CI-built 0.5.0 pkg, build 7, from branch `mac-pkg` at 3544c91 (2026-11-24), in /Applications;
  the install.sh copy went to the Trash. Note: AppleScript `quit app "Huntsman for Mac"`
  is ignored by the app; quit with Cmd-Q/menu or SIGTERM (restores typing).
- **CI stays on GitHub-hosted runners** (owner decision 2026-11-22): the repo is public, and fork PRs could run code on
  the self-hosted fleet; rule recorded in ~/Downloads/Projects/ci-monitor/fleet/README.md. Don't onboard it.

## What the product is
Unofficial macOS control app for the Razer Huntsman V3 Pro (USB 1532:02A6), which Razer Synapse for Mac doesn't
support. Since 0.3.0 six more models are detected as **experimental** (see Models below). Both parts live inside
one bundle: `/Applications/Huntsman for Mac.app` from the .pkg (0.5.0, PyInstaller, signed with the project cert), or
`~/Applications/Huntsman for Mac.app` from install.sh (source: copies the code and a `--copies` venv into the bundle
and signs it ad hoc; unsigned apps can't read ~/Downloads; developers and Intel Macs):
1. **The app** (`app.py` + `ui/`, pywebview): control panel with tabs Actuation, Rapid Trigger, Snap Tap, Lighting
   (keyboard's own effects + per-key paint), Studio, Keyboard (gear); the key tester is inside Actuation.
2. **The lighting service** "Huntsman Lighting" (`service.py`, nested `Contents/Library/LoginItems/Huntsman
   Lighting.app`, LaunchAgent `io.github.huntsman-for-mac.lighting`, RunAtLoad + KeepAlive SuccessfulExit=false):
   owns the menu bar icon and the Studio engine, so app-drawn effects keep running after the app quits. The app talks
   to it over `ipc.py` (UNIX socket `data_dir()/service.sock`, JSON lines, pause leases around every keyboard op).

## Models and features
- `models.py`: table of 7 models (PID, name, matrix, layout file, effects, features, status). Only 02A6 is
  `verified`. Experimental: V3 Pro TKL 02A7, V3 Pro 8KHz 02CF, V3 Pro Mini 02B0 (5×15), V2 026C, V2 TKL 026B (6×18),
  V2 Analog 0266 (8×23, frame size 74). V2/V2 TKL: lighting/per-key/Studio only. Key tester only on verified models.
- 0.4.0: V2 Analog gets experimental actuation on its own `models.Scale`
  (`V2_ANALOG_SCALE`: mm = thr/255×2.1+1.5, offered 1.62–3.56 mm = thr 15–250, 0.01 mm steps, release ≥5 and
  ≤ thr−10, reads show the firmware-clamped point; no factory point, so restore-factory refuses; snapshot works).
  V3 models use `V3_SCALE` (the old constants; golden bytes unchanged). `Model.info()["actuation"]` drives the UI
  slider/presets/reset/restore button. No Rapid Trigger/Snap Tap on the V2 Analog (host-side in Synapse).
  Tests: tests/test_v2_analog.py, UI in tests/test_ui_models.py. Plan: docs/plans/2026-11-18-v2-analog-actuation.md.
- 0.4.0: Windows build, step W1 "core" done (docs/plans/2026-11-18-windows.md):
  `platforms/` (selector, %APPDATA%/%LOCALAPPDATA% folders, fcntl/msvcrt locks, hidapi `HidTransport`), IPC
  endpoints (UNIX socket on the Mac, named pipe + authkey file on Windows), Windows gate (every model experimental,
  no key tester), `requirements-win.txt`. Nothing run on a Windows PC.
- 0.4.0: step W2 "front-end" done (same plan, "W2" section): shared menu model
  (`menubar.MenuState`, pystray `platforms/win_tray.py`), start at login via HKCU Run (`win_autostart.py`; the app
  starts the service itself), Raw Input typing reactions (`win_keys.py`), smart-lighting adapters
  (`win_smart.py`), Synapse guard + Dynamic Lighting notice (`win_guard.py`, `hc.SynapseRunning`), random pipe
  name + key in %LOCALAPPDATA%. Depth stream deliberately not implemented on Windows.
- 0.4.0: step W3 "packaging + CI" done (same plan, "W3" section):
  `packaging/windows/huntsman.spec` (PyInstaller one-folder `Huntsman.exe`, manifest `platforms/bundle.py`),
  `Huntsman.exe --version` / `--self-test`, workflow `Windows build` (dispatch, packaging pushes, release published →
  `Huntsman-for-Windows-<version>.zip` attached). Frozen self-test passes on windows-latest; nothing run on a real
  Windows PC with a keyboard. W4 docs done (README/landing Windows section, SmartScreen, CHANGELOG).
- Review fixes in 0.4.0: while Synapse runs nothing reaches the keyboard
  (`HidTransport` refuses to open/exchange, `hc.synapse_block()`, app/service drop handles, `Api.platform_status()`
  is the window's only poll, `model()` answers from the last model with `offline`); build workflow `contents: read`
  with a separate `release` job (tag minus v must equal the built version); V2 Analog "Just above" always uses
  `sc.release(thr)`; Windows start at login respects a removed Run value (`state.json["autostart_added"]`, re-added
  by Studio on); `win_window` per-start stop flag.
- Six more built-in Studio presets (0.4.0, CHANGELOG "Added"): Plasma, Starfield, Ripple, Spectrum bars, Sunset,
  Neon cycle, appended after the original eight in `lighting/presets.py` (never reorder: the active preset is stored by
  name; `golden_02a6.json` pins every preset's packets). `tests/test_site.py` checks the preset count on the page/README.
- UX audit batch A (CHANGELOG "Changed", plan docs/plans/2026-11-18-ux-audit-fixes.md): no-keyboard stage, Mixed
  depths + confirm before overwriting other depths, small-window depth labels on hover, sticky Apply, Studio preview
  while off (service composes frames only: `Studio.preview`/`Engine.preview`, IPC `studio_preview`), Save as… for
  built-ins. Batch B: Keyboard label on the gear, disabled key tester with the reason, one folded Synapse notice
  (lock note hidden while Synapse runs), Select bar only where selection applies + "Applying to N selected keys ·
  Clear", Snap Tap switch/Apply/dirty/board picking (same `set_snap`), 32 px layer buttons, Solid colour over layers
  Normal 50 %, "Onboard profile". Review fixes: the Apply confirm names only the keys that will change ("99 keys will
  change from 2.0 mm to 1.0 mm"; skipped when the scope is at one depth), no preset pressed while Mixed, Snap Tap pick
  order resets on leaving the tab/Reconnect, focus moves to the stage Reconnect when panes/board go inert, disabled Snap Tap
  button reads "Apply", `Studio._previewing` resets if the preview loop or its spawn raises. Hardware-checked 2026-11-22
  (actuation, Snap Tap, preview).
- Layouts: `layout.json` (02A6) + `layouts/<PID>.json`; LED positions for experimental models are guesses
  (reasoning in the models.py docstring) until testers send LED check results.
- Gate (`huntsman_core.gate`, `Keyboard.check_write`, `_check_command`): experimental models get reads only until
  `state.json["experimental"]` is on (Keyboard tab switch or `huntsman.py experimental on`); never driver mode;
  unknown commands refused. Golden-byte tests (`tests/golden_02a6.json`) pin every 02A6 packet.
- First-launch snapshot records its PID; restore refuses another model's snapshot. One snapshot per Mac user.
- Key tester lives in Actuation and runs live (0.4.1, plan
  docs/plans/2026-11-22-live-key-tester.md): no button; starts while Actuation is in front, stops on tab/app change,
  hidden, close, disconnect, 5 min idle. UX-audit fixes: opens on the last tab (state.ui.tab; first launch Lighting),
  one-time intro (state.ui.liveSeen), stable layout with a Resume chip, `Api.open_privacy`. Media:
  `tools/make_media.py` regenerates the Actuation screenshot and key-tester gif (fake clock, WASD at 1.2 mm). Checked
  on the keyboard 2026-11-24. 0.4.2: ⌘ (LEFT_GUI ≥ 0.5 mm) ends it; window holds it off ({cmd, left}) until Resume or
  refocus after leaving; `StillInDriverMode` abandons the lease when start()'s switch-back fails.

## Code map
- `huntsman_core.py`: protocol + USB transport (pyusb/libusb control transfers to interface 3, 90-byte reports, CRC,
  process + file USB lock, fast frame path `exchange_fast`/`send_frame_fast`, `DeviceBusy`, `__version__`).
- `depth_stream.py`: key tester (driver mode + IOKit report 0x0B), `recover_typing`, signal/shutdown hooks.
- `lighting/`: engine (frame streaming, busy-skip, back-off), 17 app-drawn effects, layers/blends, presets.
- `inputs/`: key listener (IOKit page-7 values), audio (sounddevice + numpy, 16 bands), smart lighting rules.
- `studio.py` Studio controller · `service.py` lighting service · `ipc.py` socket · `menubar.py` status menu.
- `app.py`: pywebview Api (actuation, firmware lighting, key tester, Studio proxy) · `huntsman.py`: CLI.
- `ui/`: index.html, style.css, app.js, studio.js, demo.js (+ generated demo-layout.js / demo-studio.js via
  `tools/make_demo_layout.py` / `tools/make_demo_studio.py`; tests fail if stale). `ui/index.html?demo` = no hardware.
- Mac installer (0.5.0): `packaging/mac/` (`huntsman-mac.spec` two PyInstaller apps; `plists.py` frozen Info.plists,
  LSMinimumSystemVersion 14.0; `service_entry.py`; `pkg/` distribution.xml, welcome/conclusion, preinstall stops the
  window + service, postinstall trashes the install.sh copy and repoints/restarts an existing LaunchAgent).
  `tools/build_mac_pkg.sh build|package|all` (build without secrets; package signs, verifies, self-tests, pkgs).
  `.github/workflows/mac-build.yml` (GitHub-hosted macos-15 arm64; cert into a temp keychain only for the package
  phase; installs the pkg on the runner and self-tests from /Applications; release job attaches
  `Huntsman-for-Mac-<version>.pkg`, tag must equal the version; a release never ships ad hoc).
  `requirements-mac-build.txt`. Frozen-only code paths (`sys.frozen`): `huntsman_core.libusb_path()` (bundled libusb
  first), `app.start_service` writes/bootstraps the LaunchAgent if missing or stale, `service.open_app` via bundle id,
  log redirection to `~/Library/Logs/Huntsman for Mac.log`, `app.uninstall_mac` (osascript admin `rm -rf` +
  `pkgutil --forget io.github.huntsman-for-mac.pkg`; `platform_status()["can_uninstall"]` only for the
  /Applications copy), `--version` / `--self-test` on both executables. No `huntsman.py` CLI in the pkg app.
  Tests: tests/test_mac_frozen.py, tests/test_mac_packaging.py.
- Windows installer (0.6.0): `packaging/windows/huntsman.iss` (Inno Setup; fixed AppId GUID, never change it;
  `PrivilegesRequired=lowest`; x64, Windows 10+; WebView2 registry check + bundled Evergreen bootstrapper, downloaded by
  CI, never committed; keep the file ASCII). `packaging/windows/setup-helper.ps1` (run hidden by the installer; paths
  as hex-encoded arguments, 4 hex digits per UTF-16 unit, not env vars: those don't reach `ExecAsOriginalUser`):
  `stop` closes the exe's windows, runs `Huntsman.exe --quit-service` (30 s limit), ends what's left of that exact
  exe, writes "lighting service was running: yes/no/unknown", exit 10 = was running (or unknown); exit 3 outside
  FullLanguage mode, exit 1 on any error (trap), so the installer's fallback runs. `webview2` runs the bootstrapper
  `/silent /install` (10 min limit).
  `app.py`: `--quit-service` (`stop_running_service`: IPC "quit", waits for the instance lock; exit 0 = none was
  running, 4 = stopped one, 1 = still running), `--remove-autostart`
  (`win_autostart.remove_if_ours`, resets `autostart_added`). `service.py`: "quit" request calls the tray's quit.
  `.github/workflows/windows-build.yml`: Inno Setup **6.7.1** via choco (pinned; version checked through
  `choco list`, ISCC.exe has no file version), then a smoke test: install, `--version`/`--self-test` from the install
  folder, reinstall over a running service, uninstall with a window open, asserts files/shortcut/Run value gone and
  %APPDATA% kept. In PowerShell, `Start-Process -Wait` waits for the whole process tree (it would hang on the service
  an upgrade restarts): use `$p.WaitForExit()` for Setup.exe. Release job attaches the Setup.exe next to the zip.
  Tests: tests/test_win_installer.py.
- Data: `~/Library/Application Support/Huntsman for Mac/` (state.json, presets.json, heatmap.json,
  first-launch-snapshot.json, *.lock, service.sock). Log: `~/Library/Logs/Huntsman for Mac.log`.

## Packaging facts (0.5.0, 0.6.0)
- macOS Installer skips a bundle whose installed `CFBundleVersion` is the same as the pkg's, so bump
  `CFBundleVersion` in both `packaging/Info.plist` and `packaging/Lighting-Info.plist` for every release and every
  test build you install over another, and whenever the version changes (also for a Windows-only release).
  Currently **9** (0.6.0; v0.5.0 shipped 8, the maintainer's Mac has test build 7). `CFBundleShortVersionString` must equal `__version__`
  (`plists.mac_info` checks).
- Both bundles are `BundleIsRelocatable = false` (else Installer "upgrades" the ~/Applications copy in place).
- arm64 only (cffi/numpy/libusb wheels); min macOS 14.0 (numpy wheel). install.sh keeps 12.0.
- Windows: setup-helper.ps1 sends `--quit-service` only to an installed exe of 0.6.0 or later (file version); an
  older exe would open its window instead, so older copies are just ended.
- A self-signed cert gives a stable designated requirement, so TCC grants survive updates (seen: Input Monitoring kept).

## Protocol facts (verified on hardware, V3 Pro firmware 1.03)
- Actuation = byte 3, release = byte 4 of 02:12/02:92 (release = actuation − 6, min threshold 7, factory 76/70).
  Writes go to the active saved profile first, then live profile 0.
- Rapid Trigger 02:1A, continuous 02:20, Snap Tap 02:21: ON goes to live profile only (service re-sends at start).
- Firmware effects 0F:02: static, breathing ×3, spectrum, wave, reactive ×2, starlight ×3. **Fire (09) is refused
  (status 03); effect 06 ("ripple") only lights pressed keys in random colours.** Both removed from the app.
- Per-key frame 0F:03 rows 0–5, cols 0–21, size 0x47, then [0,0,8] size 0x0C; ~290 fps with immediate polling.
  While the user types, frames can stay busy (status 01) → skipped (`DeviceBusy`), reported only after ~1 s.
- Gamma 2.2 matches the colour picker. Restores use store 0 (RAM), never rewriting flash.
- Driver mode 00:04 [3,0] streams report 0x0B (u16 BE, 16380 units/mm); back with [0,0]. SIGTERM and reconnect
  both restore typing. Normal typing is visible as HID page-7 values with Input Monitoring.

## Verified by the owner on hardware (0.3.0 on 02A6, 2026-11-17/18)
Window (no badge/switch, all tabs), actuation, Rapid Trigger + Snap Tap, firmware effect + per-key paint +
brightness, Studio typing + ambient + after quit, key tester in Actuation with typing back. Other models: none.

## Verified by the owner on hardware (2026-11-17)
Actuation (selection, presets, reset point, live meter), Rapid Trigger, Snap Tap, firmware lighting + per-key paint +
brightness, key tester, Studio presets (rainbow, aurora, matrix, fire, typing glow, gaming WASD, music via microphone),
Studio layers/params/presets/Sound/Typing/Smart panels, effects continuing after the app quits.

## Not yet verified
- Windows installer (0.6.0) on a real PC: wizard pages, SmartScreen, WebView2 bootstrapper on a PC without the
  runtime (CI only had it already), upgrade/uninstall outside CI. Also unverified: Setup run as administrator,
  PowerShell blocked (the fallback path), moving from a real 0.5 zip copy, a fresh install while a zip copy's
  service runs. Note: when PowerShell is blocked, the uninstall fallback only asks the service to quit; it doesn't
  close an open window (Windows' Restart Manager may still close it).
- macOS permission name for the service ("Huntsman Lighting") for Microphone and Input Monitoring, in the pkg app and
  install.sh copies. In an install.sh copy the key tester's Input Monitoring is held by the Python binaries (bundle
  venv `python`, Homebrew `python3.13`), not the bundle id (TCC.db, 2026-11-24), so `tccutil reset ListenEvent
  io.github.huntsman-for-mac` does nothing there; the pkg app is listed as "Huntsman for Mac" (2026-11-24).
- Gatekeeper's Open Anyway path for the pkg (owner didn't get through it; xattr worked).
- pkg install with several users logged in: another user's lighting service isn't stopped (known limitation).
- Lighting restore at logout/shutdown; KeepAlive restart after a crash; install.sh rollback after a failed build.
- Smart lighting over a long session (real sleep/lock); BlackHole/system-audio input.
- All six experimental models (no tester reports yet), incl. LED positions and the 8KHz profile read (05:84).
- V2 Analog actuation (0.4.0): scale, 1.62 mm end, release rule, Hypershift-layer depth left alone (from easyrazer).
- Intel Macs, macOS < 26.

## Decisions (don't re-raise)
- Name stays "Huntsman for Mac"; discoverability via README/FAQ/topics, not a rename.
- Owner's personal email is fine in commits and SECURITY.md.
- No Razer logos/assets/code copied; Synapse look and flow only. Default accent ice #6ad7ff.
- Hardware testing with the owner: one item at a time, multiple-choice questions.
- Workflow per feature: plan in docs/plans/, tests first, Opus implementers, independent Opus review, hardware test
  with the owner, then merge to master and release.

## Next (pick with the owner)
(Done 2026-11-24) v0.5.0 released with the pkg attached. The maintainer's Mac runs test build 7; installing the
   release pkg (build 8) over it is optional.
0. Merge the `windows-installer` PR and release v0.6.0 (Setup.exe + zip + pkg attached by CI).
0a. Apple Developer ID + notarization (owner decision, $99/yr) to remove the Gatekeeper block on the pkg; pending the
    owner's enrolment.
0b. A real Windows PC check, now covering the installer too: wizard pages, SmartScreen, WebView2 install on a PC
    without it, upgrade/uninstall, and the app with a Huntsman (never run yet).
(Done 2026-11-24) Live-view hardware check; fixes shipped as 0.4.2.
0c. (Done in 0.4.2) Actuation gap; media regenerated. Minor, open: AppleScript quit is ignored by the app.
1. (Done 2026-11-18) GitHub social preview set to `docs/social-preview.png` (1280×640, from the README banner).
2. (Done 2026-11-18) Landing page live at https://samir777-eng.github.io/huntsman-for-mac/ (GitHub Pages, master
   /docs, `docs/index.html`; tests in tests/test_site.py). Keep its facts in step with the README.
3. Collect tester reports for the experimental models (issue template new_model.md); promote a model to `verified`
   in models.py only after a tester confirms it, and fix its LED map from the LED check.
4. Work through "Not yet verified".

## Plan records
- docs/plans/2026-11-17-open-source-release.md (v0.1.0)
- docs/plans/2026-11-17-v2-lighting-studio.md (v0.2.0)
- docs/plans/2026-11-17-v3-more-models.md (v0.3.0)
- docs/plans/2026-11-18-landing-page.md (GitHub Pages)
- docs/plans/2026-11-18-windows.md, 2026-11-18-v2-analog-actuation.md, 2026-11-18-ux-audit-fixes.md (v0.4.0)
- docs/plans/2026-11-22-live-key-tester.md (v0.4.1)
- docs/plans/2026-11-24-live-view-fixes.md (v0.4.2)
- docs/plans/2026-11-24-mac-pkg.md (v0.5.0)
- docs/plans/2026-11-24-windows-installer.md (v0.6.0)
