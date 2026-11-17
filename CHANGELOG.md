# Changelog

All notable changes to this project are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## Unreleased (0.2.0)

Not yet checked on hardware.

### Added
- Lighting Studio: app-drawn per-key effects streamed to the keyboard while the app runs, with a layer editor (opacity,
  blend modes, per-layer key sets), an effect gallery and live preview on the on-screen keyboard.
- Effects: solid, gradient, rainbow wave, colour cycle, breathing, aurora, matrix rain, plasma, fire, starfield, audio
  spectrum, audio pulse, typing heatmap, and typing reactions (ripple, afterglow, explosion, trail).
- Presets: eight built-ins; save, save as, rename, duplicate, delete, import and export (JSON).
- Sound-reactive lighting from any input device, including loopback devices such as BlackHole for system audio.
- Smart lighting: dim or off when idle, off while the Mac sleeps or the screen is locked, a preset per frontmost app.
- Menu bar icon (Studio on/off, presets, open, quit). Closing the window keeps Studio running in the menu bar.

### Changed
- The login item opens the app in the background (`open -g -a ... --args --background`) instead of running
  `apply-saved`; it still re-sends per-key colours, Rapid Trigger and Snap Tap.
- Applying a keyboard effect or per-key colours turns Studio off. Every other keyboard operation pauses Studio's stream.
- New dependencies: numpy and sounddevice. The app asks for Microphone access when a sound effect is used.

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
