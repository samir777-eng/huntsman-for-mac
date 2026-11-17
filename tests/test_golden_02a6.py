# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Golden bytes for the Huntsman V3 Pro (1532:02A6), the only model checked on hardware.

Every packet each operation sends is compared with tests/golden_02a6.json, recorded from v0.2.0 before multi-model
support was added. Supporting other models must not change a single byte sent to the 02A6. Regenerate the file
(python tests/test_golden_02a6.py) only for a deliberate, hardware-checked protocol change."""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import depth_stream  # noqa: E402
import huntsman_core as hc  # noqa: E402
from test_core import FakeTransport  # noqa: E402

GOLDEN = os.path.join(HERE, "golden_02a6.json")
SOME_KEYS = [110, 31, 32, 33, 61, 79, 90]


class FastFake(FakeTransport):
    def exchange_fast(self, reports):
        return [self.exchange(r) for r in reports]


def _frame():
    return [[[(r * 40 + c) % 256, c * 11 % 256, r * 7] for c in range(22)] for r in range(6)]


def _snapshot_roundtrip(kb):
    kb.set_actuation([31], 2.0)
    snap = kb.snapshot(SOME_KEYS)
    kb.restore_snapshot(snap)


SCENARIOS = {
    "reads": lambda kb: (kb.firmware(), kb.active_profile(), kb.get_effect_raw(), kb.brightness(),
                         kb.read_points(31), kb.read_points(31, 1)),
    "actuation": lambda kb: kb.set_actuation([31, 32, 110], 2.0),
    "actuation_release": lambda kb: kb.set_actuation([33], 1.5, 1.0),
    "restore_factory": lambda kb: kb.restore_factory([31, 32]),
    "rapid_on": lambda kb: kb.set_rapid([(31, (0.3, 0.4)), (32, None), (33, (1.0, 2.5))]),
    "rapid_off_everywhere": lambda kb: kb.set_rapid([(k, None) for k in hc.every_key_id()]),
    "continuous": lambda kb: (kb.set_continuous(True), kb.set_continuous(False)),
    "snap_tap": lambda kb: (kb.set_snap_tap((31, 33)), kb.set_snap_tap(None)),
    "effects": lambda kb: [
        kb.set_effect("off"),
        kb.set_effect("static", [255, 128, 0]),
        kb.set_effect("static", [10, 20, 30], correct=False, store=0),
        kb.set_effect("breathing_one", [0, 200, 100]),
        kb.set_effect("breathing_two", [255, 0, 0], [0, 0, 255]),
        kb.set_effect("breathing_random"),
        kb.set_effect("spectrum"),
        kb.set_effect("wave", speed=40, direction="left"),
        kb.set_effect("wave", speed=200, direction="right"),
        kb.set_effect("reactive_key_one", [1, 2, 3]),
        kb.set_effect("reactive_key_random"),
        kb.set_effect("starlight_random", speed=1),
        kb.set_effect("starlight_one", [9, 8, 7], speed=2),
        kb.set_effect("starlight_two", [9, 8, 7], [70, 80, 90], speed=3),
    ],
    "brightness": lambda kb: (kb.set_brightness(55), kb.set_brightness(30, stores=(0,)), kb.set_brightness(100)),
    "custom": lambda kb: kb.set_custom({31: [10, 20, 30], 110: [255, 0, 0], 59: [0, 255, 0]}, hc.load_layout(),
                                       base=[1, 2, 3]),
    "custom_uncorrected": lambda kb: kb.set_custom({90: [128, 128, 128]}, hc.load_layout(), correct=False),
    "enter_custom_mode": lambda kb: kb.enter_custom_mode(),
    "frame_fast": lambda kb: kb.send_frame_fast(_frame()),
    "snapshot": lambda kb: kb.snapshot(SOME_KEYS),
    "snapshot_restore": _snapshot_roundtrip,
    "recover_typing": lambda kb: depth_stream.recover_typing(kb),
}


def run(name):
    t = FastFake()
    t.mode = depth_stream.MODE_DRIVER
    SCENARIOS[name](hc.Keyboard(t))
    return [r.hex() for r in t.sent]


def record():
    return {
        "packets": {name: run(name) for name in SCENARIOS},
        "frame_rows": hc.frame_rows({31: [1, 2, 3], 110: [4, 5, 6], 104: [7, 8, 9]}, hc.load_layout(), (0, 0, 1)),
        "every_key_id": hc.every_key_id(),
        "all_key_ids": hc.all_key_ids(),
        "effects": sorted(hc.EFFECTS),
        "frame": [hc.FRAME_ROWS, hc.FRAME_COLS, hc.FRAME_SIZE],
    }


@pytest.fixture(scope="module")
def golden():
    with open(GOLDEN) as f:
        return json.load(f)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_02a6_packets_are_unchanged(golden, name):
    assert run(name) == golden["packets"][name]


def test_02a6_frames_keys_and_effects_are_unchanged(golden):
    now = json.loads(json.dumps(record()))
    for field in ("frame_rows", "every_key_id", "all_key_ids", "effects", "frame"):
        assert now[field] == golden[field], field


def test_02a6_layout_is_layout_json():
    with open(os.path.join(os.path.dirname(HERE), "layout.json")) as f:
        assert hc.load_layout() == json.load(f)


if __name__ == "__main__":
    with open(GOLDEN, "w") as f:
        json.dump(record(), f, indent=0)
        f.write("\n")
    print(f"wrote {GOLDEN}")
