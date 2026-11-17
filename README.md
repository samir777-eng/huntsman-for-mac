# Huntsman for Mac: Razer Huntsman V3 Pro settings on macOS, without Synapse

Razer Synapse for Mac doesn't support the **Razer Huntsman V3 Pro** analog optical keyboard, so on a Mac you can't change its actuation point, Rapid Trigger or RGB lighting. **Huntsman for Mac** is a free, open-source macOS app that does: per-key actuation from 0.1 to 4.0 mm, Rapid Trigger, Snap Tap, per-key RGB colours and lighting effects. It also has a live key tester that shows how far each key is pressed.

Works on Apple silicon Macs (M1, M2, M3, M4) without Razer Synapse or a Windows PC.

> Unofficial. Not made, endorsed or supported by Razer. "Razer" and "Huntsman" are Razer Inc. trademarks, used here only to say which keyboard this works with. Use at your own risk; see [Safety](#safety).

![Actuation view](docs/screenshot-actuation.png)

## What it does

| Feature | Saved on the keyboard | Notes |
|---|---|---|
| Actuation point, per key, 0.1 to 4.0 mm | Yes | The reset point follows 0.1 mm above it, or set it yourself |
| Lighting effects (static, breathing, spectrum, wave, reactive, starlight) | Yes | Colours are corrected so the keyboard matches the colour you pick. All of them were accepted by the keyboard on hardware; the Fire effect some Razer keyboards have is refused by this one's firmware, so it isn't offered |
| Brightness | Yes | |
| Per-key colours | No, kept until unplugged | Sent again when the app opens and at login |
| Rapid Trigger | No, kept until unplugged | Confirmed on hardware (2026-11-17) |
| Snap Tap (one pair) | No, kept until unplugged | Confirmed on hardware (2026-11-17) |
| Live key tester and actuation meter | – | While testing, the keyboard sends travel readings instead of typing |
| Lighting Studio (layers, typing and sound effects, presets, smart lighting) | No, drawn by the app while it runs | **New in 0.2.0, not yet checked on hardware**. See [Lighting Studio](#lighting-studio) |

## Lighting Studio

The keyboard's own effects (the **Lighting** tab) run on the keyboard and are saved on it. **Studio** goes further: the app
draws every frame itself and streams it to the keys, so effects can be layered, react to typing and sound, and change with
what you're doing. Studio runs in a small background **lighting service** (Huntsman Lighting), not in the window, so
**effects keep running after you quit the app**, like Razer Synapse's service. When Studio is turned off or the lighting
service quits, the keyboard's own lighting comes back.

- **Layers.** Stack effects; the top layer is drawn last. Each layer has its own colours and settings, opacity, a blend mode
  (normal, add, screen, multiply, brightest) and a key set (all keys, or the keys you select on the board).
- **Effects.** Basic: solid colour, gradient (linear or radial, 2 to 5 colours), rainbow wave, colour cycle, breathing.
  Ambient: aurora, matrix rain, plasma, fire, starfield. Sound: audio spectrum (bars across the keyboard), audio pulse.
  Typing: ripple, afterglow, explosion, trail, and a typing heatmap.
- **Presets.** Eight built-in presets to start from (Rainbow wave, Aurora, Gaming WASD, Typing glow, Music, Fire, Matrix,
  Calm breathing). Save, save as, rename, duplicate, delete, and import or export a preset as a JSON file. Built-in presets
  can't be changed; save a copy instead. Brightness and smoothness (15 to 60 frames a second) apply to all presets.
- **Sound.** Choose the input in Studio → Sound. A microphone hears the room. **For the Mac's own sound, install a loopback
  device such as [BlackHole](https://github.com/ExistentialAudio/BlackHole), send your output to it (for example with a
  Multi-Output Device in Audio MIDI Setup), and choose it as the input.** Sensitivity adjusts how strongly the lights react.
- **Smart lighting** (Studio → Smart). Dim the keys or turn them off after a number of minutes without input; turn them off
  while the Mac sleeps or the screen is locked; show a chosen preset while a given app is in front (pick an open app or type
  its bundle ID).
- **Menu bar.** The keyboard icon in the menu bar belongs to the lighting service. It turns Studio on or off, switches
  presets, opens Huntsman for Mac, and has **Quit lighting service**, which stops Studio and puts the keyboard's own
  lighting back. The service starts at login (and when the installer finishes); after *Quit lighting service* it stays
  off until the next login or until you use Studio in the app, which starts it again. Quitting the app window (red
  button, Cmd-Q) just closes the window; the lighting keeps running. While the app changes the keyboard (actuation,
  keyboard effects, per-key colours, brightness, the key tester), the service pauses its frames.

### Permissions

Studio's permissions belong to the lighting service, so macOS lists them as **Huntsman Lighting**:

- **Input Monitoring**, for typing effects and the heatmap: **System Settings → Privacy & Security → Input Monitoring →
  Huntsman Lighting**. The service only listens while a preset with a typing effect is on or the heatmap is counting.
  (The key tester in the window needs the same permission for **Huntsman for Mac**; see
  [Input Monitoring](#input-monitoring-for-the-key-tester).)
- **Microphone**, for sound effects: **System Settings → Privacy & Security → Microphone → Huntsman Lighting**. The service
  only listens while a preset with a sound effect is on. If access is refused, Studio shows where to turn it on.
- After changing either, use **Quit lighting service** in the menu bar, then turn Studio on again in the app.

### Privacy

Key presses and sound are processed in memory, frame by frame, to draw the lights. Nothing is recorded, logged or sent
anywhere. The typing heatmap is off by default; when you turn it on, it stores only how many times each key was pressed
(`heatmap.json`, on this Mac), never which keys in which order, and **Reset heatmap** deletes it.

## What has been checked on real hardware

Checked on 2026-11-17 with a Huntsman V3 Pro (USB ID 1532:02A6), firmware 1.03, wired, on macOS 26 with Apple silicon.

| Checked on hardware | Not checked yet |
|---|---|
| Actuation and reset points: written, read back, still there after unplugging | Rapid Trigger turned on |
| Static lighting and brightness | Snap Tap turned on |
| Per-key colours | The key tester inside the installed app (Input Monitoring for the app's Python) |
| Colour correction (the keyboard matches the picker) | Other Huntsman models |
| Key tester readings, and switching the keyboard back to typing afterwards | Intel Macs |
| Quitting the app with SIGTERM during a key test: the keyboard types again | macOS versions before 26 |
| A keyboard left in test mode is put back to typing the next time the app or the command line connects | A hard kill (SIGKILL) during a key test; this relies on the recovery on the next connect, which is checked |
| Checksums on the keyboard's replies; actuation is written to the saved copy before the live copy | Lighting effects other than static |

## Supported hardware

Only the **Huntsman V3 Pro (USB ID 1532:02A6), wired**. Other Huntsman V3 models use the same commands, but the app only connects to 1532:02A6 until someone tests them. If you own another model, see [CONTRIBUTING.md](CONTRIBUTING.md#reporting-a-new-model).

Intel Macs and macOS versions before 26 are untested. They will probably work; please report back either way.

## Install

You need:
- macOS on a Mac with the keyboard plugged in by USB.
- Python 3.11 to 3.13, from Homebrew (`brew install python@3.13`) or from [python.org](https://www.python.org/downloads/macos/). Newer versions are used if nothing older is found; the installer says they are untested.
- [Homebrew](https://brew.sh), which the installer uses to add libusb if it's missing.

```bash
git clone https://github.com/samir777-eng/huntsman-for-mac.git
cd huntsman-for-mac
./install.sh
```

This installs:
- **Huntsman for Mac.app** in `~/Applications`. It carries its own copy of the code and Python environment, and is signed ad hoc on your Mac (no Apple developer account involved).
- **libusb**, through Homebrew, if it's missing.
- **The lighting service**, `Huntsman Lighting.app`, inside the app (`Contents/Library/LoginItems`), and a LaunchAgent (`io.github.huntsman-for-mac.lighting`) that starts it now and at every login, and restarts it if it crashes (not after *Quit lighting service*). At start it sends per-key colours, Rapid Trigger and Snap Tap to the keyboard again, starts Studio if it was on, and shows the menu bar icon. It replaces the `apply-saved` login item of earlier versions, which the installer removes. Its own small app bundle means macOS shows **Huntsman Lighting** in the Input Monitoring and Microphone lists.

Open it from `~/Applications` or Spotlight. To preview the interface without a keyboard, open `ui/index.html?demo` in a browser.

### Input Monitoring for the key tester

The key tester reads the keyboard's travel reports, which macOS treats as input monitoring. The first time you start testing (*Start testing* in Key tester, or *Test with a key press* in Actuation), macOS asks for permission. If you said no, or nothing was asked:

1. Open **System Settings → Privacy & Security → Input Monitoring**.
2. Turn on **Huntsman for Mac**. If it isn't listed but **Python** is, turn that on instead. If neither is listed, click **+** and choose `~/Applications/Huntsman for Mac.app`.
3. Quit and reopen the app.

Re-installing replaces the app, so macOS may ask again, or the switch may need to be turned off and on.

### Update

1. Quit the app (Cmd-Q). The installer stops and restarts the lighting service itself.
2. `git pull`
3. `./install.sh`

Also run `./install.sh` again after Homebrew upgrades Python: the app's environment points at the Python it was built with.

### Uninstall

Quit the app first, then:

```bash
./uninstall.sh          # stops the lighting service, removes the app and its login item; keeps your settings and the log
./uninstall.sh --all    # also deletes your settings, the first-launch snapshot and the log
```

Stopping the lighting service puts the keyboard's own lighting back; nothing else on the keyboard changes. Use *Restore factory depth* in the app first if you want the keyboard back to its defaults.

## Command line

The installed app includes the command-line tool:

```bash
APP=~/Applications/"Huntsman for Mac.app"/Contents/Resources
$APP/venv/bin/python $APP/code/huntsman.py status
```

| Command | What it does |
|---|---|
| `status` | Firmware, saved profile, brightness, and the A key's actuation and reset points |
| `depth 2.0` | Every key types at 2.0 mm (0.1 to 4.0); the reset point follows 0.1 mm above |
| `depth 0.5 W A S D` | Only those keys |
| `color 255 255 255` | Solid colour, saved on the keyboard |
| `spectrum`, `wave`, `off` | Built-in effects, saved on the keyboard |
| `brightness 80` | Brightness, 0 to 100 |
| `apply-saved` | Send per-key colours, Rapid Trigger and Snap Tap again (the lighting service does this when it starts) |
| `factory` | Every key back to 1.2 mm; Rapid Trigger and Snap Tap off |
| `restore-snapshot` | Put every key back exactly as it was on the app's first launch |
| `--version` | Print the version |
| `help` | Print this list |

## Safety

The app writes to the keyboard's built-in memory using commands the community worked out by reverse engineering, not from Razer documentation.
- **Actuation** has been checked on real hardware: written, read back and confirmed after unplugging. **Static lighting and brightness** were checked to stay after unplugging.
- Every command checks that the keyboard's reply matches the request and passes its checksum. Actuation writes are also read back key by key; lighting writes are not read back.
- **Restore factory depth** (in the app, or `huntsman.py factory`) puts every key back to 1.2 mm and turns off Rapid Trigger and Snap Tap.
- **Your original settings are saved.** On first launch the app copies every key's settings to `~/Library/Application Support/Huntsman for Mac/first-launch-snapshot.json`; `huntsman.py restore-snapshot` puts them back.
- **The key tester switches the keyboard back to typing** when you stop, after 60 seconds, when you close the window, when the app quits, and when macOS ends it (SIGTERM). If the app is killed outright, the next time the app or the command line connects it puts the keyboard back to typing. Unplugging and replugging should also work, since test mode isn't stored.
- **If everything else fails**, connecting the keyboard to Windows with Razer Synapse should reset it. This hasn't been needed or tried.

## Troubleshooting

**"Huntsman V3 Pro not found"**
- Connect it with its USB cable, directly or through a powered hub, then open Keyboard info (the gear icon) and click *Reconnect*.
- Check it's the right model: **Apple menu → About This Mac → More Info → System Report → USB**. Look for a Razer device with **Product ID 0x02a6** and Vendor ID 0x1532. Other IDs aren't supported yet.
- Only one program can use the keyboard's control interface. Quit Razer Synapse, OpenRazer-based tools or anything else that talks to Razer devices, then click *Reconnect* in Keyboard info.

**"libusb is missing"** Run `brew install libusb`, then `./install.sh` again.

**The app doesn't open, or macOS says it's damaged or from an unidentified developer**
- The installer removes the download quarantine flag and signs the app ad hoc. If it printed a signing warning, run `./install.sh` again and keep the output for a bug report.
- You can also right-click the app, choose **Open**, and confirm.
- Check the log: `~/Library/Logs/Huntsman for Mac.log`.

**The app opens but stops working after a Python upgrade** Run `./install.sh` again.

**Settings aren't sent again after login, or Studio stops when the app quits**
- Check the lighting service is loaded and running: `launchctl print gui/$(id -u)/io.github.huntsman-for-mac.lighting`. Start it by hand with `launchctl kickstart gui/$(id -u)/io.github.huntsman-for-mac.lighting` (the app does this when you use Studio).
- Check **System Settings → General → Login Items & Extensions**; it may be listed as Huntsman Lighting or Python. It must be allowed.
- Its output goes to the same log, `~/Library/Logs/Huntsman for Mac.log`.

**The keyboard stopped typing** This means it was left in test mode. Unplug it and plug it back in; opening the app, or running any `huntsman.py` command, also puts it back to typing.

**Installer says the app is running** Quit the window app (Cmd-Q), then run the installer again. The lighting service doesn't need quitting; the installer stops and restarts it.

**Studio lights don't follow typing or sound** Studio → Typing or Sound shows the reason. Usually Input Monitoring or
Microphone access is off for Huntsman Lighting (see [Permissions](#permissions)); use *Quit lighting service* in the menu
bar after turning it on, then turn Studio on again.
For the Mac's own sound, the input must be a loopback device such as BlackHole, not the microphone.

## How it works

The app talks to the keyboard's control interface with USB control transfers through libusb. This avoids Razer's macOS driver, which keeps that interface to itself. Settings go to two places: the copy the keyboard is using right now, and the saved onboard profile. The live tester puts the keyboard into "driver mode" and reads its travel reports (report `0x0B`) through IOKit.

- `huntsman_core.py`: protocol and USB transport
- `depth_stream.py`: live travel readings
- `app.py` and `ui/`: the window, the control panel (`ui/studio.js` is the Studio tab)
- `service.py`: the lighting service (Huntsman Lighting): runs Studio and the menu bar icon in the background
- `ipc.py`: the local socket between the app and the service (`service.sock`, JSON lines, owner-only): Studio commands,
  live preview frames, and pause leases the app holds around every keyboard operation (they expire on their own, so a
  crashed app never leaves the lighting paused)
- `studio.py`: Studio controller (presets, settings, listeners, smart lighting) between the service and the engine
- `lighting/`: effects, layers, presets and the engine that streams per-key frames
- `inputs/`: key presses (IOKit), sound levels (sounddevice) and smart-lighting signals (idle, sleep, lock, front app)
- `menubar.py`: the menu bar icon
- `huntsman.py`: the command line

Your settings and logs live in:
- `~/Library/Application Support/Huntsman for Mac/`: `state.json` (settings the keyboard forgets when unplugged, and Studio and smart lighting settings), `presets.json` (your Studio presets), `heatmap.json` (press counts, only if the heatmap is on), `first-launch-snapshot.json`, lock files, and the lighting service's socket (`service.sock`).
- `~/Library/Logs/Huntsman for Mac.log`

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). In short:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q tests
```

The tests use a simulated keyboard and never touch USB. The interface tests open `ui/index.html?demo` in a headless browser; they are skipped if Playwright isn't installed.

## FAQ

**Does Razer Synapse work with the Huntsman V3 Pro on Mac?**
Not at the time of writing. Synapse for macOS detects the keyboard but has no settings for it, so actuation, Rapid Trigger and per-key lighting can't be changed there. This app fills that gap.

**How do I change the actuation point of a Razer Huntsman V3 Pro on macOS?**
Open Huntsman for Mac, select keys (or none for all keys), pick a depth between 0.1 and 4.0 mm and press Apply. The setting is stored on the keyboard, so it stays after unplugging and also works on other computers.

**Can I use Rapid Trigger or Snap Tap on a Mac?**
Yes, from the Rapid Trigger and Snap Tap tabs. Both have been confirmed on a Huntsman V3 Pro; please report how they work on other models.

**Can I set per-key RGB lighting without Synapse?**
Yes. Use Lighting → Per key to colour individual keys, or Effect for spectrum, wave, breathing, reactive and starlight. Ripple and other typing effects are in Studio.

**Do I need Windows, Boot Camp or a virtual machine?**
No. It talks to the keyboard directly over USB from macOS.

**Which keyboards are supported?**
The Razer Huntsman V3 Pro (full size, USB ID 1532:02A6) is tested. The Huntsman V3 Pro TKL, V3 Pro Mini and 8KHz versions use the same commands but aren't enabled yet; see [CONTRIBUTING.md](CONTRIBUTING.md) to help add them.

## Credits

This project uses facts and data from:
- [easyrazer](https://github.com/janeblower/easyrazer) (GPL-3.0-or-later): the key IDs, layout geometry and LED map in `layout.json` and `keymap.json` are derived from it, as are the analog actuation, Rapid Trigger, Snap Tap and per-key frame commands.
- [OpenRazer](https://github.com/openrazer/openrazer) (GPL-2.0-or-later driver): protocol facts only, the report format and lighting commands. No code is copied.
- [SensorFinder for Razer Huntsman](https://github.com/ohy1/SensorFinder-for-Razer-Huntsman) (MIT): protocol facts only, the actuation and release-point rules and the travel report format.

See [NOTICE](NOTICE) for details.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
