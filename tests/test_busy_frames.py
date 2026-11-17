# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Typing makes the keyboard answer 'busy' to frame packets; Studio must skip frames, not report errors."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import huntsman_core as hc  # noqa: E402
from lighting import engine as eng  # noqa: E402
from lighting.frame import Keymap  # noqa: E402
from lighting.layers import Layer  # noqa: E402
from lighting.presets import Preset  # noqa: E402
from test_core import FakeTransport  # noqa: E402


class BusyTransport(FakeTransport):
    def exchange_fast(self, reports):
        out = []
        for r in reports:
            resp = bytearray(r); resp[0] = hc.STATUS_BUSY; resp[88] = hc.crc(resp)
            out.append(bytes(resp))
            break
        return out


def rows():
    return [[[0, 0, 0] for _ in range(hc.FRAME_COLS)] for _ in range(hc.FRAME_ROWS)]


def test_busy_reply_raises_device_busy_not_a_plain_error():
    with pytest.raises(hc.DeviceBusy):
        hc.Keyboard(BusyTransport()).send_frame_fast(rows())


def test_engine_skips_busy_frames_silently_then_reports_after_a_second():
    errors = []
    km = Keymap.load()
    e = eng.Engine(lambda: hc.Keyboard(BusyTransport()), km, fps=30, on_error=errors.append)
    e.set_preset(Preset("t", [Layer("l", "rainbow")]))
    t = 0.0
    for _ in range(eng.BUSY_REPORT_AFTER - 1):
        t += 0.04
        e.step(t)
    assert errors == []
    e.step(t + 0.04)
    assert len(errors) == 1 and isinstance(errors[0], hc.DeviceBusy)
