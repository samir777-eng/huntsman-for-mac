#!/usr/bin/env python3
"""Command-line control for the Razer Huntsman V3 Pro (1532:02A6) on macOS, without Synapse.

  huntsman.py status
  huntsman.py depth 2.0              all keys (0.1-4.0 mm); the reset point follows 0.1 mm above
  huntsman.py depth 0.5 W A S D      only those keys
  huntsman.py color 255 255 255      solid colour, saved on the keyboard
  huntsman.py spectrum | wave | off
  huntsman.py brightness 0-100
  huntsman.py apply-saved            send per-key colours, Rapid Trigger and Snap Tap again (runs at login)
  huntsman.py factory                every key back to 1.2 mm; Rapid Trigger and Snap Tap off
  huntsman.py restore-snapshot       put back every key exactly as it was on the app's first launch
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import app  # noqa: E402
import depth_stream  # noqa: E402
import huntsman_core as hc  # noqa: E402


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    layout = hc.load_layout()
    names = {k["name"].upper(): k["id"] for k in layout}
    names.update({k["label"].upper(): k["id"] for k in layout if k["label"]})
    kb, cmd = hc.Keyboard(), argv[0]
    depth_stream.recover_typing(kb)  # a crashed key test leaves the keyboard not typing; put it back
    if cmd == "status":
        act, rel = kb.read_points(names["A"])
        print(f"firmware {kb.firmware()}, saved profile {kb.saved}, brightness {kb.brightness()}%")
        print(f"A key: types at {act} mm, resets at {rel} mm")
    elif cmd == "depth":
        keys = app.check_key_ids([names[n.upper()] for n in argv[2:]])  # refuses Fn
        failed = kb.set_actuation(keys, float(argv[1]))
        print(f"{len(keys) - len(failed)} keys now type at {round(float(argv[1]), 1)} mm"
              + (f"; not confirmed: {failed}" if failed else ""))
    elif cmd in ("color", "spectrum", "wave", "off"):
        opts = {"color": {"rgb1": [int(x) for x in argv[1:4]]}, "wave": {"speed": 40, "direction": "right"}}.get(cmd, {})
        app.set_effect(kb, "static" if cmd == "color" else cmd, opts)
        print("done")
    elif cmd == "brightness":
        kb.set_brightness(int(argv[1]))
        print("done")
    elif cmd == "apply-saved":
        done = app.apply_saved(kb)
        print("sent again:", ", ".join(done) or "nothing")
    elif cmd == "factory":
        app.restore_factory(kb)
        print("every key types at 1.2 mm again; Rapid Trigger and Snap Tap are off")
    elif cmd == "restore-snapshot":
        with open(app.SNAPSHOT_FILE) as f:
            failed = kb.restore_snapshot(json.load(f))
        print("restored from", app.SNAPSHOT_FILE + (f"; not confirmed: {failed}" if failed else ""))
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (hc.DeviceError, ValueError, KeyError, IndexError, FileNotFoundError) as e:
        sys.exit(f"error: {e}")
