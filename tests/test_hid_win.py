# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The Windows transport (platforms.win_hid.HidTransport) against a fake `hid` module (the hidapi package's API):
detection of the first supported model in models.py order on interface 3, report ID 00 + 90 bytes out, the ID
stripped from 91-byte replies, busy re-reads 15 ms apart (at most 10) on the normal path, immediate polling on the
fast path, the shared USB lock, and hid errors turned into DeviceError so the app reconnects. The real hid module is
never imported: nothing here enumerates or opens a device."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import huntsman_core as hc  # noqa: E402
import models  # noqa: E402
from platforms import win_hid  # noqa: E402


def reply_for(report, status=hc.STATUS_OK):
    r = bytearray(report)
    r[0] = status
    r[88] = hc.crc(r)
    return bytes(r)


class FakeDevice:
    """hid.device(): open_path, send_feature_report(data) -> bytes written, get_feature_report(id, n) -> list."""

    def __init__(self, hidmod):
        self.hidmod = hidmod
        self.path = None
        self.sent, self.reads, self.closed = [], [], False
        self.statuses = []      # status of each reply, in order; OK once used up
        self.short = False

    def open_path(self, path):
        if self.hidmod.fail_open:
            raise OSError("open failed")
        self.path = path
        self.hidmod.opened.append(self)

    def send_feature_report(self, data):
        if self.hidmod.fail_io:
            raise OSError("write error")
        self.sent.append(bytes(data))
        return len(data)

    def get_feature_report(self, report_id, max_length):
        if self.hidmod.fail_io:
            raise ValueError("not open")
        self.reads.append((report_id, max_length))
        status = self.statuses.pop(0) if self.statuses else hc.STATUS_OK
        body = reply_for(self.sent[-1][1:], status)
        if self.short:
            return list(b"\x00" + body[:40])
        return list(b"\x00" + body)   # hidapi on Windows: the report ID comes back first

    def close(self):
        self.closed = True


class FakeHid:
    """The bits of the hidapi package the transport uses: enumerate(vid, pid) and device()."""

    def __init__(self, entries=()):
        self.entries = list(entries)
        self.opened, self.enumerated = [], []
        self.fail_open = self.fail_io = False
        self.next_device = None

    def enumerate(self, vid=0, pid=0):
        self.enumerated.append((vid, pid))
        return [dict(e) for e in self.entries if (not vid or e["vendor_id"] == vid) and (not pid or e["product_id"] == pid)]

    def device(self):
        d = self.next_device or FakeDevice(self)
        d.hidmod = self
        return d


def entry(pid, interface, path=None, vid=hc.VID):
    return {"vendor_id": vid, "product_id": pid, "interface_number": interface,
            "path": path or f"\\\\?\\hid#vid_{vid:04x}&pid_{pid:04x}&mi_{interface:02d}".encode(),
            "usage_page": 0xFF00 if interface == 3 else 1, "usage": 1}


@pytest.fixture(autouse=True)
def keep_model():
    yield
    hc.set_active_model(0x02A6)


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(win_hid, "_sleep", sleeps.append)
    return sleeps


@pytest.fixture
def lockdir(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    return tmp_path


def transport(*entries, hid=None):
    hid = hid or FakeHid(entries)
    t = win_hid.HidTransport(hid_module=hid)
    for d in hid.opened:   # forget the detection probe (00:81) so tests count only their own traffic
        d.sent.clear()
        d.reads.clear()
    return t, hid


# ---------- detection ----------

def test_detects_the_v3_pro_on_interface_3_and_sets_the_active_model(lockdir):
    t, hid = transport(entry(0x02A6, 0), entry(0x02A6, 1), entry(0x02A6, 3, b"ctl"), entry(0x02A6, 2))
    assert t.model is models.MODELS[0x02A6] and hc.active_model() is t.model
    assert hid.opened[0].path == b"ctl"


def test_detection_follows_the_models_order(lockdir):
    # an experimental V2 Analog listed first by Windows, the verified V3 Pro second: the V3 Pro wins
    t, _ = transport(entry(0x0266, 3, b"analog"), entry(0x02A6, 3, b"v3"))
    assert t.model.pid == 0x02A6 and t.dev.path == b"v3"
    t, _ = transport(entry(0x026B, 3, b"tkl"), entry(0x0266, 3, b"analog"))
    order = list(models.MODELS)
    assert t.model.pid == min((0x026B, 0x0266), key=order.index)


def test_an_interface_other_than_3_is_not_the_control_interface(lockdir):
    with pytest.raises(hc.DeviceError, match="No supported Razer Huntsman"):
        transport(entry(0x02A6, 0), entry(0x02A6, 1), entry(0x02A6, 2))


def test_other_razer_devices_and_vendors_are_ignored(lockdir):
    with pytest.raises(hc.DeviceError, match="No supported Razer Huntsman"):
        transport(entry(0x0084, 3), entry(0x02A6, 3, vid=0x046D))


def test_open_failure_is_a_device_error(lockdir):
    hid = FakeHid([entry(0x02A6, 3)])
    hid.fail_open = True
    with pytest.raises(hc.DeviceError, match="open"):
        win_hid.HidTransport(hid_module=hid)


def test_missing_hidapi_is_a_device_error(monkeypatch, lockdir):
    monkeypatch.setitem(sys.modules, "hid", None)   # import hid -> ImportError
    with pytest.raises(hc.DeviceError, match="hidapi"):
        win_hid.HidTransport()


# ---------- framing ----------

def test_exchange_sends_report_id_zero_and_strips_it_from_the_reply(lockdir, no_sleep):
    t, hid = transport(entry(0x02A6, 3))
    req = hc.build_report(0x00, 0x81, size=2)
    resp = t.exchange(req)
    dev = hid.opened[0]
    assert dev.sent == [b"\x00" + bytes(req)] and len(dev.sent[0]) == 91
    assert dev.reads == [(0, 91)]
    assert len(resp) == 90 and resp[0] == hc.STATUS_OK and resp[6:8] == bytes([0x00, 0x81])
    hc.check_reply(req, resp)
    assert no_sleep == []   # the reply is ready right after SET_REPORT


def test_a_short_reply_is_a_device_error(lockdir, no_sleep):
    t, hid = transport(entry(0x02A6, 3))
    hid.opened[0].short = True
    with pytest.raises(hc.DeviceError, match="short"):
        t.exchange(hc.build_report(0x00, 0x81, size=2))


def test_hid_errors_become_device_errors(lockdir, no_sleep):
    t, hid = transport(entry(0x02A6, 3))
    hid.fail_io = True
    with pytest.raises(hc.DeviceError):
        t.exchange(hc.build_report(0x00, 0x81, size=2))
    with pytest.raises(hc.DeviceError):
        t.exchange_fast([hc.build_report(0x0F, 0x03, [0] * 10)])


def test_a_keyboard_works_over_the_hid_transport(lockdir, no_sleep):
    t, _ = transport(entry(0x02A6, 3))
    kb = hc.Keyboard(t)
    assert kb.model.pid == 0x02A6 and kb.firmware() == "0.00"


# ---------- busy retry ----------

def test_busy_replies_are_re_read_15_ms_apart_without_re_sending(lockdir, no_sleep):
    t, hid = transport(entry(0x02A6, 3))
    dev = hid.opened[0]
    dev.statuses = [hc.STATUS_BUSY, hc.STATUS_NEW, hc.STATUS_BUSY]
    resp = t.exchange(hc.build_report(0x02, 0x12, [0] * 10))
    assert resp[0] == hc.STATUS_OK
    assert len(dev.sent) == 1 and len(dev.reads) == 4
    assert no_sleep == [0.015] * 3


def test_busy_retry_gives_up_after_10_reads(lockdir, no_sleep):
    t, hid = transport(entry(0x02A6, 3))
    dev = hid.opened[0]
    dev.statuses = [hc.STATUS_BUSY] * 50
    req = hc.build_report(0x0F, 0x02, [1, 5, 0, 0, 0, 0])
    resp = t.exchange(req)
    assert resp[0] == hc.STATUS_BUSY and len(dev.reads) == 10 and len(dev.sent) == 1
    with pytest.raises(hc.DeviceError):
        hc.check_reply(req, resp)


def test_a_refusal_is_returned_at_once(lockdir, no_sleep):
    t, hid = transport(entry(0x02A6, 3))
    hid.opened[0].statuses = [hc.STATUS_NOT_SUPPORTED]
    assert t.exchange(hc.build_report(0x0F, 0x02, [1, 5, 9]))[0] == hc.STATUS_NOT_SUPPORTED
    assert no_sleep == []


# ---------- fast path ----------

def test_fast_path_polls_immediately_and_answers_each_report(lockdir, no_sleep):
    t, hid = transport(entry(0x02A6, 3))
    dev = hid.opened[0]
    dev.statuses = [hc.STATUS_BUSY, hc.STATUS_BUSY]
    reqs = [hc.build_report(0x0F, 0x03, [0, 0, i, 0, 21] + [0] * 66, 0x47) for i in range(6)]
    replies = t.exchange_fast(reqs)
    assert len(replies) == 6 and all(len(r) == 90 and r[0] == hc.STATUS_OK for r in replies)
    assert [s[1:] for s in dev.sent] == [bytes(r) for r in reqs] and all(s[0] == 0 for s in dev.sent)
    assert len(dev.reads) == 8 and no_sleep == []   # no 15 ms sleeps on the fast path


def test_fast_path_stops_at_the_first_reply_that_is_not_ok(lockdir, no_sleep):
    t, hid = transport(entry(0x02A6, 3))
    dev = hid.opened[0]
    dev.statuses = [hc.STATUS_OK, 0x05]
    reqs = [hc.build_report(0x0F, 0x03, [0, 0, i]) for i in range(6)]
    replies = t.exchange_fast(reqs)
    assert len(replies) == 2 and replies[1][0] == 0x05 and len(dev.sent) == 2


def test_fast_path_skips_a_frame_that_stays_busy(lockdir, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(win_hid, "_sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(win_hid, "_monotonic", lambda: clock[0])
    t, hid = transport(entry(0x02A6, 3))
    dev = hid.opened[0]
    dev.statuses = [hc.STATUS_BUSY] * 1000
    replies = t.exchange_fast([hc.build_report(0x0F, 0x03, [0, 0, 0])] * 3)
    assert len(replies) == 1 and replies[0][0] == hc.STATUS_BUSY and len(dev.sent) == 1
    assert clock[0] <= hc.FAST_BUSY_BUDGET + 0.001


def test_send_frame_fast_over_hid(lockdir, no_sleep):
    t, _ = transport(entry(0x02A6, 3))
    kb = hc.Keyboard(t)
    kb.send_frame_fast([[[0, 0, 0]] * 22 for _ in range(6)])


# ---------- locking and close ----------

def test_exchanges_hold_the_usb_lock(lockdir, no_sleep, monkeypatch):
    t, _ = transport(entry(0x02A6, 3))
    real, taken = hc.usb_lock, []

    def counting():
        taken.append(1)
        return real()
    monkeypatch.setattr(hc, "usb_lock", counting)
    t.exchange(hc.build_report(0x00, 0x81, size=2))
    t.exchange_fast([hc.build_report(0x0F, 0x03, [0, 0, i]) for i in range(6)])
    assert taken == [1, 1]
    assert os.path.exists(lockdir / "usb.lock")


def test_close_closes_the_device_once_and_waits_for_the_lock(lockdir):
    import threading
    t, hid = transport(entry(0x02A6, 3))
    done = threading.Event()
    with hc._USB_LOCK:
        th = threading.Thread(target=lambda: (t.close(), done.set()))
        th.start()
        assert not done.wait(0.1)
    assert done.wait(1) and hid.opened[0].closed
    t.close()   # twice is fine


# ---------- choosing the transport ----------

def test_keyboard_opens_the_hid_transport_on_windows(monkeypatch, lockdir):
    made = []

    class Fake:
        model = models.MODELS[0x02A6]

        def __init__(self):
            made.append("hid")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(win_hid, "HidTransport", Fake)
    monkeypatch.setattr(hc, "UsbTransport", lambda: pytest.fail("pyusb on Windows"))
    assert isinstance(hc.open_transport(), Fake) and made == ["hid"]
    assert isinstance(hc.Keyboard().t, Fake)


def test_keyboard_opens_the_usb_transport_on_the_mac(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(hc, "UsbTransport", lambda: sentinel)
    monkeypatch.setattr(win_hid, "HidTransport", lambda: pytest.fail("hidapi on the Mac"))
    assert hc.open_transport() is sentinel


# ---------- collections, probe, closed ----------

class DeadCollection(FakeDevice):
    """An interface-3 collection that doesn't take feature report 0."""

    def get_feature_report(self, report_id, max_length):
        raise OSError("HidD_GetFeature: The parameter is incorrect.")


def test_the_collection_that_answers_the_firmware_read_is_used(lockdir, no_sleep):
    hid = FakeHid([entry(0x02A6, 3, b"col01"), entry(0x02A6, 3, b"col02")])
    devices = [DeadCollection(hid), FakeDevice(hid)]
    hid.device = lambda: devices.pop(0)
    t = win_hid.HidTransport(hid_module=hid)
    assert t.dev.path == b"col02"
    first, second = hid.opened
    assert first.closed and not second.closed
    assert [s[7:9] for s in second.sent] == [bytes([0x00, 0x81])]   # the probe is a read


def test_no_collection_answering_is_a_device_error(lockdir, no_sleep):
    hid = FakeHid([entry(0x02A6, 3, b"col01")])
    hid.device = lambda: DeadCollection(hid)
    with pytest.raises(hc.DeviceError, match="control interface"):
        win_hid.HidTransport(hid_module=hid)
    assert hid.opened[0].closed


def test_a_closed_transport_raises_a_device_error(lockdir, no_sleep):
    t, _ = transport(entry(0x02A6, 3))
    t.close()
    with pytest.raises(hc.DeviceError, match="closed"):
        t.exchange(hc.build_report(0x00, 0x81, size=2))
    with pytest.raises(hc.DeviceError, match="closed"):
        t.exchange_fast([hc.build_report(0x0F, 0x03, [0])])


def test_a_longer_feature_buffer_is_cut_to_the_packet(lockdir, no_sleep):
    t, hid = transport(entry(0x02A6, 3))
    dev = hid.opened[0]
    real = dev.get_feature_report
    dev.get_feature_report = lambda rid, n: real(rid, n) + [0] * 9
    resp = t.exchange(hc.build_report(0x00, 0x81, size=2))
    assert len(resp) == 90 and resp[0] == hc.STATUS_OK
