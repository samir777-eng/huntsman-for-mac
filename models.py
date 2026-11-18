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

Actuation scales (Scale): each model with actuation maps a threshold byte (02:12 / 02:92, byte 3 actuation, byte 4
release) to millimetres on its own scale. The V3 family: the 02A6's scale, verified on hardware. The V2 Analog: easyrazer
53a3dd3 (docs/en/devices/huntsman-v2-analog/protocol.md "Actuation", firmware.md "Sensors and actuation",
crates/core/devices/1532-0266.json): mm = thr/255 x 2.1 + 1.5; the firmware clamps the actuation byte to 15-250
(1.62-3.56 mm, only the 250 end checked on hardware by easyrazer) and the release byte to 5..actuation-10 (from the
firmware code, unverified). Its key ids are easyrazer's 0266 keymap (crates/core/src/keymap.rs), which keymap.json
and layouts/0266.json already use (tests/test_v2_analog.py checks every key). No factory point is known for it.
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
class Scale:
    """Threshold byte <-> mm for one model's actuation and release points, and the range the app offers."""
    zero_mm: float            # mm at threshold 0
    full_mm: float            # mm at threshold 255
    min_mm: float             # offered actuation range, in steps of `step`
    max_mm: float
    decimals: int             # step = 10 ** -decimals mm
    min_thr: int              # lowest / highest actuation byte written
    max_thr: int
    min_rel: int              # lowest release byte written
    min_gap: int              # the release byte sits at least this far below the actuation byte
    units_gap: bool           # default release: min_gap bytes below (V3, Synapse's 76/70), else reset_gap mm above
    firmware_clamps: bool     # reads report the points the firmware uses (it clamps the stored bytes)
    factory: tuple = None     # (actuation, release) bytes of the factory depth, or None if it isn't known
    factory_mm: float = None  # the offered value that writes exactly the factory actuation byte
    presets: tuple = ()       # (name, mm) buttons in the window
    reset_gap: float = 0.1    # "Just above": the reset point this far above the actuation point, in mm

    @property
    def step(self):
        return round(10 ** -self.decimals, self.decimals)

    def _units(self, mm):
        return round((mm - self.zero_mm) / (self.full_mm - self.zero_mm) * 255)

    def mm(self, t):
        return round(self.zero_mm + t * (self.full_mm - self.zero_mm) / 255, self.decimals)

    def threshold(self, mm):
        """Actuation byte for a point in the offered range (rounded to the step), else ValueError."""
        mm = round(float(mm), self.decimals)
        if not self.min_mm <= mm <= self.max_mm:
            d = self.decimals
            raise ValueError(f"{mm} mm is outside {self.min_mm:.{d}f}-{self.max_mm:.{d}f}")
        if self.factory and mm == self.factory_mm:   # keep the preset and "factory" identical
            return self.factory[0]
        return max(self.min_thr, min(self.max_thr, self._units(mm)))

    def release(self, thr, release_mm=None):
        """Release byte for an actuation byte: explicit, or the default (see units_gap). Never below min_rel."""
        if thr < self.min_thr:
            raise ValueError(f"actuation threshold {thr} is below the minimum {self.min_thr}")
        if release_mm is None:
            if self.units_gap:
                return thr - self.min_gap
            release_mm = max(self.mm(self.min_rel), round(self.mm(thr) - self.reset_gap, self.decimals))
        rel = max(self.min_rel, min(255, self._units(float(release_mm))))
        top = thr - self.min_gap
        if top < rel < thr:  # within one step of the limit (e.g. 3.9 at 4.0): clamp
            rel = top
        if rel > top:
            gap = round(self.min_gap * (self.full_mm - self.zero_mm) / 255, self.decimals)
            raise ValueError(f"release point must sit at least {gap} mm above the actuation point")
        return rel

    def effective(self, thr, rel):
        """The (actuation, release) bytes the keyboard acts on for the stored ones."""
        if not self.firmware_clamps:
            return thr, rel
        thr = max(self.min_thr, min(self.max_thr, thr))
        return thr, max(self.min_rel, min(thr - self.min_gap, rel))

    def info(self):
        """For the window: slider range and step, reset point, factory depth (None: not offered), presets."""
        return {"min": self.min_mm, "max": self.max_mm, "step": self.step, "decimals": self.decimals,
                "release_min": self.mm(self.min_rel), "reset_gap": self.reset_gap, "factory": self.factory_mm,
                "presets": [list(p) for p in self.presets]}


# The 02A6's scale (huntsman_core: FULL_MM, MIN_THR, RELEASE_GAP, FACTORY_THR/REL), verified on hardware.
V3_SCALE = Scale(zero_mm=0, full_mm=255 * 256 / 16380, min_mm=0.1, max_mm=4.0, decimals=1, min_thr=7, max_thr=255,
                 min_rel=1, min_gap=6, units_gap=True, firmware_clamps=False, factory=(76, 70), factory_mm=1.2,
                 presets=(("Light", 0.5), ("Gaming", 1.0), ("Factory", 1.2), ("Balanced", 1.5), ("Typing", 2.0),
                          ("Firm", 3.0)))
# The V2 Analog's (easyrazer, see the docstring). 0.01 mm steps: each is its own byte (1 byte = 0.0082 mm) and
# survives a read-back. Unverified here.
V2_ANALOG_SCALE = Scale(zero_mm=1.5, full_mm=3.6, min_mm=1.62, max_mm=3.56, decimals=2, min_thr=15, max_thr=250,
                        min_rel=5, min_gap=10, units_gap=False, firmware_clamps=True,
                        presets=(("Lightest", 1.62), ("Gaming", 2.0), ("Balanced", 2.5), ("Typing", 3.0),
                                 ("Deepest", 3.56)))


@dataclasses.dataclass(frozen=True)
class Model:
    pid: int
    name: str
    rows: int                 # lighting matrix (0F:03 frame) size
    cols: int
    layout: str               # layout file, relative to the code folder
    effects: tuple            # firmware effect names (keys of huntsman_core.EFFECTS)
    status: str               # VERIFIED or EXPERIMENTAL
    actuation: bool           # 02:12 actuation / release points, on `scale`
    rapid: bool               # 02:1A Rapid Trigger, 02:20 continuous
    snap_tap: bool            # 02:21
    key_tester: bool          # driver mode 00:04 + depth report; never offered on an experimental model
    per_key: bool = True      # 0F:03 frames and the custom effect
    studio: bool = True       # app-drawn effects (needs per_key)
    frame_size: int = 0x47    # 0F:03 size field: OpenRazer's 0x47 (5 + 22 x 3), longer only for 23 columns
    leds: str = ""            # where the layout's LED cells come from
    scale: Scale = V3_SCALE   # actuation scale and offered range (used only when actuation is True)

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
                "effects": list(self.effects), "features": {f: self.has(f) for f in FEATURES}, "leds": self.leds,
                "actuation": self.scale.info() if self.actuation else None}


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
          scale=V2_ANALOG_SCALE, **dict(_V2, effects=NO_STARLIGHT, actuation=True)),
)}

DEFAULT = MODELS[0x02A6]


def by_pid(pid):
    """The Model for a USB product id, or None if it isn't supported."""
    return MODELS.get(int(pid))
