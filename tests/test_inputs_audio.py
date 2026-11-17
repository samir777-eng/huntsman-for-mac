# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Audio analysis on synthetic input: band layout, sine placement, silence, noise, smoothing, auto-gain."""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from inputs import audio  # noqa: E402
from inputs.types import AudioState  # noqa: E402

SR = 48000
N = 1024


def sine(freq, amp=0.5, n=N, sr=SR, start=0):
    """Block number `start` of a continuous sine (consecutive blocks join without a phase jump)."""
    t = (np.arange(n) + start * n) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def settle(block, state, times=40, sr=SR):
    """Feed `times` blocks; `block` is an array (repeated) or a function of the block number."""
    out = None
    for i in range(times):
        out = audio.analyse(block(i) if callable(block) else block, sr, state)
    return out


def band_of(freq):
    edges = audio.band_edges()
    for i in range(audio.BANDS):
        if edges[i] <= freq < edges[i + 1]:
            return i
    raise AssertionError(freq)


def test_band_edges_are_log_spaced_from_40_hz_to_16_khz():
    e = audio.band_edges()
    assert len(e) == 17
    assert e[0] == pytest.approx(40.0)
    assert e[-1] == pytest.approx(16000.0)
    ratios = [e[i + 1] / e[i] for i in range(16)]
    assert all(r == pytest.approx(ratios[0]) for r in ratios)


def test_output_shape_and_ranges():
    st = audio.AnalyserState()
    out = audio.analyse(sine(1000), SR, st)
    assert isinstance(out, AudioState)
    assert len(out.bands) == 16
    assert all(0.0 <= b <= 1.0 for b in out.bands)
    assert 0.0 <= out.level <= 1.0


@pytest.mark.parametrize("freq", [60, 250, 1000, 4000, 12000])
def test_a_sine_lights_its_own_band_most(freq):
    st = audio.AnalyserState()
    out = settle(lambda i: sine(freq, start=i), st)
    peak = max(range(16), key=lambda i: out.bands[i])
    assert peak == band_of(freq)
    assert out.bands[peak] > 0.8
    far = [b for i, b in enumerate(out.bands) if abs(i - peak) > 3]
    assert max(far) < 0.35


def test_silence_is_dark():
    st = audio.AnalyserState()
    out = settle(np.zeros(N, dtype=np.float32), st)
    assert out.level == 0.0
    assert max(out.bands) == 0.0


def test_very_quiet_hiss_is_not_boosted_to_full():
    rng = np.random.default_rng(1)
    st = audio.AnalyserState()
    out = settle((rng.standard_normal(N) * 1e-5).astype(np.float32), st)
    assert out.level < 0.1
    assert max(out.bands) < 0.2


def test_noise_spreads_over_many_bands():
    rng = np.random.default_rng(2)
    st = audio.AnalyserState()
    out = None
    for _ in range(40):
        out = audio.analyse((rng.standard_normal(N) * 0.2).astype(np.float32), SR, st)
    assert sum(1 for b in out.bands if b > 0.3) >= 10
    assert out.level > 0.5


def test_stereo_is_mixed_to_mono():
    st1, st2 = audio.AnalyserState(), audio.AnalyserState()
    mono = settle(lambda i: sine(1000, start=i), st1)
    stereo = settle(lambda i: np.stack([sine(1000, start=i)] * 2, axis=1), st2)
    assert stereo.bands == pytest.approx(mono.bands, abs=1e-6)


def test_auto_gain_brings_a_quiet_sine_up():
    st = audio.AnalyserState()
    out = settle(lambda i: sine(1000, amp=0.01, start=i), st, times=200)
    assert out.bands[band_of(1000)] > 0.8


def test_attack_is_fast_and_decay_is_gradual():
    st = audio.AnalyserState()
    settle(lambda i: sine(1000, start=i), st)
    loud = audio.analyse(sine(1000, start=40), SR, st).level
    after_one = audio.analyse(np.zeros(N, dtype=np.float32), SR, st).level
    assert 0.2 * loud < after_one < loud  # falls, but not to zero in one 21 ms block
    for _ in range(100):  # about two seconds of silence
        quiet = audio.analyse(np.zeros(N, dtype=np.float32), SR, st).level
    assert quiet < 0.02


def test_lower_sensitivity_gives_lower_values():
    hi, lo = audio.AnalyserState(sensitivity=1.0), audio.AnalyserState(sensitivity=0.5)
    a = settle(lambda i: sine(1000, start=i), hi)
    b = settle(lambda i: sine(1000, start=i), lo)
    assert b.bands[band_of(1000)] < a.bands[band_of(1000)]


def test_empty_block_returns_current_state():
    st = audio.AnalyserState()
    out = audio.analyse(np.zeros(0, dtype=np.float32), SR, st)
    assert len(out.bands) == 16 and out.level == 0.0


@pytest.mark.parametrize("name,loop", [
    ("BlackHole 2ch", True), ("Loopback Audio", True), ("Soundflower (2ch)", True),
    ("MacBook Pro Microphone", False), ("External Microphone", False),
])
def test_loopback_guess(name, loop):
    assert audio.is_loopback_name(name) is loop


def test_list_input_devices_keeps_inputs_only():
    fake = [
        {"name": "MacBook Pro Microphone", "max_input_channels": 1, "max_output_channels": 0},
        {"name": "MacBook Pro Speakers", "max_input_channels": 0, "max_output_channels": 2},
        {"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2},
    ]
    devs = audio.list_input_devices(query=lambda: fake)
    assert [(d.name, d.index, d.channels, d.is_loopback) for d in devs] == [
        ("MacBook Pro Microphone", 0, 1, False), ("BlackHole 2ch", 2, 2, True)]


def test_silence_watch_flags_digital_silence_only_after_the_grace_time():
    w = audio.SilenceWatch(seconds=3.0)
    zeros = np.zeros(N, dtype=np.float32)
    assert not w.feed(zeros, 0.0)
    assert not w.feed(zeros, 2.9)
    assert w.feed(zeros, 3.1)
    assert not w.feed(zeros, 3.2)  # reported once


def test_silence_watch_is_reset_by_any_sound():
    w = audio.SilenceWatch(seconds=3.0)
    w.feed(np.zeros(N, dtype=np.float32), 0.0)
    w.feed(sine(440, amp=1e-6), 2.0)  # quiet but not digital zero: something is arriving
    assert not w.feed(np.zeros(N, dtype=np.float32), 4.0)


def test_listener_is_not_running_before_start():
    lst = audio.AudioListener(None, lambda s: None)
    assert not lst.running
    lst.stop()


def test_open_failure_is_reported_clearly(monkeypatch):
    class Boom:
        def __init__(self, **kw):
            raise audio.sd.PortAudioError("Error opening InputStream: Internal PortAudio error [PaErrorCode -9986]")

    monkeypatch.setattr(audio.sd, "InputStream", Boom)
    monkeypatch.setattr(audio.sd, "query_devices", lambda *a, **k: {"name": "Mic", "max_input_channels": 1,
                                                                     "default_samplerate": 48000.0})
    lst = audio.AudioListener(None, lambda s: None)
    with pytest.raises(audio.AudioError) as ei:
        lst.start()
    assert "Microphone" in str(ei.value)
    assert not lst.running


def test_math_sanity_of_test_helper():
    assert math.isclose(float(np.max(np.abs(sine(1000)))), 0.5, rel_tol=1e-3)
