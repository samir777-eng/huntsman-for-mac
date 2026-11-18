# Changelog

All notable changes to this project are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## 0.3.0 – 2026-11-17

### Added
- Experimental support for six more Huntsman models: V3 Pro TKL (1532:02A7), V3 Pro 8KHz (02CF), V3 Pro Mini (02B0),
  V2 (026C), V2 TKL (026B) and V2 Analog (0266). They get only commands already checked on the V3 Pro (02A6).
- Model detection: the app, the lighting service and the command line open the first supported model found, and use
  its lighting matrix, layout, effects and features. The header shows the model name and an Experimental badge.
- Keyboard → Experimental support: one remembered switch, with a warning. While it's off, nothing that changes an
  experimental keyboard is sent: lighting, per-key colours, Studio, actuation, Rapid Trigger and Snap Tap are refused
  before anything reaches USB. Reads (model, firmware, profile, effect, brightness) are always allowed.
- `huntsman.py experimental on|off`. `huntsman.py status` now prints the model, its USB ID and status.
- LED check (Keyboard tab, experimental models, switch on): lights one matrix cell at a time, notes which key lit,
  and copies a summary to paste into an issue.
- Layout files for each model in `layouts/`. Demo mode previews any model (`ui/index.html?demo&model=02B0`).
- Tests: golden bytes for every packet sent to the V3 Pro, recorded from 0.2.0, so its behaviour stays the same.

### Changed
- The V2 family has no actuation, Rapid Trigger or Snap Tap tabs and no key tester; the V2 Analog has no starlight effects.
- The key tester is only offered on the V3 Pro (02A6). It is never offered on an experimental model.
- The key tester moved into Actuation: the Key tester tab is gone, and *Test with a key press* starts the same test.
  The last key's types at, resets at and deepest press show below the button, and the travel trace shows under the
  keyboard while testing.
- The first-launch snapshot records its model and is never written to another one. Models without adjustable
  actuation get none.
- Studio's audio, matrix and fire effects use the keyboard's row count.
- "Huntsman V3 Pro not found" is now "No supported Razer Huntsman found".

### Not checked on hardware
- Every experimental model: nothing in this release has been seen working on them. Their LED positions are a guess
  (the V2 Analog's come from easyrazer's map) until a tester confirms them with the LED check.
- Whether the V3 Pro 8KHz reports its active profile the same way as the V3 Pro.

Checked on the V3 Pro (02A6) before release: the window, actuation, Rapid Trigger and Snap Tap, keyboard effects,
per-key colours and brightness, Studio (typing, ambient, after quitting the app), and the key tester in Actuation with
typing coming back.

## 0.2.0 – 2026-11-17

Checked on hardware after release (2026-11-17): Studio presets, layers, settings and panels, music through the
microphone, and effects continuing after the app quits. Not yet checked: smart lighting over a long session, system
sound through BlackHole, lighting restore at logout, restart after a crash, the name in the permission prompts.

### Added
- Lighting Studio: app-drawn per-key effects streamed to the keyboard while the app runs, with a layer editor (opacity,
  blend modes, per-layer key sets), an effect gallery and live preview on the on-screen keyboard.
- Effects: solid, gradient, rainbow wave, colour cycle, breathing, aurora, matrix rain, plasma, fire, starfield, audio
  spectrum, audio pulse, typing heatmap, and typing reactions (ripple, afterglow, explosion, trail).
- Presets: eight built-ins; save, save as, rename, duplicate, delete, import and export (JSON).
- Sound-reactive lighting from any input device, including loopback devices such as BlackHole for system audio.
- Smart lighting: dim or off when idle, off while the Mac sleeps or the screen is locked, a preset per frontmost app.
- Lighting service (Huntsman Lighting): Studio runs in a background menu bar app, started at login by a LaunchAgent
  (`io.github.huntsman-for-mac.lighting`, restarted after a crash), so effects keep running after the app quits. Its menu
  bar icon has Studio on/off, presets, Open Huntsman for Mac and Quit lighting service. The app talks to it over a local
  socket and pauses it (with self-expiring leases) around every keyboard operation.

### Changed
- The `apply-saved` login item is replaced by the lighting service, which re-sends per-key colours, Rapid Trigger and
  Snap Tap when it starts. The installer removes the old item and starts the service right away.
- Quitting the app (red button, Cmd-Q) just closes it; Studio keeps running in the lighting service.
- Typing and sound permissions are asked for, and listed, as Huntsman Lighting.
- Applying a keyboard effect or per-key colours turns Studio off. Every other keyboard operation pauses Studio's stream.
- New dependencies: numpy and sounddevice. The app asks for Microphone access when a sound effect is used.

## 0.1.0 – 2026-11-17

First public version.

### Added
- Per-key actuation point (0.1 to 4.0 mm) with an automatic or custom reset point, saved on the keyboard.
- Lighting: built-in effects, brightness and per-key colours, with colour correction so the keyboard matches the picker.
- Rapid Trigger and Snap Tap (experimental at release; confirmed on hardware 2026-11-17).
- Live key tester and actuation meter, with automatic return to typing on stop, timeout, window close, quit, SIGTERM and the next connect.
- First-launch snapshot of every key's settings, and a factory depth restore.
- Command-line tool (`huntsman.py`), including `--version`.
- Installer that builds `~/Applications/Huntsman for Mac.app` with its own Python environment, strips the quarantine flag, signs it ad hoc and adds a login item that re-sends settings the keyboard forgets.
- Progress bar while many keys are read or written.
- Tests: simulated keyboard, plus interface smoke tests in headless Chromium.

### Checked on hardware
Huntsman V3 Pro (1532:02A6), firmware 1.03, macOS 26, Apple silicon: actuation and reset points, static lighting, brightness, per-key colours, colour correction, the key tester's readings and switching back to typing, and recovery of a keyboard left in test mode.
