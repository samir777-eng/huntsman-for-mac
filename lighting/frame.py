# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Frames, the key map, shared input records and colour helpers.

A Frame maps key id -> (r, g, b), each 0..255, in picker (sRGB) values: gamma correction happens once,
where the frame is sent to the keyboard (lighting.engine).
"""
import colorsys
import math
from dataclasses import dataclass, field

import huntsman_core as hc
from lighting.hid_usage import USAGE_TO_NAME

RGB = tuple[int, int, int]
Frame = dict[int, RGB]
BLACK: RGB = (0, 0, 0)
WHITE: RGB = (255, 255, 255)


@dataclass(frozen=True)
class KeyEvent:
    """A key press (down=True) or release; t on the time.monotonic() clock, like the engine's frames."""
    key_id: int
    down: bool
    t: float


@dataclass(frozen=True)
class AudioState:
    """level: overall loudness 0..1; bands: 16 log-spaced bands, low to high, each 0..1."""
    level: float = 0.0
    bands: list[float] = field(default_factory=lambda: [0.0] * 16)


@dataclass(frozen=True)
class KeyInfo:
    id: int
    name: str
    label: str
    x: float
    y: float
    w: float
    h: float
    row: int            # LED row 0..5 (0 = function row, 5 = bottom row)
    led: tuple[int, int]


class Keymap:
    """The physical keys from layout.json, in layout order. Positions are in key units."""

    def __init__(self, layout):
        self.keys = [KeyInfo(int(k["id"]), k["name"], k.get("label", k["name"]), float(k["x"]), float(k["y"]),
                             float(k["w"]), float(k["h"]), int(k["led"][0]), (int(k["led"][0]), int(k["led"][1])))
                     for k in layout]
        self.ids = [k.id for k in self.keys]
        self._by_id = {k.id: k for k in self.keys}
        self._by_name = {k.name: k for k in self.keys}
        self._centers = {k.id: (k.x + k.w / 2, k.y + k.h / 2) for k in self.keys}
        self.bounds = (max((k.x + k.w for k in self.keys), default=0.0),
                       max((k.y + k.h for k in self.keys), default=0.0))

    @classmethod
    def load(cls):
        return cls(hc.load_layout())

    def __contains__(self, key_id):
        return key_id in self._by_id

    def key(self, key_id) -> KeyInfo:
        return self._by_id[key_id]

    def by_name(self, name):
        return self._by_name.get(name)

    def center(self, key_id):
        return self._centers[key_id]

    def by_hid_usage(self, usage):
        """HID usage page 7 code -> key id, or None when the usage or the named key isn't on this layout."""
        key = self._by_name.get(USAGE_TO_NAME.get(usage, ""))
        return key.id if key else None


# ---------- colour helpers (all return (r, g, b) ints 0..255) ----------

def clamp8(v) -> int:
    return 0 if v <= 0 else 255 if v >= 255 else int(v + 0.5)


def rgb(c) -> RGB:
    return (clamp8(c[0]), clamp8(c[1]), clamp8(c[2]))


def lerp(a, b, t) -> RGB:
    t = 0.0 if t <= 0 else 1.0 if t >= 1 else t
    return (clamp8(a[0] + (b[0] - a[0]) * t), clamp8(a[1] + (b[1] - a[1]) * t), clamp8(a[2] + (b[2] - a[2]) * t))


def scale(c, f) -> RGB:
    return (clamp8(c[0] * f), clamp8(c[1] * f), clamp8(c[2] * f))


def sample(colors, t, loop=False) -> RGB:
    """Colour at position t along a palette. loop=True wraps (period 1) back to the first colour."""
    n = len(colors)
    if n == 1:
        return rgb(colors[0])
    if loop:
        pos = (t % 1.0) * n
        i = int(pos) % n
        return lerp(colors[i], colors[(i + 1) % n], pos - int(pos))
    t = 0.0 if t <= 0 else 1.0 if t >= 1 else t
    pos = t * (n - 1)
    i = min(int(pos), n - 2)
    return lerp(colors[i], colors[i + 1], pos - i)


def hsv(h, s, v) -> RGB:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (clamp8(r * 255), clamp8(g * 255), clamp8(b * 255))


def smoothstep(x) -> float:
    x = 0.0 if x <= 0 else 1.0 if x >= 1 else x
    return x * x * (3 - 2 * x)


PALETTES = {
    "rainbow": [(255, 0, 0), (255, 160, 0), (255, 255, 0), (0, 255, 0), (0, 160, 255), (0, 0, 255), (160, 0, 255)],
    "fire": [(255, 0, 0), (255, 96, 0), (255, 200, 0)],
    "aurora": [(0, 255, 120), (0, 200, 255), (120, 60, 255), (0, 255, 200)],
    "ocean": [(0, 30, 120), (0, 120, 255), (0, 220, 220)],
    "heat": [(0, 0, 255), (0, 255, 0), (255, 255, 0), (255, 0, 0)],
    "spectrum": [(0, 255, 0), (255, 255, 0), (255, 0, 0)],
    "sunset": [(255, 60, 0), (255, 0, 120), (120, 0, 255)],
    "synthwave": [(255, 0, 200), (0, 200, 255), (120, 0, 255)],
}


def dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
