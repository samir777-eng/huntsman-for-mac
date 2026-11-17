# HANDOFF

Current state of Huntsman for Mac (updated 2026-11-17). Version 0.1.0 published; v2 (0.2.0, Lighting Studio) in progress on branch `v2`, not committed.

## v2 Lighting Studio (branch v2, plan docs/plans/2026-11-17-v2-lighting-studio.md; menu bar, hide-on-close and login-item notes below are superseded by the lighting service section below)
- Parts A (lighting/ engine, effects, layers, presets, core fast path), B (inputs/ keys, audio, smart; menubar.py) and
  C (integration) are implemented. C added: `studio.py` (controller), Studio API in `app.py`, background launch + menu
  bar in `app.main`, `ui/studio.js` + Studio tab, demo simulation (`ui/demo.js`, generated `ui/demo-studio.js` via
  `tools/make_demo_studio.py`), installer/plist/requirements changes, README/CHANGELOG.
- Tests: `~/Documents/huntsman-control/venv/bin/python -m pytest -q tests` → 472 passed (fakes + headless Chromium).
- Verified on hardware: only the spike numbers (per-key frame 294 fps with immediate reply polling; IOKit page-7
  key events during normal typing).
- NOT verified on hardware / real macOS (all of v2): engine streaming at 30 fps through the app, pausing for other
  device calls, restore on Studio off/quit (incl. the raw re-send of the stored effect when state.json has no effect),
  typing reactions and Input Monitoring prompt for the bundle, Microphone prompt (NSMicrophoneUsageDescription) and
  sound input incl. BlackHole, smart lighting (idle/sleep/lock/front app), menu bar icon, hidden-window close
  (pywebview 6.2.1 `closing` runs on the main thread and False cancels: read from its source, not exercised),
  accessory/regular activation policy switching, login item via `open -g -a ... --args --background`, install.sh
  copying lighting/, inputs/, studio.py, menubar.py, ui/studio.js.
- Review fixes (v2, uncommitted, not yet on hardware/real macOS): only the red close button hides to the menu bar;
  Cmd-Q / Quit menu / logout / power-off set `quitting` via a subclass of pywebview's AppDelegate
  (`app.install_app_hooks`) plus NSWorkspaceWillPowerOffNotification, so `closing` lets the quit through; reopening
  the app shows the window (applicationShouldHandleReopen); SIGTERM/SIGHUP run `api.shutdown` (2 s limit) before
  exit; Studio restores lighting to RAM (store 0), never flash; a failed key-test start resumes the engine, a failed
  switch-back keeps it paused until reconnect; smart notifications and window updates never block on locks
  (lock order in studio.py). install.sh no longer starts the login item; it opens the app at the end.
  Heat counts are saved on Studio off/quit/SIGTERM only (a crash loses the session's counts).

## v2 lighting service (branch v2, uncommitted, 2026-11-17) — NOT verified on hardware or real macOS
- Owner requirement: Studio effects keep running after the app quits (like Synapse's service). `service.py` is the
  lighting service ("Huntsman Lighting", accessory NSApplication, menu bar icon now lives here with "Quit lighting
  service"); it hosts Studio (engine, key/audio listeners, smart lighting), single instance (flock service.lock),
  re-sends RAM-only settings at start (replaces apply-saved), restores firmware lighting to RAM on quit/SIGTERM/logout.
- `ipc.py`: UNIX socket `data_dir()/service.sock` (0600, same-uid peers, 2 MiB lines, NaN refused, typed args per
  command in `service.SPECS`), JSON-lines request/reply plus an event stream (newest event per name; frames ~15 fps
  only to subscribers that ask). Pause leases: `pause(lease_seconds 0.5–30[, token])` / `resume(token)`, max 16; the
  app holds a 5 s lease renewed every 2 s around every keyboard operation and for the whole key test; on expiry the
  service runs recover_typing before resuming; restores requested while leased wait for the last lease.
- `app.py` is the control panel: Studio methods proxy through `ServiceLink` (starts the agent with
  `launchctl kickstart -k`, bootstrapping its plist if needed, clear error otherwise); live preview from the
  subscription via JsPusher (event names whitelisted). No menu bar, hide-to-menu-bar, dock-policy or AppDelegate hooks
  any more: closing the window quits.
- Packaging: `Huntsman for Mac.app/Contents/Library/LoginItems/Huntsman Lighting.app` (packaging/Lighting-Info.plist,
  LSUIElement, mic/input reasons, exec's the bundled venv python on service.py), signed by the outer --deep ad-hoc
  sign. LaunchAgent `io.github.huntsman-for-mac.lighting` (RunAtLoad, KeepAlive SuccessfulExit=false, Aqua,
  Interactive), bootstrapped by install.sh (3 tries); install.sh boots the service out before replacing files, removes
  the old apply-saved agent, re-bootstraps the previous service on rollback; uninstall.sh boots out and removes both.
- Tests: 548 passed (`~/Documents/huntsman-control/venv/bin/python -m pytest -q tests`).
- Verify on real macOS/hardware: install.sh end to end (bootstrap right after bootout, nested app signature
  `codesign --verify --deep --strict`), menu bar icon from the service, Studio surviving app quit, Quit lighting service
  restores lighting and stays quit (exit 0), crash restart (KeepAlive), TCC prompts attributed to "Huntsman Lighting"
  (the bundle exec's a python binary from the outer bundle; attribution may instead show Python), smart lighting
  notifications in the accessory app, logout restore, lease timing during long operations and the key tester, app
  starting the service via kickstart, LOCAL_PEERCRED peer check (works in tests), socket path length (< 104 bytes).

## Done
- First version: clean open-source repo, installer, GPL-3.0, Synapse-style interface, live key tester.
- Full audit (7 auditors: keyboard safety, security, concurrency, accessibility, design, docs/licensing, tests), fixed in three batches:
- Audit batch 1: keyboard safety (CRC-checked replies, saved-before-live writes, driver-mode recovery on connect, SIGTERM stop, file locks shared with the login item and CLI, input validation).
- Audit batch 2: accessible, livelier interface (keyboard-operable key grid, contrast-correct accent text, live effect previews, testing banner).
- Audit batch 3: open-source readiness. UI smoke tests (Playwright, demo mode), demo-layout and licence-header checks, installer hardening (quarantine strip, ad-hoc signing, running-app check, escaped plist and launcher paths, Python 3.13→3.11 preference with an "untested" note for 3.14+, venv built with --copies so the ad-hoc signature verifies, rollback to the previous app if the build fails), pinned requirements, requirements-dev.txt, SPDX headers, NOTICE, CONTRIBUTING, SECURITY, CHANGELOG, issue templates, `__version__` (CLI `--version`, Keyboard pane), progress bar, README rewrite.
- Tests: `python -m pytest -q tests` (simulated keyboard + headless Chromium), all green.

## Verified on hardware (Huntsman V3 Pro 1532:02A6, firmware 1.03, macOS 26, Apple silicon, 2026-11-17)
- Actuation and release write, read-back, persist after replug; release follows actuation − 6 units.
- Lighting: static effect and brightness, persist on the keyboard.
- Per-key colour frame (0F:03, rows 0–5, cols 0–21, size 0x47; then effect [0,0,8] size 0x0C).
- Colour correction (gamma 2.2) matches the picker (visual check on hardware).
- Driver mode (00:04 [3,0]) streams report 0x0B; switching back (00:04 [0,0]) confirmed.
- SIGTERM during a key test: keyboard returns to typing (exit 143).
- Keyboard left in driver mode: recovered automatically on the next connect.
- CRC-checked replies and saved-before-live writes on hardware.
- Installed .app opens and reads the keyboard.
- New installer (2026-11-17): real re-install ran, quarantine stripped, ad-hoc signed bundle passes `codesign --verify --strict --deep`, app opens and connects.

## Not yet verified
- Rapid Trigger ON, Snap Tap ON (protocol from easyrazer; only OFF was seen accepted).
- Key tester inside the installed .app (Input Monitoring grant for the bundled Python).
- install.sh rollback after a failed build on a real install (checked only in a scratch script).
- Other models, Intel Macs, macOS < 26, SIGKILL during a test (relies on reconnect recovery, which is verified).

## Layout
- `huntsman_core.py` protocol/transport, `depth_stream.py` live travel, `app.py` + `ui/` window, `huntsman.py` CLI.
- User data: `~/Library/Application Support/Huntsman for Mac/` (state.json, first-launch-snapshot.json, usb.lock, state.lock); log `~/Library/Logs/Huntsman for Mac.log`.
- `install.sh` copies code + venv into `~/Applications/Huntsman for Mac.app` (unsigned apps can't read ~/Downloads); login item `io.github.huntsman-for-mac.apply-saved`.

## Next
Published 2026-11-17: https://github.com/samir777-eng/huntsman-for-mac (public, branch master, SEO description + 18 topics).
1. Upload a social preview image (GitHub → Settings → Social preview; use docs/screenshot-actuation.png).
2. Find testers for Rapid Trigger, Snap Tap, other V3 models, Intel and older macOS.
3. Optional: a GitHub Pages landing page and a first release tag (v0.1.0) for search visibility.

## Plan record
- docs/plans/2026-11-17-open-source-release.md
