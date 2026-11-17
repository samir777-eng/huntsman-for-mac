# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The Huntsman models the app can open, in the order it looks for them.

Only the Huntsman V3 Pro (1532:02A6) is checked on hardware ("verified"). Every other model is "experimental": it
gets only commands already verified on the 02A6, and writes need the user's Experimental support switch
(huntsman_core.gate). Sources: OpenRazer master cd5c424 (matrix sizes, 0F:03 frame form), janeblower/easyrazer
(analog support, layouts, V2 Analog 8x23 frame), cloned 2026-11-17.

Layouts (layouts/<PID>.json, same format as layout.json) and where their LED (row, column) cells come from:
- 02A6: layout.json, every LED checked on hardware.
- 02CF, 026C (6x22): the 02A6 layout with the 02A6 LEDs. Same key set and matrix size; unconfirmed.
- 0266 V2 Analog (8x23): the 02A6 layout and LEDs. easyrazer's V2 Analog frame map (measured on that keyboard)
  puts the keys in rows 0-5 at exactly the 02A6 cells; rows 6 and 7 are the case edge and wrist rest and (0, 18),
  (0, 21) the media keys and dial, which have no key id and are only reachable with the LED check. Unconfirmed here.
- 02A7 V3 Pro TKL (6x22, easyrazer's 84-key pro TKL layout) and 026B V2 TKL (6x18, easyrazer's 87-key TKL layout):
  each key keeps the 02A6 LED of the same key (the TKL boards are the full board minus the numpad, and every
  remaining 02A6 cell is at column 17 or lower, so it fits 6x18). Guess, unconfirmed.
- 02B0 V3 Pro Mini (5x15, easyrazer's 61-key layout): no function row, so each key takes the 02A6 LED of the key at
  the same physical spot one row up: (row - 1, column), Esc where the tilde is. The 02A6 main block uses columns
  1-14, which fits 15 columns. Guess, unconfirmed.
"""
import dataclasses

VERIFIED, EXPERIMENTAL = "verified", "experimental"

# Firmware effects verified on the 02A6 (huntsman_core.EFFECTS). Other models get these and nothing new.
V3_EFFECTS = ("off", "static", "breathing_one", "breathing_two", "breathing_random", "spectrum", "wave",
              "reactive_key_one", "reactive_key_random", "starlight_random", "starlight_one", "starlight_two")
NO_STARLIGHT = tuple(e for e in V3_EFFECTS if not e.startswith("starlight"))

# Features a write can need (huntsman_core.gate). "lighting" (firmware effects, brightness) every model has.
FEATURES = ("lighting", "per_key", "studio", "actuation", "rapid", "snap_tap", "key_tester")


@dataclasses.dataclass(frozen=True)
class Model:
    pid: int
    name: str
    rows: int                 # lighting matrix (0F:03 frame) size
    cols: int
    layout: str               # layout file, relative to the code folder
    effects: tuple            # firmware effect names (keys of huntsman_core.EFFECTS)
    status: str               # VERIFIED or EXPERIMENTAL
    actuation: bool           # 02:12 actuation / release points
    rapid: bool               # 02:1A Rapid Trigger, 02:20 continuous
    snap_tap: bool            # 02:21
    key_tester: bool          # driver mode 00:04 + depth report; never offered on an experimental model
    per_key: bool = True      # 0F:03 frames and the custom effect
    studio: bool = True       # app-drawn effects (needs per_key)
    frame_size: int = 0x47    # 0F:03 size field: OpenRazer's 0x47 (5 + 22 x 3), longer only for 23 columns
    leds: str = ""            # where the layout's LED cells come from

    lighting = True

    @property
    def verified(self):
        return self.status == VERIFIED

    @property
    def experimental(self):
        return not self.verified

    @property
    def matrix(self):
        return self.rows, self.cols

    def has(self, feature):
        if feature not in FEATURES:
            raise ValueError(f"unknown feature {feature!r}")
        return bool(getattr(self, feature))

    def info(self):
        """Plain dict for the interface and the CLI."""
        return {"pid": f"{self.pid:04X}", "name": self.name, "status": self.status, "matrix": [self.rows, self.cols],
                "effects": list(self.effects), "features": {f: self.has(f) for f in FEATURES}, "leds": self.leds}


_V3 = dict(effects=V3_EFFECTS, actuation=True, rapid=True, snap_tap=True)
_V2 = dict(effects=V3_EFFECTS, actuation=False, rapid=False, snap_tap=False, key_tester=False)

MODELS = {m.pid: m for m in (
    Model(0x02A6, "Huntsman V3 Pro", 6, 22, "layout.json", status=VERIFIED, key_tester=True,
          leds="checked on hardware", **_V3),
    Model(0x02A7, "Huntsman V3 Pro TKL", 6, 22, "layouts/02A7.json", status=EXPERIMENTAL, key_tester=False,
          leds="guess: same LED as the V3 Pro key", **_V3),
    Model(0x02CF, "Huntsman V3 Pro 8KHz", 6, 22, "layouts/02CF.json", status=EXPERIMENTAL, key_tester=False,
          leds="guess: V3 Pro layout", **_V3),
    Model(0x02B0, "Huntsman V3 Pro Mini", 5, 15, "layouts/02B0.json", status=EXPERIMENTAL, key_tester=False,
          leds="guess: V3 Pro LED of the key at the same spot, one row up", **_V3),
    Model(0x026C, "Huntsman V2", 6, 22, "layouts/026C.json", status=EXPERIMENTAL,
          leds="guess: V3 Pro layout", **_V2),
    Model(0x026B, "Huntsman V2 TKL", 6, 18, "layouts/026B.json", status=EXPERIMENTAL,
          leds="guess: same LED as the V3 Pro key", **_V2),
    Model(0x0266, "Huntsman V2 Analog", 8, 23, "layouts/0266.json", status=EXPERIMENTAL, frame_size=5 + 23 * 3,
          leds="easyrazer's V2 Analog frame map (same cells as the V3 Pro); unconfirmed here",
          **dict(_V2, effects=NO_STARLIGHT)),
)}

DEFAULT = MODELS[0x02A6]


def by_pid(pid):
    """The Model for a USB product id, or None if it isn't supported."""
    return MODELS.get(int(pid))
