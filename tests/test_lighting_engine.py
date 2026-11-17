# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Engine against a fake keyboard: change-only sends, fps, pause, stop/restore, error back-off, previews."""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import huntsman_core as hc  # noqa: E402
from lighting.engine import Engine  # noqa: E402
from lighting.frame import KeyEvent, Keymap  # noqa: E402
from lighting.layers import Layer  # noqa: E402
from lighting.presets import Preset  # noqa: E402

KM = Keymap.load()
W = KM.by_name("W").id


class FakeKb:
    def __init__(self, delay=0.0):
        self.frames, self.modes, self.fail, self.delay = [], 0, 0, delay
        self.sending = False

    def send_frame_fast(self, rows):
        if self.fail:
            self.fail -= 1
            raise hc.DeviceError("unplugged")
        self.sending = True
        if self.delay:
            time.sleep(self.delay)
        self.frames.append([[list(c) for c in r] for r in rows])
        self.sending = False

    def enter_custom_mode(self):
        self.modes += 1


def preset(effect="solid", params=None, brightness=1.0):
    return Preset(name="p", brightness=brightness,
                  layers=[Layer(id="a", effect=effect, params=params or {"color": [128, 64, 0]})])


def make(**kw):
    kb = kw.pop("kb", None) or FakeKb()
    eng = Engine(lambda: kb, KM, **kw)
    return eng, kb


def test_first_frame_enters_custom_mode_with_gamma_at_the_sink():
    eng, kb = make()
    eng.set_preset(preset())
    assert eng.step(1.0) is True
    assert kb.modes == 1 and len(kb.frames) == 1
    r, c = KM.key(W).led
    assert kb.frames[0][r][c] == hc.gamma([128, 64, 0])
    unused = [(r, c) for r in range(hc.FRAME_ROWS) for c in range(hc.FRAME_COLS)
              if (r, c) not in {k.led for k in KM.keys}]
    assert all(kb.frames[0][r][c] == [0, 0, 0] for r, c in unused)


def test_identical_frames_are_not_resent():
    eng, kb = make()
    eng.set_preset(preset())
    for i in range(10):
        eng.step(1.0 + i / 30)
    assert len(kb.frames) == 1 and kb.modes == 1


def test_changed_frames_are_sent():
    eng, kb = make()
    eng.set_preset(preset("rainbow", {"speed": 1.0}))
    for i in range(5):
        eng.step(1.0 + i / 10)
    assert len(kb.frames) == 5 and kb.modes == 1


def test_nothing_is_sent_without_a_preset():
    eng, kb = make()
    assert eng.step(1.0) is False and kb.frames == [] and kb.modes == 0


def test_brightness_scales_before_gamma():
    eng, kb = make()
    eng.set_preset(preset(params={"color": [200, 100, 0]}, brightness=0.5))
    eng.set_brightness(0.5)
    eng.step(1.0)
    r, c = KM.key(W).led
    assert kb.frames[-1][r][c] == hc.gamma([50, 25, 0])
    with pytest.raises(ValueError):
        eng.set_brightness(1.5)


def test_key_events_reach_reactive_layers():
    eng, kb = make()
    eng.set_preset(preset("reactive_afterglow", {"color": [255, 255, 255], "fade": 1.0}))
    eng.step(1.0)
    r, c = KM.key(W).led
    assert kb.frames[-1][r][c] == [0, 0, 0]
    eng.push_key_event(KeyEvent(W, True, 1.01))
    eng.step(1.02)
    assert kb.frames[-1][r][c] != [0, 0, 0]


def test_heat_counts_only_when_enabled():
    eng, _ = make()
    eng.push_key_event(KeyEvent(W, True, 0.0))
    assert eng.heat_counts() == {}
    eng.set_heat_enabled(True)
    eng.push_key_event(KeyEvent(W, True, 0.1))
    eng.push_key_event(KeyEvent(W, False, 0.2))
    eng.push_key_event(KeyEvent(W, True, 0.3))
    assert eng.heat_counts() == {W: 2}
    eng.set_heat({W: 7})
    assert eng.heat_counts() == {W: 7}
    eng.reset_heat()
    assert eng.heat_counts() == {}


def test_audio_reaches_audio_layers():
    from lighting.frame import AudioState
    eng, kb = make()
    eng.set_preset(preset("audio_pulse", {"colors": [[255, 255, 255]], "sensitivity": 1.0}))
    eng.step(1.0)
    eng.set_audio(AudioState(1.0, [1.0] * 16))
    eng.step(1.1)
    r, c = KM.key(W).led
    assert kb.frames[-1][r][c] == [255, 255, 255]


def test_pause_stops_sending_and_resume_reenters_custom_mode():
    eng, kb = make()
    eng.set_preset(preset("rainbow", {"speed": 1.0}))
    eng.step(1.0)
    with eng.paused():
        assert eng.step(1.1) is False and eng.step(1.2) is False
        with eng.paused():  # nests
            pass
        assert eng.step(1.25) is False
    assert len(kb.frames) == 1
    eng.step(1.3)
    assert len(kb.frames) == 2 and kb.modes == 2  # another device call may have changed the effect


def test_pause_waits_for_the_frame_in_flight():
    eng, kb = make(kb=FakeKb(delay=0.15))
    eng.set_preset(preset())
    t = threading.Thread(target=eng.step, args=(1.0,))
    t.start()
    while not kb.sending:
        time.sleep(0.001)
    eng.pause()
    assert kb.sending is False and len(kb.frames) == 1
    eng.resume()
    t.join()


def test_errors_back_off_report_and_recover():
    errors = []
    eng, kb = make(on_error=errors.append, backoff=(0.5, 2.0))
    eng.set_preset(preset())
    kb.fail = 3
    assert eng.step(0.0) is False                # fail 1 -> retry at 0.5
    assert eng.step(0.2) is False and kb.fail == 2  # still backing off: no attempt
    eng.step(0.5)                                # fail 2 -> retry at 1.5
    eng.step(1.0)
    assert kb.fail == 1
    eng.step(1.5)                                # fail 3 -> retry at 3.5
    eng.step(3.0)
    assert kb.fail == 0 and kb.frames == []
    assert eng.step(3.5) is True and len(kb.frames) == 1 and kb.modes == 1
    assert len(errors) == 3 and all(isinstance(e, hc.DeviceError) for e in errors)


def test_keyboard_factory_errors_are_backed_off_too():
    errors, calls = [], []

    def factory():
        calls.append(1)
        raise hc.DeviceError("not found")
    eng = Engine(factory, KM, on_error=errors.append, backoff=(1.0, 4.0))
    eng.set_preset(preset())
    for i in range(20):
        eng.step(i * 0.1)  # 2 s of frames
    assert len(calls) == 2 and len(errors) == 2


def test_on_frame_is_throttled_and_gets_the_composed_frame():
    eng, _ = make()
    got = []
    eng.on_frame(lambda f: got.append((f)))
    eng.set_preset(preset("rainbow", {"speed": 1.0}))
    for i in range(60):  # one second at 60 fps
        eng.step(1.0 + i / 60)
    assert 13 <= len(got) <= 16
    assert set(got[0]) == set(KM.ids) and all(len(c) == 3 for c in got[0].values())


def test_on_frame_gets_the_preview_while_paused():
    eng, kb = make()
    got = []
    eng.on_frame(got.append)
    eng.set_preset(preset())
    with eng.paused():
        eng.step(1.0)
    assert len(got) == 1 and kb.frames == []


def test_thread_runs_at_the_target_fps_and_stop_restores():
    restored = []
    eng, kb = make(fps=20, restore=lambda: restored.append(1))
    eng.set_preset(preset("rainbow", {"speed": 2.0}))
    eng.start()
    time.sleep(0.5)
    eng.stop()
    n = len(kb.frames)
    assert 5 <= n <= 12
    assert restored == [1]
    time.sleep(0.1)
    assert len(kb.frames) == n  # nothing after stop


def test_stop_without_restore():
    restored = []
    eng, _ = make(restore=lambda: restored.append(1))
    eng.start()
    eng.stop(restore=False)
    assert restored == []


def test_restore_errors_are_reported():
    errors = []

    def boom():
        raise hc.DeviceError("gone")
    eng, _ = make(restore=boom, on_error=errors.append)
    eng.start()
    eng.stop()
    assert len(errors) == 1


def test_fps_is_bounded():
    with pytest.raises(ValueError):
        Engine(lambda: FakeKb(), KM, fps=0)
    with pytest.raises(ValueError):
        Engine(lambda: FakeKb(), KM, fps=500)


def test_push_key_event_accepts_hid_usage_events_from_inputs():
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class UsageEvent:  # the shape of inputs.types.KeyEvent: HID usage instead of key id
        usage: int
        down: bool
        t: float

    eng, kb = make()
    eng.set_heat_enabled(True)
    eng.set_preset(preset("reactive_afterglow", {"color": [255, 255, 255], "fade": 1.0}))
    eng.push_key_event(UsageEvent(0x1A, True, 1.0))   # W
    eng.push_key_event(UsageEvent(0x64, True, 1.0))   # not on this layout: ignored
    eng.step(1.01)
    r, c = KM.key(W).led
    assert kb.frames[-1][r][c] != [0, 0, 0]
    assert eng.heat_counts() == {W: 1}
