# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Golden bytes for the Huntsman V3 Pro (1532:02A6), the only model checked on hardware.

Every packet each operation sends is compared with tests/golden_02a6.json, recorded from v0.2.0 (master) before multi-model
support was added, including the key tester start/stop and the app's apply_saved / restore_lighting / restore_factory
order. Supporting other models must not change a single byte sent to the 02A6. Regenerate the file
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


class _NoIOKit:
    """DepthSession's IOKit with nothing behind it: Input Monitoring granted, no stream (its thread is replaced)."""

    class iokit:
        IOHIDRequestAccess = staticmethod(lambda _: True)


def _key_tester(kb):
    """DepthSession start then stop: 00:04 driver mode, then 00:04 hardware mode and the 00:84 read-back."""
    run_stream, make_io = depth_stream.DepthSession._run, depth_stream._IOKit
    depth_stream.DepthSession._run = lambda self, io, ready, failure: ready.set()
    depth_stream._IOKit = _NoIOKit
    try:
        s = depth_stream.DepthSession(kb, lambda batch: None, lambda reason, ok: None)
        assert s.start() is True
        assert s.stop() is True
    finally:
        depth_stream.DepthSession._run, depth_stream._IOKit = run_stream, make_io


SAVED = {"custom": {"base": [1, 2, 3], "keys": {"31": [10, 20, 30], "110": [255, 0, 0]}},
         "rapid": {"enabled": True, "press": 0.3, "release": 0.5, "keys": "all", "continuous": True},
         "snap": [31, 33], "effect": None}


def _app(fn):
    """Run fn(app, kb) with state.json in a temporary folder (restore_factory writes it)."""
    import tempfile

    import app

    def scenario(kb):
        old = app.STATE_FILE
        with tempfile.TemporaryDirectory() as d:
            app.STATE_FILE = os.path.join(d, "state.json")
            try:
                fn(app, kb)
            finally:
                app.STATE_FILE = old
    return scenario


def _app_restore_factory(app, kb):
    try:
        app.restore_factory(kb)
    except hc.DeviceError:
        pass   # FakeTransport doesn't store every key's factory depth; the packets are what matters


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
    "key_tester_start_stop": _key_tester,
    "app_apply_saved": _app(lambda app, kb: app.apply_saved(kb, SAVED)),
    "app_apply_saved_rapid_some": _app(lambda app, kb: app.apply_saved(kb, {
        "custom": None, "snap": None,
        "rapid": {"enabled": True, "press": 1.0, "release": 0.2, "keys": [31, 32], "continuous": False}})),
    "app_restore_lighting_custom": _app(lambda app, kb: app.restore_lighting(kb, SAVED)),
    "app_restore_lighting_effect": _app(lambda app, kb: app.restore_lighting(kb, {
        "custom": None, "effect": {"name": "wave", "speed": 40, "direction": "left"}})),
    "app_restore_lighting_firmware": _app(lambda app, kb: app.restore_lighting(kb, {"custom": None, "effect": None})),
    "app_restore_factory": _app(_app_restore_factory),
}


def _digest(value):
    import hashlib
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def effect_frames():
    """Every Studio effect with its defaults on the 02A6 layout, at a few times, with sound, presses and heat:
    {effect: sha256 of the frames}. The row count the audio and ambient effects use must stay 6 on the 02A6."""
    from lighting.effects import REGISTRY, AudioState, KeyEvent, RenderContext, create
    from lighting.frame import Keymap
    km = Keymap(hc.load_layout())
    out = {}
    for name in sorted(REGISTRY):
        r = create(name)
        frames = []
        for t in (0.0, 0.95, 2.37, 7.5, 31.2):
            ctx = RenderContext(keymap=km, keys=km.ids, params={},
                                audio=AudioState(level=0.6, bands=[i / 15 for i in range(16)]),
                                events=[KeyEvent(31, True, 0.9), KeyEvent(61, True, 2.3), KeyEvent(31, False, 2.35)],
                                heat={31: 5, 61: 2, 110: 9})
            frames.append(sorted([k, list(v)] for k, v in r.render(t, ctx).items()))
        out[name] = _digest(frames)
    return out


def preset_packets():
    """Every built-in Studio preset streamed by the engine to a 02A6 (FakeTransport): {preset: sha256 of the
    packets of three frames}."""
    from lighting.engine import Engine
    from lighting.frame import KeyEvent, Keymap
    from lighting.presets import builtin_presets
    km = Keymap(hc.load_layout())
    out = {}
    for preset in builtin_presets(km):
        t = FastFake()
        eng = Engine(lambda: hc.Keyboard(t), km, fps=30)
        eng.set_preset(preset)
        eng.push_key_event(KeyEvent(31, True, 1.0))
        for now in (1.05, 1.4, 3.0):
            eng.step(now)
        out[preset.name] = _digest([r.hex() for r in t.sent])
    return out


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
        "effect_frames": effect_frames(),
        "preset_packets": preset_packets(),
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


def test_02a6_studio_effect_frames_are_unchanged(golden):
    assert effect_frames() == golden["effect_frames"]


def test_02a6_studio_preset_packets_are_unchanged(golden):
    assert preset_packets() == golden["preset_packets"]


def test_02a6_layout_is_layout_json():
    with open(os.path.join(os.path.dirname(HERE), "layout.json")) as f:
        assert hc.load_layout() == json.load(f)


if __name__ == "__main__":
    with open(GOLDEN, "w") as f:
        json.dump(record(), f, indent=0)
        f.write("\n")
    print(f"wrote {GOLDEN}")
