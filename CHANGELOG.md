# Changelog

All notable changes to this project are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

## 0.1.0 – 2026-11-17

First public version.

### Added
- Per-key actuation point (0.1 to 4.0 mm) with an automatic or custom reset point, saved on the keyboard.
- Lighting: built-in effects, brightness and per-key colours, with colour correction so the keyboard matches the picker.
- Rapid Trigger and Snap Tap (experimental, not yet confirmed on hardware).
- Live key tester and actuation meter, with automatic return to typing on stop, timeout, window close, quit, SIGTERM and the next connect.
- First-launch snapshot of every key's settings, and a factory depth restore.
- Command-line tool (`huntsman.py`), including `--version`.
- Installer that builds `~/Applications/Huntsman for Mac.app` with its own Python environment, strips the quarantine flag, signs it ad hoc and adds a login item that re-sends settings the keyboard forgets.
- Progress bar while many keys are read or written.
- Tests: simulated keyboard, plus interface smoke tests in headless Chromium.

### Checked on hardware
Huntsman V3 Pro (1532:02A6), firmware 1.03, macOS 26, Apple silicon: actuation and reset points, static lighting, brightness, per-key colours, colour correction, the key tester's readings and switching back to typing, and recovery of a keyboard left in test mode.
