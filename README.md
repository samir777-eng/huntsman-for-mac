# Huntsman for Mac: Razer Huntsman V3 Pro settings on macOS, without Synapse

Razer Synapse for Mac doesn't support the **Razer Huntsman V3 Pro** analog optical keyboard, so on a Mac you can't change its actuation point, Rapid Trigger or RGB lighting. **Huntsman for Mac** is a free, open-source macOS app that does: per-key actuation from 0.1 to 4.0 mm, Rapid Trigger, Snap Tap, per-key RGB colours and lighting effects. It also has a live key tester that shows how far each key is pressed.

Works on Apple silicon Macs (M1, M2, M3, M4) without Razer Synapse or a Windows PC.

> Unofficial. Not made, endorsed or supported by Razer. "Razer" and "Huntsman" are Razer Inc. trademarks, used here only to say which keyboard this works with. Use at your own risk; see [Safety](#safety).

![Actuation view](docs/screenshot-actuation.png)

## What it does

| Feature | Saved on the keyboard | Notes |
|---|---|---|
| Actuation point, per key, 0.1 to 4.0 mm | Yes | The reset point follows 0.1 mm above it, or set it yourself |
| Lighting effects (static, breathing, spectrum, wave, reactive, ripple, starlight) | Yes | Colours are corrected so the keyboard matches the colour you pick. All of them were accepted by the keyboard on hardware; the Fire effect some Razer keyboards have is refused by this one's firmware, so it isn't offered |
| Brightness | Yes | |
| Per-key colours | No, kept until unplugged | Sent again when the app opens and at login |
| Rapid Trigger | No, kept until unplugged | **Experimental**: not yet confirmed on real hardware |
| Snap Tap (one pair) | No, kept until unplugged | **Experimental**: not yet confirmed on real hardware |
| Live key tester and actuation meter | – | While testing, the keyboard sends travel readings instead of typing |

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
- **A login item** (`io.github.huntsman-for-mac.apply-saved`) that sends per-key colours, Rapid Trigger and Snap Tap to the keyboard again after you log in.

Open it from `~/Applications` or Spotlight. To preview the interface without a keyboard, open `ui/index.html?demo` in a browser.

### Input Monitoring for the key tester

The key tester reads the keyboard's travel reports, which macOS treats as input monitoring. The first time you start testing (*Start testing* in Key tester, or *Test with a key press* in Actuation), macOS asks for permission. If you said no, or nothing was asked:

1. Open **System Settings → Privacy & Security → Input Monitoring**.
2. Turn on **Huntsman for Mac**. If it isn't listed but **Python** is, turn that on instead. If neither is listed, click **+** and choose `~/Applications/Huntsman for Mac.app`.
3. Quit and reopen the app.

Re-installing replaces the app, so macOS may ask again, or the switch may need to be turned off and on.

### Update

1. Quit the app (Cmd-Q).
2. `git pull`
3. `./install.sh`

Also run `./install.sh` again after Homebrew upgrades Python: the app's environment points at the Python it was built with.

### Uninstall

Quit the app first, then:

```bash
./uninstall.sh          # removes the app and the login item; keeps your settings and the log
./uninstall.sh --all    # also deletes your settings, the first-launch snapshot and the log
```

Nothing on the keyboard changes. Use *Restore factory depth* in the app first if you want the keyboard back to its defaults.

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
| `apply-saved` | Send per-key colours, Rapid Trigger and Snap Tap again (what the login item runs) |
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

**Settings aren't sent again after login**
- Check the login item is loaded: `launchctl list | grep huntsman-for-mac`.
- Check **System Settings → General → Login Items & Extensions**; it may be listed as Python. It must be allowed.
- Its output goes to the same log, `~/Library/Logs/Huntsman for Mac.log`.

**The keyboard stopped typing** This means it was left in test mode. Unplug it and plug it back in; opening the app, or running any `huntsman.py` command, also puts it back to typing.

**Installer says the app is running** Quit it (Cmd-Q), then run the installer again.

## How it works

The app talks to the keyboard's control interface with USB control transfers through libusb. This avoids Razer's macOS driver, which keeps that interface to itself. Settings go to two places: the copy the keyboard is using right now, and the saved onboard profile. The live tester puts the keyboard into "driver mode" and reads its travel reports (report `0x0B`) through IOKit.

- `huntsman_core.py`: protocol and USB transport
- `depth_stream.py`: live travel readings
- `app.py` and `ui/`: the window
- `huntsman.py`: the command line

Your settings and logs live in:
- `~/Library/Application Support/Huntsman for Mac/`: `state.json` (settings the keyboard forgets when unplugged), `first-launch-snapshot.json`, and lock files.
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
Yes, from the Rapid Trigger and Snap Tap tabs. Both are experimental and not yet confirmed on real hardware; please report how they work for you.

**Can I set per-key RGB lighting without Synapse?**
Yes. Use Lighting → Per key to colour individual keys, or Effect for spectrum, wave, breathing, reactive, ripple and starlight.

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
