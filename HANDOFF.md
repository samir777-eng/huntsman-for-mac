# HANDOFF

Current state of Huntsman for Mac (updated 2026-11-17).

## Verified on hardware (Huntsman V3 Pro 1532:02A6, firmware 1.03, macOS 26, Apple silicon)
- Actuation write + read-back on all 103 keys, persists after replug; release point fixed to actuation − 6 units.
- Lighting effects (static) and brightness, persist on the keyboard.
- Per-key colour frame (0F:03, rows 0–5, cols 0–21, size 0x47; then effect [0,0,8] size 0x0C).
- Colour correction (gamma 2.2) matches the picker (owner's orange test).
- Driver mode (00:04 [3,0]) streams report 0x0B at ~500 Hz; back to hardware mode (00:04 [0,0]) confirmed.
- Installed .app opens and reads the keyboard.

## Not yet verified on hardware
- Rapid Trigger ON, Snap Tap ON (protocol from easyrazer; only OFF commands were seen accepted).
- Key tester inside the installed .app (needs Input Monitoring granted to the app's Python).
- Other models, Intel Macs, older macOS.

## Layout
- `huntsman_core.py` protocol/transport, `depth_stream.py` live travel, `app.py` + `ui/` window, `huntsman.py` CLI.
- User data: `~/Library/Application Support/Huntsman for Mac/` (state.json, first-launch-snapshot.json).
- `install.sh` copies code + venv into `~/Applications/Huntsman for Mac.app` (unsigned apps can't read ~/Downloads).

## Next
- Owner reviews the repo; decide project name (contains the "Huntsman" trademark), then create the GitHub repo.
- Get testers for Rapid Trigger / Snap Tap and other V3 models.

## Plan record
- docs/plans/2026-11-17-open-source-release.md
