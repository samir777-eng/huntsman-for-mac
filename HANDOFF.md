# HANDOFF

Current state of Huntsman for Mac (updated 2026-11-17). Version 0.1.0, not yet published.

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
1. Decide the project name (the current one contains the "Huntsman" trademark).
2. Decide the commit author email for the public history (current commits carry a personal address).
3. Fill in the TODOs: clone URL in README.md (`OWNER/REPO`), security contact in SECURITY.md.
4. Create the GitHub repo and push.
5. Find testers for Rapid Trigger, Snap Tap, other V3 models, Intel and older macOS.

## Plan record
- docs/plans/2026-11-17-open-source-release.md
