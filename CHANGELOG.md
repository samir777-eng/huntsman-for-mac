# Changelog

All notable changes to this project are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

### Changed
- The key tester runs live: no more *Test with a key press* button. It starts by itself while the Actuation tab is open
  and the window is in front (focused and visible) on a model with the key tester, and stops, with the keyboard typing
  again, on another tab, another app, a minimised or hidden window, close, quit, disconnect or Reconnect. Focus changes
  are debounced (300 ms). A status line in Actuation says when it's live or paused; the banner's Stop button is gone.
- The tester pauses after 5 minutes without key travel (was: 60 seconds after starting) and stays paused until the
  window is focused again, the tab is opened again, or *Resume* / the board is clicked. A failed start shows its reason
  once with *Try again* and isn't retried by itself.
- Keys can be selected and Apply used while the tester runs; Apply writes as before and the tester keeps running.
- UX audit of the live view: the app opens on the last tab used (first launch: Lighting), so it doesn't stop the
  Huntsman typing at launch unless it was left on Actuation; a one-time explanation the first time it goes live. The
  trace and readings keep their place while paused (dimmed, with a *Paused · Resume* chip on the trace), so nothing
  jumps; the trace's height follows the window (110–200 px) and the presets sit above the readings. One message per
  place: the banner says what's happening ("Click another window to type again"), the status line the state (live, it also says
  once how to type again), and it's the only live region (the meter's line no longer speaks; its buttons sit outside
  it, and a button that hides itself hands focus to the depth slider). Input Monitoring refused shows *Open Privacy
  settings*. "Live view" wording throughout. Resuming is from the chip, focus or the tab only; clicking the board
  selects keys. The readings say "Last key: W"; the trace names the key and asks for one while empty. Toasts sit
  below the board while the trace shows. "Starting live view…" appears only if a start takes over 400 ms.

## 0.4.0 – 2026-11-22

### Added
- A Windows build, experimental and untested: `Huntsman-for-Windows-<version>.zip` on the release, a one-folder
  PyInstaller build with one `Huntsman.exe` (the window; `Huntsman.exe --service` runs the lighting service). Unsigned,
  so SmartScreen asks first. Everything the Mac app does, except the key tester, through a small platform layer
  (`platforms/`): hidapi feature reports on interface 3 (the keyboard's normal driver), a tray icon instead of the menu
  bar icon, start at login through the per-user Run key (value "Huntsman for Mac lighting", no admin rights; added once and
  kept up to date if `Huntsman.exe` moves, not added back if you delete it, until you turn Studio on in the app), a named
  pipe between the app and the service (random name and key at every start, mutual HMAC handshake), Raw Input for
  typing reactions, and idle, sleep, lock and front-program events for smart lighting (app rules use program names
  such as `steam.exe`). Settings in `%APPDATA%\Huntsman for Mac`, the log in
  `%LOCALAPPDATA%\Huntsman for Mac\Logs`.
- On Windows every model is experimental (writes need the Experimental support switch, the V3 Pro too) and the key
  tester is never offered; pointing at the header's Experimental badge says Windows support is experimental.
- Windows: while Razer Synapse runs (RazerAppEngine.exe, Synapse 3 or 2), nothing at all reaches the keyboard, reads
  included (two programs on the same HID interface swap each other's replies): the app and the lighting service let go
  of the keyboard, the window shows the last model it saw (locked) with "Paused: Razer Synapse is running", and the
  tray menu says why. Studio switched off while Synapse runs stays off when Synapse quits; everything else comes back
  within a few seconds. When Windows
  Dynamic Lighting is on, the window says how to turn it off for the keyboard (the app never changes it).
- `Huntsman.exe --version` and `--self-test` (imports every module and reads every data file and layout the build
  needs, without opening the keyboard or a window; it writes to the log, since a windowed exe has no console).
- CI: GitHub Actions runs the test suite on macOS and Windows for every push and pull request, and builds,
  smoke-tests and zips the Windows app (attached to a release when it's published).
- Huntsman V2 Analog (1532:0266): actuation, experimental and untested, behind Experimental support like every other
  write to it. Its own scale from easyrazer (mm = byte / 255 × 2.1 + 1.5): 1.62 to 3.56 mm (bytes 15 to 250, the
  range its firmware keeps to), in 0.01 mm steps, with its own presets. Without a reset point (the window's *Just above*,
  `huntsman.py depth`) the reset point follows 0.1 mm above, at least 1.54 mm (byte 5), in the saved and the live
  profile alike; a custom one must sit at least 0.08 mm (10 bytes) above the actuation point (the release rules are
  unverified). Keys already at the target aren't written again, to spare flash. Each write changes at most the two depth
  bytes of the normal layer, keeps the key's assignment, goes to the
  active saved profile first and then the live one, and is read back. Reads show the depth the keyboard acts on, so a
  key Synapse left at 0/0 shows as 1.62 mm. Key ids are easyrazer's 0266 key map; all 104 keys of the layout match.
- The V2 Analog gets the first-launch snapshot, and `huntsman.py restore-snapshot` works on it.
- Six more built-in Studio presets, after the original eight (fourteen in all): Plasma (a vivid flowing plasma),
  Starfield (twinkling stars on a deep blue sky), Ripple (colour rings from each key press over a dim base),
  Spectrum bars (sound bars in blue to pink over a slowly drifting base), Sunset (a slow warm gradient) and Neon
  cycle (the whole keyboard fading through neon colours). They work on every model's layout.

### Changed
- Every JSON and text file the app reads or writes is opened as UTF-8 (found by CI on Windows, where the locale
  encoding broke layouts with non-ASCII names). On the Mac this was already the default.
- The macOS app bundles say 0.4.0 (build 4).
- The actuation slider, its labels, the presets and the custom reset point follow the connected model's range and
  step (the window gets them with the model). The V3 Pro family is unchanged: 0.1 to 4.0 mm in 0.1 mm steps, and every
  byte sent to the V3 Pro is the same (golden tests).
- `huntsman.py depth` checks the connected model's range.

- From the UX audit (docs/plans/2026-11-18-ux-audit-fixes.md, items 1–6):
  - No keyboard: the stage says "Plug in your Huntsman by USB" with a Reconnect button, the panes other than Keyboard
    are switched off, the header says "No keyboard" instead of a model name, and there's no red toast at start.
    Reconnect says "Connected to {model}" and clears an earlier error toast.
  - Actuation: keys at different depths read "Mixed (1.0–2.0 mm)", the slider follows the selected keys until you
    move a control, and "Not applied yet" shows only after an edit. Apply asks first when keys in its scope use
    different depths, naming only the keys that will change and how ("99 keys will change from 2.0 mm to 1.0 mm.
    W, A, S, D already type at 1.0 mm."). No depth preset shows as chosen while the readout says Mixed.
  - Small windows: legends scale with the keys; below about 27 px per key the depths show in place of the legend
    when you point at or focus a key, instead of over it.
  - The primary Apply of Actuation, Rapid Trigger, Snap Tap and Lighting effects stays in view at the bottom of the
    panel; the tester's readings and warning show only while testing.
  - Studio: with Studio off, its tab previews the preset on the on-screen board ("Preview, Studio off", Turn on).
    The lighting service composes the frames without sending anything to the keyboard (`studio_preview`, asked again
    every few seconds while the tab shows, 30 s at most per request).
  - Built-in presets show Save as… as the main button with "Built-in preset: save a copy to keep your changes."
    instead of a disabled Save.
  - The live tester readout is announced to screen readers when it changes; switching tabs drops the last toast.
- From the same UX audit (items 7–10 and the other quick wins):
  - The Keyboard pane's button in the header says "Keyboard" next to its gear, matching the notes that point to it.
    On models without the key tester, "Test with a key press" shows disabled with the reason (experimental models,
    the Huntsman V2 family, or Windows) instead of disappearing.
  - Windows: while Razer Synapse runs, the panel shows one notice, "Quit Razer Synapse to use these controls", with
    the reason folded under Why, and no "turn on Experimental support" note (it wouldn't help). The Dynamic Lighting
    notice is one line with Details. The Synapse message says "this app" instead of "Huntsman for Mac".
  - The Select bar and key outlines show only where the selection does something (Actuation, Rapid Trigger,
    Lighting's Per key and a Static effect, Studio's Layers). The panel names a selection made on another tab:
    "Applying to 4 selected keys · Clear".
  - Snap Tap has a switch and Apply like Rapid Trigger, "Not applied yet" while the panel differs from the keyboard,
    and "On for A and D" once applied (the Apply button stays "Apply", disabled, while Snap Tap is off and
    unchanged). Click two keys on the keyboard to make the pair, or use the lists; leaving the tab or Reconnect starts
    the pick over at the first key. The keyboard gets the same command as before.
  - When the keyboard goes away, focus in a pane that switches off (or on the hidden keyboard) moves to the stage's Reconnect button.
  - Studio: the layer up and down buttons are 32 px; a Solid colour added on top of other layers mixes in at 50 %
    (Normal) instead of covering them all. The Keyboard pane says "Onboard profile" instead of "Stored profile".

### Not offered on the V2 Analog
- Rapid Trigger and Snap Tap (Razer's software runs them on the computer; the keyboard has no command for them), the
  key tester, and *Restore factory depth* / `huntsman.py factory` (its factory depth isn't known; they refuse before
  anything is sent).

### Not checked on hardware
- Everything on Windows: the build has never run on a Windows PC with a keyboard. Only the test suite (simulated
  keyboard) and the built exe's `--version` and `--self-test` have run, on GitHub's windows-latest runners. Not seen
  yet: the window (WebView2), the tray icon, start at login, typing reactions, smart lighting, the Synapse check, the
  Dynamic Lighting notice, SmartScreen, and every exchange with a keyboard.
- Actuation on the V2 Analog: the 3.56 mm end was checked on this keyboard by easyrazer; the 1.62 mm end and the reset
  point rules come from its reading of the firmware.
- The Mac app on the V3 Pro (02A6): the window, the menu bar icon, actuation, lighting, Studio after the app quits and
  the key tester were checked on 2026-11-18, before the UX-audit changes; the no-keyboard screen and Reconnect on
  2026-11-20. Not checked on the keyboard yet: the Mixed readout and the Apply confirmation, Snap Tap's switch and
  picking keys on the board, Studio's preview while off, the six new presets, and the key tester since the UX-audit
  changes. The golden tests show every byte sent to it is unchanged.

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
