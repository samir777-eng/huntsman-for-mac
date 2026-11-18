# HANDOFF

Current state of Huntsman for Mac, updated 2026-11-18.

## Status
- **Released:** v0.3.0 "More models" (https://github.com/samir777-eng/huntsman-for-mac/releases/tag/v0.3.0).
  v0.1.0 and v0.2.0 are also tagged. `master` = v0.3.0 (merge of branch `v3-models`, kept for history).
- **Repo:** public, GitHub `samir777-eng/huntsman-for-mac`, default branch `master`, SEO description + 18 topics.
- **Tests:** 972 passing: `python -m pytest -q tests` (simulated keyboard, fake transports, headless Chromium UI
  tests in demo mode). Dev env: `requirements.txt` + `requirements-dev.txt`, then `playwright install chromium`.
- **Installed on the maintainer's Mac** from `master` via `./install.sh`; app + lighting service running.

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

## Models (0.3.0)
- `models.py`: table of 7 models (PID, name, matrix, layout file, effects, features, status). Only 02A6 is
  `verified`. Experimental: V3 Pro TKL 02A7, V3 Pro 8KHz 02CF, V3 Pro Mini 02B0 (5×15), V2 026C, V2 TKL 026B (6×18),
  V2 Analog 0266 (8×23, frame size 74). V2 family: lighting/per-key/Studio only. Key tester only on verified models.
- Layouts: `layout.json` (02A6) + `layouts/<PID>.json`; LED positions for experimental models are guesses
  (reasoning in the models.py docstring) until testers send LED check results.
- Gate (`huntsman_core.gate`, `Keyboard.check_write`, `_check_command`): experimental models get reads only until
  `state.json["experimental"]` is on (Keyboard tab switch or `huntsman.py experimental on`); never driver mode;
  unknown commands refused. Golden-byte tests (`tests/golden_02a6.json`) pin every 02A6 packet.
- First-launch snapshot records its PID; restore refuses another model's snapshot. One snapshot per Mac user.
- Key tester lives in Actuation ("Test with a key press"); the Key tester tab is gone.

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
- Intel Macs, macOS < 26.

## Decisions (don't re-raise)
- Name stays "Huntsman for Mac"; discoverability via README/FAQ/topics, not a rename.
- Owner's personal email is fine in commits and SECURITY.md.
- No Razer logos/assets/code copied; Synapse look and flow only. Default accent ice #6ad7ff.
- Hardware testing with the owner: one item at a time, multiple-choice questions.
- Workflow per feature: plan in docs/plans/, tests first, Opus implementers, independent Opus review, hardware test
  with the owner, then merge to master and release.

## Next (pick with the owner)
1. (Done 2026-11-18) GitHub social preview set to `docs/social-preview.png` (1280×640, from the README banner).
2. Optional GitHub Pages landing page for search visibility.
3. Collect tester reports for the experimental models (issue template new_model.md); promote a model to `verified`
   in models.py only after a tester confirms it, and fix its LED map from the LED check.
4. Work through "Not yet verified".

## Plan records
- docs/plans/2026-11-17-open-source-release.md (v0.1.0)
- docs/plans/2026-11-17-v2-lighting-studio.md (v0.2.0)
- docs/plans/2026-11-17-v3-more-models.md (v0.3.0)
