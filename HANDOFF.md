# HANDOFF

Current state of Huntsman for Mac, updated 2026-11-24.

## Status
- **Released:** v0.4.1 (2026-11-23, https://github.com/samir777-eng/huntsman-for-mac/releases/tag/v0.4.1): the live
  key tester ("live view", no Test button) plus its UX-audit and review fixes. `Huntsman-for-Windows-0.4.1.zip` is
  attached by `.github/workflows/windows-build.yml`. `master` = v0.4.1 (merge of branch `auto-key-tester`).
  v0.1.0–v0.4.0 are also tagged. Media: `tools/make_media.py` remakes `docs/screenshot-actuation.png` and
  `docs/demo-key-tester.gif` from demo mode.
- **Released at the owner's go-ahead before the live view was checked on the keyboard.** Still to check on the V3 Pro:
  start/stop as the real window comes to the front or goes behind (Cmd-Tab must bring typing back at once), screen
  lock, the Input Monitoring prompt, the 5-minute pause + Resume, opening on the last tab. Record verified results in
  README/CHANGELOG/HANDOFF; fix anything found in a 0.4.2.
- 0.4.0 checks done on the V3 Pro: window, menu bar, actuation, lighting, Studio after quit, key tester (2026-11-18);
  no-keyboard screen + Reconnect (2026-11-20); Mixed readout + Apply confirmation, Snap Tap switch/board picking,
  Studio preview while off, the 6 new presets (2026-11-22). The Windows build has still never run on a Windows PC
  with a keyboard.
- **Repo:** public, GitHub `samir777-eng/huntsman-for-mac`, default branch `master`, SEO description + 18 topics.
- **Tests:** 1372 passing (2 skipped) on the Mac: `python -m pytest -q tests` (simulated keyboard, fake transports,
  headless Chromium UI tests in demo mode). Dev env: `requirements.txt` + `requirements-dev.txt`, then
  `playwright install chromium`. GitHub Actions `CI` (.github/workflows/ci.yml) runs it on macos-latest and
  windows-latest (Windows: `requirements-win.txt`; 37 `mac_only` tests skipped, see tests/conftest.py).
- **Installed on the maintainer's Mac:** branch `auto-key-tester` at 7dc0f58, before the version bump aa00a64
  and the wording fix 88ab285 (About still says 0.4.0). Reinstall from `master` (quit the app, `./install.sh`) before the live-view
  hardware check.
- **CI stays on GitHub-hosted runners** (owner decision 2026-11-22): the repo is public, and fork PRs could run code on
  the self-hosted fleet; rule recorded in ~/Downloads/Projects/ci-monitor/fleet/README.md. Don't onboard it.

## What the product is
Unofficial macOS control app for the Razer Huntsman V3 Pro (USB 1532:02A6), which Razer Synapse for Mac doesn't
support. Since 0.3.0 six more models are detected as **experimental** (see Models below). Both parts live inside `~/Applications/Huntsman for Mac.app` (install.sh copies the code and a `--copies`
venv into the bundle and signs it ad hoc; unsigned apps can't read ~/Downloads):
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
  `tools/make_media.py` regenerates the Actuation screenshot and key-tester gif (fake clock, WASD at 1.2 mm). Not yet
  checked on the keyboard (pywebview focus/blur untested).

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
- Data: `~/Library/Application Support/Huntsman for Mac/` (state.json, presets.json, heatmap.json,
  first-launch-snapshot.json, *.lock, service.sock). Log: `~/Library/Logs/Huntsman for Mac.log`.

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
- macOS permission prompt names for the service ("Huntsman Lighting" vs "Python").
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
0. **Live-view hardware check on the V3 Pro** (released unchecked in 0.4.1), one item at a time, after reinstalling
   from master: Cmd-Tab away → typing back at once (most important); back → live again; switching tab → typing;
   screen lock; Input Monitoring prompt (Deny → notice + Open Privacy settings + Try again); 5-minute pause + Resume
   chip; opens on the last tab. Record verified results in README ("Version 0.4.1" paragraph), CHANGELOG 0.4.1 "Not
   checked on hardware", HANDOFF. Anything failing → fix in 0.4.2 (same workflow).
0b. Windows build on a real Windows PC with a Huntsman (never run yet).
0c. Cosmetic: empty gap in the Actuation panel between the live status line and "Last key" (see
    docs/screenshot-actuation.png).
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
