# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The per-key frame fast path in huntsman_core (no USB device: fakes only)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import huntsman_core as hc  # noqa: E402
from test_core import FakeTransport  # noqa: E402


def _rows(rgb=(1, 2, 3)):
    return [[list(rgb) for _ in range(hc.FRAME_COLS)] for _ in range(hc.FRAME_ROWS)]


class FastFake(FakeTransport):
    """FakeTransport with the batched exchange the engine uses; counts lock-holding batches."""

    def __init__(self):
        super().__init__()
        self.batches = []

    def exchange_fast(self, reports):
        self.batches.append(len(reports))
        return [self.exchange(r) for r in reports]


def test_send_frame_fast_sends_six_row_packets_in_one_batch():
    t = FastFake()
    hc.Keyboard(t).send_frame_fast(_rows())
    assert t.batches == [6]
    frames = t.writes(0x0F, 0x03)
    assert len(frames) == 6 == len(t.sent)  # no effect command: that is enter_custom_mode's job
    for i, r in enumerate(frames):
        assert r[5] == hc.FRAME_SIZE and list(r[8:13]) == [0, 0, i, 0, hc.FRAME_COLS - 1]
        assert list(r[13:16]) == [1, 2, 3] and r[88] == hc.crc(r)


def test_send_frame_fast_works_on_a_plain_transport():
    t = FakeTransport()  # no exchange_fast: falls back to one exchange per packet
    hc.Keyboard(t).send_frame_fast(_rows((9, 9, 9)))
    assert len(t.writes(0x0F, 0x03)) == 6


def test_send_frame_fast_does_not_gamma_correct():
    t = FastFake()
    hc.Keyboard(t).send_frame_fast(_rows((128, 64, 32)))
    assert list(t.writes(0x0F, 0x03)[0][13:16]) == [128, 64, 32]


@pytest.mark.parametrize("bad", [
    _rows()[:5],
    [row[:21] for row in _rows()],
    [[[256, 0, 0]] * hc.FRAME_COLS] * hc.FRAME_ROWS,
    [[[1.5, 0, 0]] * hc.FRAME_COLS] * hc.FRAME_ROWS,
])
def test_send_frame_fast_rejects_bad_rows_before_sending(bad):
    t = FastFake()
    with pytest.raises(ValueError):
        hc.Keyboard(t).send_frame_fast(bad)
    assert t.sent == []


def test_send_frame_fast_checks_every_reply():
    class Refuse(FastFake):
        def refuse(self, r):
            return r[10] == 3  # row 3

    with pytest.raises(hc.DeviceError, match="refused 0F:03"):
        hc.Keyboard(Refuse()).send_frame_fast(_rows())

    class BadCrc(FastFake):
        def edit(self, r):
            pass

        def exchange(self, report):
            r = bytearray(super().exchange(report))
            r[88] ^= 0xFF
            return bytes(r)

    with pytest.raises(hc.DeviceError, match="checksum"):
        hc.Keyboard(BadCrc()).send_frame_fast(_rows())


def test_send_frame_fast_raises_when_the_batch_is_cut_short():
    class Short(FastFake):
        def exchange_fast(self, reports):
            return [self.exchange(r) for r in reports[:3]]

    with pytest.raises(hc.DeviceError):
        hc.Keyboard(Short()).send_frame_fast(_rows())


def test_enter_custom_mode_sends_the_custom_effect():
    t = FakeTransport()
    hc.Keyboard(t).enter_custom_mode()
    (r,) = t.sent
    assert (r[6], r[7]) == (0x0F, 0x02) and r[5] == 0x0C and list(r[8:11]) == [0, 0, 0x08]


# ---------- UsbTransport.exchange_fast against a fake pyusb device ----------

class FakeDev:
    """ctrl_transfer like pyusb: OUT stores the request; IN answers busy `busy` times, then OK."""

    def __init__(self, busy=1, never_ready=False):
        self.busy, self.never_ready = busy, never_ready
        self.log, self.pending, self.left = [], None, 0

    def ctrl_transfer(self, bm, req, value, index, data):
        if bm == 0x21:
            self.log.append(("out", bytes(data)))
            self.pending, self.left = bytearray(data), self.busy
            return len(data)
        self.log.append(("in",))
        r = bytearray(self.pending)
        if self.never_ready or self.left > 0:
            self.left -= 1
            r[0] = hc.STATUS_BUSY
        else:
            r[0] = hc.STATUS_OK
        r[88] = hc.crc(r)
        return r


@pytest.fixture
def usb(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    sleeps = []
    monkeypatch.setattr(hc.time, "sleep", lambda s: sleeps.append(s))
    import usb.util
    released = []
    monkeypatch.setattr(usb.util, "release_interface", lambda dev, i: released.append(i))

    def make(**kw):
        t = hc.UsbTransport.__new__(hc.UsbTransport)
        t.dev = FakeDev(**kw)
        return t
    make.sleeps, make.released = sleeps, released
    return make


def test_exchange_fast_polls_immediately_without_sleeping(usb):
    t = usb(busy=2)
    reqs = [hc.build_report(0x0F, 0x03, [0, 0, i, 0, 21], hc.FRAME_SIZE) for i in range(6)]
    resps = t.exchange_fast(reqs)
    assert len(resps) == 6 and all(r[0] == hc.STATUS_OK for r in resps)
    assert usb.sleeps == []
    # each request: one OUT, then IN until ready (2 busy + 1 ok)
    assert [e[0] for e in t.dev.log] == (["out"] + ["in"] * 3) * 6
    assert usb.released == [hc.CONTROL_INTERFACE]  # released once, after the whole frame


def test_exchange_fast_holds_the_usb_lock_once_per_batch(usb, monkeypatch):
    entered = []
    real = hc.usb_lock

    def counting():
        entered.append(1)
        return real()
    monkeypatch.setattr(hc, "usb_lock", counting)
    usb(busy=0).exchange_fast([hc.build_report(0x0F, 0x03, [0, 0, i, 0, 21], hc.FRAME_SIZE) for i in range(6)])
    assert entered == [1]


def test_exchange_fast_gives_up_after_its_time_budget_and_stops_the_batch(usb):
    t = usb(never_ready=True)
    reqs = [hc.build_report(0x0F, 0x03, [0, 0, i, 0, 21], hc.FRAME_SIZE) for i in range(6)]
    resps = t.exchange_fast(reqs)
    assert len(resps) == 1 and resps[0][0] == hc.STATUS_BUSY  # nothing more is written to a busy keyboard
    # bounded by time (FAST_BUSY_BUDGET), so typing-induced busy periods are waited out briefly
    assert sum(1 for e in t.dev.log if e[0] == "in") >= hc.FAST_POLLS
    with pytest.raises(hc.DeviceBusy):
        hc.Keyboard(t).send_frame_fast(_rows())
