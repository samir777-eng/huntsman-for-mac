---
name: New model or hardware report
about: Results from an experimental Huntsman model, another model, the Windows build, or Rapid Trigger, Snap Tap, Intel or older macOS
labels: hardware
---

Please don't add a Product ID to the code and write to a model the app doesn't list. A read-only check comes first.
For the six experimental models, the steps are in CONTRIBUTING.md under "Testing an experimental model"; for the
Windows build, under "Testing on Windows".

**Operating system** (keep one): macOS / Windows

**App version** (Keyboard tab → Keyboard info, or `huntsman.py --version`):

**Model** (exactly as on the box):

**USB IDs** (Mac: Apple menu → About This Mac → More Info → System Report → USB; Windows: Device Manager → the
keyboard → Properties → Details → Hardware Ids, the VID_ and PID_ values):
- Product ID:
- Vendor ID:

**Firmware version** (shown in the app's Keyboard tab and by `huntsman.py status`):

**macOS version and Mac** (Apple silicon or Intel), **or Windows version** (Settings → System → About):

**Windows only:** did SmartScreen ask? Was Razer Synapse installed or running? Did the window show a Dynamic Lighting
notice? Did the tray icon appear, and did the lighting service start again after signing out and in?

**Output of `huntsman.py status`** (Mac; the Windows download has no command line):

```
```

**LED check summary** (Keyboard tab → LED check → Copy summary, then paste here):

```
```

**Which features worked?** (yes, no or not tried; add what happened when something didn't work)
- Lighting effects:
- Brightness:
- Per-key colours (do the right keys light?):
- Studio:
- Actuation point (V3 Pro models, V2 Analog):
- Rapid Trigger (V3 Pro models):
- Snap Tap (V3 Pro models):

**Windows log** (the end of `%LOCALAPPDATA%\Huntsman for Mac\Logs\Huntsman for Mac.log`, remove anything personal):

```
```

**Anything else you tested and what happened** (for example: Rapid Trigger on W A S D, 0.3 mm; did keys re-fire as expected?):
