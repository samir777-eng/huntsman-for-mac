# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""lighting.frame (Keymap, colour helpers) and lighting.hid_usage."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import huntsman_core as hc  # noqa: E402
from lighting import frame as fr  # noqa: E402
from lighting import hid_usage  # noqa: E402


@pytest.fixture(scope="module")
def km():
    return fr.Keymap.load()


def test_keymap_has_every_layout_key(km):
    layout = hc.load_layout()
    assert len(km.keys) == len(layout) == 104
    w = km.key(18)
    assert (w.name, w.label, w.row, w.led) == ("W", "W", 2, (2, 3))
    assert km.ids == [k.id for k in km.keys]
    assert km.by_name("SPACEBAR").id == 61 and km.by_name("NOPE") is None


def test_keymap_center_and_bounds(km):
    esc = km.key(110)
    assert km.center(110) == (esc.x + esc.w / 2, esc.y + esc.h / 2)
    assert km.bounds == (22.5, 6.25)


@pytest.mark.parametrize("usage,name", [
    (0x1A, "W"), (0x04, "A"), (0x16, "S"), (0x07, "D"), (0x2C, "SPACEBAR"), (0x28, "ENTER"),
    (0x3A, "F1"), (0x45, "F12"), (0x52, "UP_ARROW"), (0x51, "DOWN_ARROW"), (0x50, "LEFT_ARROW"),
    (0x4F, "RIGHT_ARROW"), (0x62, "NUMPAD_0"), (0x59, "NUMPAD_1"), (0x61, "NUMPAD_9"), (0x58, "NUMPAD_ENTER"),
    (0x2D, "HYPEN"), (0x35, "TILDE"), (0xE0, "LEFT_CTRL"), (0xE1, "LEFT_SHIFT"), (0xE6, "RIGHT_ALT"),
])
def test_hid_usage_maps_to_layout_ids(km, usage, name):
    assert hid_usage.USAGE_TO_NAME[usage] == name
    assert km.by_hid_usage(usage) == km.by_name(name).id


def test_hid_usage_covers_the_whole_layout(km):
    assert {k.name for k in km.keys} <= set(hid_usage.USAGE_TO_NAME.values())


def test_hid_usage_unknown_and_missing_names_give_none(km):
    assert km.by_hid_usage(0x00) is None and km.by_hid_usage(0x64) is None
    # RIGHT_GUI (0xE7) resolves only because this layout names a key RIGHT_GUI (the Fn key)
    assert km.by_hid_usage(0xE7) == km.by_name("RIGHT_GUI").id
    small = fr.Keymap([k for k in hc.load_layout() if k["name"] != "RIGHT_GUI"])
    assert small.by_hid_usage(0xE7) is None


def test_lerp_and_clamp():
    assert fr.lerp((0, 0, 0), (255, 100, 10), 0.5) == (128, 50, 5)
    assert fr.lerp((0, 0, 0), (255, 255, 255), 2) == (255, 255, 255)
    assert fr.scale((200, 100, 50), 0.5) == (100, 50, 25)


def test_palette_sampling():
    pal = [(255, 0, 0), (0, 0, 255)]
    assert fr.sample(pal, 0) == (255, 0, 0) and fr.sample(pal, 1) == (0, 0, 255)
    assert fr.sample(pal, 0.5) == (128, 0, 128)
    assert fr.sample(pal, 0.5, loop=True) == (0, 0, 255)  # loop: 0 -> red, .5 -> blue, 1 -> red
    assert fr.sample(pal, 1.0, loop=True) == (255, 0, 0)
    assert fr.sample([(7, 7, 7)], 0.3) == (7, 7, 7)


def test_hsv():
    assert fr.hsv(0, 1, 1) == (255, 0, 0)
    assert fr.hsv(1 / 3, 1, 1) == (0, 255, 0)
    assert fr.hsv(0.5, 0, 0.5) == (128, 128, 128)


def test_named_palettes_are_valid_colour_lists():
    assert {"rainbow", "fire", "aurora", "ocean", "heat", "spectrum"} <= set(fr.PALETTES)
    for pal in fr.PALETTES.values():
        assert 2 <= len(pal) <= 8
        for c in pal:
            hc.check_rgb(list(c))
