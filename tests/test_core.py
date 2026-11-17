# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import huntsman_core as hc  # noqa: E402


class FakeTransport:
    """Answers like the keyboard: echoes the request with status 0x02 and stores key assignments.

    Knobs for tests: profile (05:84 answer), mode (00:84 answer, set by 00:04 unless stuck),
    refuse(r) -> True to answer status 0x05, ignore_writes = key ids whose 02:12 writes are dropped.
    """

    def __init__(self):
        self.sent = []
        self.keys = {}  # (profile, key) -> bytearray assignment
        self.profile = 1
        self.mode = 0
        self.stuck = False
        self.ignore_writes = set()

    def refuse(self, r):
        return False

    def edit(self, r):
        """Subclasses change the reply here; the CRC is recomputed afterwards."""

    def exchange(self, report):
        self.sent.append(bytes(report))
        r = bytearray(report)
        r[0] = hc.STATUS_OK
        cls, cid, args = r[6], r[7], r[8:88]
        if self.refuse(r):
            r[0] = 0x05
        elif (cls, cid) == (0x02, 0x92):
            p, k = args[0], args[1]
            a = self.keys.setdefault((p, k), bytearray([p, k, 0, 76, 70, 2, 2, 0, 4]))
            r[8:8 + len(a)] = a
        elif (cls, cid) == (0x05, 0x84):
            r[8] = self.profile
        elif (cls, cid) == (0x00, 0x84):
            r[8] = self.mode
        elif (cls, cid) == (0x00, 0x04):
            if not self.stuck:
                self.mode = args[0]
        elif (cls, cid) == (0x02, 0x12):
            fn = args[6]
            if args[1] not in self.ignore_writes:
                self.keys[(args[0], args[1])] = bytearray(args[:7 + fn])
        self.edit(r)
        r[88] = hc.crc(r)
        return bytes(r)

    def writes(self, cls=0x02, cid=0x12):
        return [r for r in self.sent if (r[6], r[7]) == (cls, cid)]


def test_report_layout_and_crc():
    r = hc.build_report(0x0F, 0x02, [1, 5, 1, 0, 0, 1, 255, 0, 0])
    assert len(r) == 90 and r[1] == 0x1F and r[5] == 9 and (r[6], r[7]) == (0x0F, 0x02)
    crc = 0
    for b in r[2:88]:
        crc ^= b
    assert r[88] == crc


def test_report_rejects_long_args():
    with pytest.raises(ValueError):
        hc.build_report(0, 0, bytes(81))


@pytest.mark.parametrize("mm,thr", [(1.2, 76), (2.0, 128), (4.0, 255), (0.1, 7)])
def test_threshold_scale(mm, thr):
    assert hc.mm_to_threshold(mm) == thr


def test_tenths_roundtrip():
    for tenth in range(1, 41):
        assert hc.threshold_to_mm(hc.mm_to_threshold(tenth / 10)) == tenth / 10


@pytest.mark.parametrize("bad", [0.0, 4.1, -1])
def test_threshold_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        hc.mm_to_threshold(bad)


def test_rapid_packet_matches_easyrazer_vector():
    # easyrazer trigger.rs: A on (press 0.1, release 0.4), S off
    pkts = hc.rapid_packets(0, [(31, (0.1, 0.4)), (32, None)])
    assert pkts == [bytes([0, 0, 0xFF, 1, 0, 0, 0, 0, 31, 1, 0x19, 0x98, 0x06, 0x66, 32, 0, 0, 0, 0, 0])]


def test_rapid_off_clears_switch_and_splits_in_thirteens():
    assert hc.rapid_packets(0, [(31, None)])[0][:8] == bytes([0, 0, 0xFF, 0, 0, 0, 0, 0])
    sizes = [len(p) for p in hc.rapid_packets(0, [(k, (0.5, 0.5)) for k in range(1, 31)])]
    assert sizes == [80, 80, 2 + 5 * 6]


@pytest.mark.parametrize("name,kw,expected", [
    ("static", {"rgb1": [255, 255, 255]}, [1, 0, 0, 1, 255, 255, 255]),
    ("spectrum", {}, [3, 0, 0, 0]),
    ("wave", {"speed": 40, "direction": "right"}, [4, 1, 40, 0]),
    ("starlight_two", {"speed": 2, "rgb1": [1, 2, 3], "rgb2": [4, 5, 6]}, [7, 0, 2, 2, 1, 2, 3, 4, 5, 6]),
    ("off", {}, [0, 0, 0, 0]),
])
def test_effects(name, kw, expected):
    assert hc.encode_effect(name, **kw) == expected


@pytest.mark.parametrize("name,kw", [
    ("static", {}), ("wave", {"speed": 0, "direction": "left"}), ("wave", {"speed": 256, "direction": "right"}),
    ("wave", {"speed": 5, "direction": "up"}), ("wave", {"speed": 5}),
    ("starlight_one", {"speed": 4, "rgb1": [0, 0, 0]}), ("nope", {}), ("static", {"rgb1": [256, 0, 0]}),
])
def test_effects_reject_bad_input(name, kw):
    with pytest.raises(ValueError):
        hc.encode_effect(name, **kw)


def test_set_actuation_writes_live_and_saved_and_keeps_other_fields():
    t = FakeTransport()
    kb = hc.Keyboard(t)
    assert kb.set_actuation([31, 32], 2.0) == []
    for p in (0, 1):
        for k in (31, 32):
            a = t.keys[(p, k)]
            assert a[3] == 128 and a[4] == 122 and a[5:] == bytearray([2, 2, 0, 4])


def test_refused_command_raises():
    class Refuse(FakeTransport):
        def edit(self, r):
            r[0] = 0x03
    with pytest.raises(hc.DeviceError):
        hc.Keyboard(Refuse()).firmware()


def test_snap_tap_and_continuous_packets():
    t = FakeTransport()
    kb = hc.Keyboard(t)
    kb.set_snap_tap((31, 33))
    kb.set_snap_tap(None)
    kb.set_continuous(True)
    kb.set_continuous(False)
    args = [(r[6], r[7], list(r[8:8 + r[5]])) for r in t.sent if (r[6], r[7]) != (5, 0x84)]
    assert args == [
        (2, 0x21, [0, 1, 31, 33]),                      # ON: live only
        (2, 0x21, [0, 0, 0, 0]), (2, 0x21, [1, 0, 0, 0]),  # OFF: live and saved
        (2, 0x20, [0, 1]),
        (2, 0x20, [0, 0]), (2, 0x20, [1, 0]),
    ]


def test_layout_has_unique_ids_and_known_keys():
    ids = [k["id"] for k in hc.load_layout()]
    assert len(ids) == len(set(ids)) == 104
    assert 31 in hc.all_key_ids()


@pytest.mark.parametrize("thr,rel", [(76, 70), (128, 122), (7, 1), (255, 249)])
def test_release_follows_actuation(thr, rel):
    assert hc.release_for(thr) == rel


def test_explicit_release_must_sit_below_actuation():
    thr = hc.mm_to_threshold(2.0)
    assert hc.release_for(thr, 1.5) == 96
    with pytest.raises(ValueError):
        hc.release_for(thr, 2.0)


def test_low_actuation_never_leaves_release_above_it():
    t = FakeTransport()
    hc.Keyboard(t).set_actuation([31], 0.5)
    a = t.keys[(0, 31)]
    assert a[4] < a[3] == 32


def test_reply_checks():
    req = hc.build_report(0x02, 0x92, [0, 31, 0], 80)
    good = bytearray(req); good[0] = 2
    hc.check_reply(req, bytes(good))
    for i, v in ((7, 0x93), (1, 0x3F), (0, 0x03)):
        bad = bytearray(good); bad[i] = v
        with pytest.raises(hc.DeviceError):
            hc.check_reply(req, bytes(bad))


def test_key_data_for_another_key_is_rejected():
    class Wrong(FakeTransport):
        def edit(self, r):
            if (r[6], r[7]) == (2, 0x92):
                r[9] = 99
    with pytest.raises(hc.DeviceError):
        hc.Keyboard(Wrong()).read_key(0, 31)


def test_frame_places_keys_on_their_led_cells():
    layout = hc.load_layout()
    rows = hc.frame_rows({31: [255, 0, 0]}, layout)
    a = next(k for k in layout if k["id"] == 31)
    r, c = a["led"]
    assert rows[r][c] == [255, 0, 0]
    assert sum(1 for row in rows for cell in row if cell != [0, 0, 0]) == 1
    cells = [tuple(k["led"]) for k in layout]
    assert len(cells) == len(set(cells))


def test_custom_lighting_packets():
    t = FakeTransport()
    hc.Keyboard(t).set_custom({31: [1, 2, 3]}, hc.load_layout())
    sent = [(r[6], r[7], r[5]) for r in t.sent]
    assert sent == [(0x0F, 0x03, 0x47)] * 6 + [(0x0F, 0x02, 0x0C)]
    assert list(t.sent[0][8:13]) == [0, 0, 0, 0, 21]


def test_gamma():
    assert hc.gamma([255, 128, 0]) == [255, 56, 0]


def test_effect_colours_are_gamma_corrected():
    t = FakeTransport()
    hc.Keyboard(t).set_effect("static", rgb1=[255, 128, 0])
    assert list(t.sent[-1][8:15]) == [1, 5, 1, 0, 0, 1, 255] and t.sent[-1][15] == 56


def test_custom_release_near_the_top_is_clamped_not_refused():
    thr = hc.mm_to_threshold(4.0)
    assert hc.release_for(thr, 3.9) == thr - hc.RELEASE_GAP


def test_restore_refuses_when_another_profile_is_active():
    snap = hc.Keyboard(FakeTransport()).snapshot([31])
    t = FakeTransport()
    t.profile = 2
    with pytest.raises(hc.DeviceError):
        hc.Keyboard(t).restore_snapshot(snap)
    assert t.writes() == []


def test_snapshot_roundtrip_restores_exact_bytes():
    t = FakeTransport()
    kb = hc.Keyboard(t)
    snap = kb.snapshot([31, 32])
    kb.set_actuation([31, 32], 3.0)
    kb.restore_snapshot(snap)
    assert t.keys[(0, 31)] == bytearray([0, 31, 0, 76, 70, 2, 2, 0, 4])
    assert t.keys[(1, 32)] == bytearray([1, 32, 0, 76, 70, 2, 2, 0, 4])


def test_factory_restore_sets_synapse_defaults():
    t = FakeTransport()
    kb = hc.Keyboard(t)
    kb.set_actuation([31], 3.0)
    assert kb.restore_factory([31]) == []
    assert tuple(t.keys[(0, 31)][3:5]) == tuple(t.keys[(1, 31)][3:5]) == (76, 70)


def test_every_key_id_covers_keys_off_the_layout():
    ids = hc.every_key_id()
    assert set(hc.all_key_ids()) < set(ids) and 59 in ids  # Fn is cleared too


def test_depth_report_parsing():
    import depth_stream as ds
    # captured from the keyboard: key D (0x21) at 0x0668 = 1640 units, then the end marker
    assert ds.parse_depth_report(bytes.fromhex("210668") + bytes(44)) == [(0x21, 0.1)]
    assert ds.parse_depth_report(bytes(47)) == []
    two = bytes([31, 0x3F, 0xFC, 33, 0xFF, 0xFF]) + bytes(41)
    assert ds.parse_depth_report(two) == [(31, 1.0), (33, 4.0)]


class _Session:
    """Builds a DepthSession around a fake keyboard without touching IOKit."""

    @staticmethod
    def make(fail_reply=False, stuck=False, limit=60.0):
        import depth_stream as ds
        t = FakeTransport()
        t.stuck = stuck
        sent = []
        orig = t.exchange

        def exchange(report):
            sent.append((report[6], report[7], report[8]))
            if fail_reply and (report[6], report[7], report[8]) == (0, 4, 3):
                raise OSError("reply lost")
            return orig(report)
        t.exchange = exchange
        ended = []
        s = ds.DepthSession(hc.Keyboard(t), lambda b: None, lambda reason, ok: ended.append((reason, ok)), limit)
        s.t = t
        return s, sent, ended


def test_stop_switches_back_to_hardware_mode_once():
    s, sent, ended = _Session.make()
    s.running = True
    assert s.stop() is True and s.stop() is True
    assert sent.count((0, 4, 0)) == 1 and ended == [(None, True)]


def test_failed_switch_reply_still_switches_back(monkeypatch):
    import depth_stream as ds
    s, sent, ended = _Session.make(fail_reply=True)

    class FakeIO:
        class iokit:
            @staticmethod
            def IOHIDRequestAccess(_):
                return True
    monkeypatch.setattr(ds, "_IOKit", lambda: FakeIO())
    monkeypatch.setattr(ds.DepthSession, "_run", lambda self, io, ready, failure: ready.set())
    with pytest.raises(OSError):
        s.start()
    assert (0, 4, 0) in sent and s.running is False and ended and ended[0][1] is True


def test_snapshot_restore_rejects_damaged_entries():
    kb = hc.Keyboard(FakeTransport())
    snap = kb.snapshot([31])
    snap["profiles"]["0"]["31"] = snap["profiles"]["0"]["31"][:4] + "20" + snap["profiles"]["0"]["31"][6:]  # key id 0x20
    kb.t.sent.clear()
    with pytest.raises(hc.DeviceError):
        kb.restore_snapshot(snap)
    assert kb.t.writes() == []


# ---------- batch 1: keyboard safety ----------

def test_release_is_never_zero():
    with pytest.raises(ValueError):
        hc.release_for(6)  # below the minimum actuation: the release would be 0
    assert hc.release_for(hc.mm_to_threshold(0.1)) == 1
    assert hc.release_for(hc.mm_to_threshold(0.5), 0.0) == 1


def test_factory_preset_matches_the_1_2_mm_threshold():
    assert hc.mm_to_threshold(1.2) == hc.FACTORY_THR == 76
    assert hc.release_for(hc.FACTORY_THR) == hc.FACTORY_REL == 70


@pytest.mark.parametrize("mm,raw", [(0.1, 1638), (2.5, 40950)])
def test_rapid_trigger_distance_range(mm, raw):
    assert hc.rt_distance(mm) == raw.to_bytes(2, "big")


@pytest.mark.parametrize("bad", [0.0, 0.09, 2.51, -1])
def test_rapid_trigger_distance_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        hc.rt_distance(bad)


def test_reply_with_bad_crc_is_rejected():
    req = hc.build_report(0x02, 0x92, [0, 31, 0], 80)
    good = bytearray(req); good[0] = 2
    bad = bytearray(good); bad[88] ^= 0xFF
    with pytest.raises(hc.DeviceError, match="checksum"):
        hc.check_reply(req, bytes(bad))
    corrupted = bytearray(good); corrupted[20] ^= 0x01  # payload changed in transit
    with pytest.raises(hc.DeviceError):
        hc.check_reply(req, bytes(corrupted))


class _FakeDev:
    """ctrl_transfer stand-in: replies with the given statuses in turn, then OK."""

    def __init__(self, statuses):
        self.statuses, self.reads, self.writes = list(statuses), 0, 0

    def ctrl_transfer(self, rtype, req, val, idx, data):
        if rtype == 0x21:
            self.writes += 1
            self.report = bytearray(data)
            return len(data)
        self.reads += 1
        r = bytearray(self.report)
        r[0] = self.statuses.pop(0) if self.statuses else hc.STATUS_OK
        r[88] = hc.crc(r)
        return r


class _FakeUtil:
    @staticmethod
    def release_interface(dev, i):
        pass


def _bare_transport(dev):
    t = object.__new__(hc.UsbTransport)
    t.dev = dev
    return t


def test_exchange_keeps_polling_while_status_is_new_or_busy():
    dev = _FakeDev([0x00, hc.STATUS_BUSY, 0x00])
    resp = _bare_transport(dev)._exchange(hc.build_report(0, 0x81, size=2), _FakeUtil)
    assert resp[0] == hc.STATUS_OK and dev.reads == 4 and dev.writes == 1


def test_usb_lock_is_shared_and_inter_process(tmp_path, monkeypatch):
    import fcntl
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    with hc.usb_lock():
        with open(tmp_path / "usb.lock", "a") as other:  # another process would hold its own descriptor
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with open(tmp_path / "usb.lock", "a") as other:  # released afterwards
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_close_waits_for_the_transport_lock():
    import threading
    closed = threading.Event()
    t = _bare_transport(object())
    with hc._USB_LOCK:
        th = threading.Thread(target=lambda: (t.close(), closed.set()))
        th.start()
        assert not closed.wait(0.1)  # disposing mid-exchange must wait
    assert closed.wait(1)


def _ops():
    return {
        "set_actuation": lambda kb: kb.set_actuation([31], 2.0),
        "restore_factory": lambda kb: kb.restore_factory([31]),
        "restore_snapshot": lambda kb: kb.restore_snapshot(
            {"saved_profile": kb.t.profile, "profiles": {"0": {}, str(kb.t.profile): {}}}),
        "set_rapid_on": lambda kb: kb.set_rapid([(31, (0.5, 0.5))]),
        "set_rapid_off": lambda kb: kb.set_rapid([(31, None)]),
        "set_continuous": lambda kb: kb.set_continuous(False),
        "set_snap_tap": lambda kb: kb.set_snap_tap(None),
        "snapshot": lambda kb: kb.snapshot([31]),
    }


@pytest.mark.parametrize("op", list(_ops()))
def test_saved_profile_is_read_again_for_every_write(op):
    t = FakeTransport()
    kb = hc.Keyboard(t)
    _ops()[op](kb)
    t.profile = 3  # the owner switched profiles on the keyboard
    t.sent.clear()
    out = _ops()[op](kb)
    assert any((r[6], r[7]) == (0x05, 0x84) for r in t.sent)
    if op in ("set_actuation", "restore_factory"):
        assert {r[8] for r in t.writes()} == {0, 3}
    if op == "snapshot":
        assert out["saved_profile"] == 3 and set(out["profiles"]) == {"0", "3"}


def test_invalid_saved_profile_blocks_writes():
    t = FakeTransport()
    t.profile = 0
    with pytest.raises(hc.DeviceError):
        hc.Keyboard(t).set_actuation([31], 2.0)
    assert t.writes() == []


def test_set_actuation_writes_saved_before_live_per_key():
    t = FakeTransport()
    hc.Keyboard(t).set_actuation([31, 32], 2.0)
    assert [(r[8], r[9]) for r in t.writes()] == [(1, 31), (0, 31), (1, 32), (0, 32)]


def test_set_actuation_skips_live_when_saved_write_fails():
    class FailSaved(FakeTransport):
        def refuse(self, r):
            return (r[6], r[7], r[8], r[9]) == (2, 0x12, 1, 32)
    t = FailSaved()
    with pytest.raises(hc.DeviceError):
        hc.Keyboard(t).set_actuation([31, 32], 2.0)
    assert (0, 32) not in [(r[8], r[9]) for r in t.writes()]  # live (RAM) never got ahead of flash


def test_partial_write_readback_is_reported():
    t = FakeTransport()
    t.ignore_writes = {32}
    assert hc.Keyboard(t).set_actuation([31, 32], 2.0) == [32]
    assert t.keys[(0, 31)][3] == 128 and (0, 32) not in [(r[8], r[9]) for r in t.writes()]  # live skipped


def test_restore_snapshot_readback_mismatch_is_reported():
    t = FakeTransport()
    kb = hc.Keyboard(t)
    snap = kb.snapshot([31, 32])
    kb.set_actuation([31, 32], 3.0)
    t.ignore_writes = {32}
    assert kb.restore_snapshot(snap) == [32]


def test_snapshot_skips_refused_keys():
    class RefuseKey40(FakeTransport):
        def refuse(self, r):
            return (r[6], r[7]) == (2, 0x92) and r[9] == 40
    snap = hc.Keyboard(RefuseKey40()).snapshot([31, 40])
    assert set(snap["profiles"]["0"]) == {"31"} and snap["skipped"] == [[0, 40], [1, 40]]


@pytest.mark.parametrize("colors,base", [
    ({31: [256, 0, 0]}, (0, 0, 0)), ({31: [-1, 0, 0]}, (0, 0, 0)), ({31: [1, 2]}, (0, 0, 0)),
    ({31: [1, 2, 3]}, (0, 0, 300)), ({31: ["x", 0, 0]}, (0, 0, 0)),
])
def test_custom_rejects_bad_colours_before_sending(colors, base):
    t = FakeTransport()
    with pytest.raises(ValueError):
        hc.Keyboard(t).set_custom(colors, hc.load_layout(), base)
    assert t.sent == []


@pytest.mark.parametrize("bad", [[256, 0, 0], [-1, 0, 0], [1, 2], [1, 2, 3, 4]])
def test_gamma_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        hc.gamma(bad)


def test_brightness_stores():
    t = FakeTransport()
    kb = hc.Keyboard(t)
    kb.set_brightness(50, stores=(0,))
    kb.set_brightness(50)
    assert [r[8] for r in t.writes(0x0F, 0x04)] == [0, 0, 1]


# ---------- key tester (depth_stream) ----------

def test_stop_failure_reports_unplug():
    s, sent, ended = _Session.make(stuck=True)
    s.t.mode = 3
    s.running = True
    assert s.stop() is False
    assert ended[0][1] is False and "Unplug" in ended[0][0]


class _FakeIOKit:
    """Enough of _IOKit for DepthSession._run: one device, an idle run loop."""

    def __init__(self):
        import ctypes
        self.CB = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p, ctypes.c_int,
                                   ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8), ctypes.c_long)
        self.mode = None
        outer = self

        class iokit:
            IOHIDRequestAccess = staticmethod(lambda _: True)
            IOHIDDeviceOpen = staticmethod(lambda d, o: 0)
            IOHIDDeviceRegisterInputReportCallback = staticmethod(lambda *a: None)
            IOHIDDeviceScheduleWithRunLoop = staticmethod(lambda *a: None)
            IOHIDDeviceUnscheduleFromRunLoop = staticmethod(lambda *a: None)
            IOHIDDeviceClose = staticmethod(lambda *a: None)

        class cf:
            CFRunLoopGetCurrent = staticmethod(lambda: None)
            CFRunLoopRunInMode = staticmethod(lambda *a: __import__("time").sleep(0.02))
        self.iokit, self.cf, outer.closed = iokit, cf, False

    def devices(self):
        return [1]

    def prop(self, dev, key):
        return 64


def test_time_limit_switches_back(monkeypatch):
    import depth_stream as ds
    import time
    monkeypatch.setattr(ds, "_IOKit", _FakeIOKit)
    s, sent, ended = _Session.make(limit=0)
    assert s.start() is True
    deadline = time.monotonic() + 2
    while not ended and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ended and ended[0][1] is True and "stopped after" in ended[0][0]
    assert sent.index((0, 4, 3)) < sent.index((0, 4, 0)) and s.t.mode == 0


def test_stop_before_running_cancels_start(monkeypatch):
    import depth_stream as ds
    s, sent, ended = _Session.make()

    def run(self, io, ready, failure):
        self.stop()  # e.g. the window closes while start() waits for the stream
        ready.set()
    monkeypatch.setattr(ds, "_IOKit", _FakeIOKit)
    monkeypatch.setattr(ds.DepthSession, "_run", run)
    assert s.start() is False
    assert (0, 4, 3) not in sent and s.running is False and s.t.mode == 0


def test_stop_during_mode_switch_switches_back(monkeypatch):
    import depth_stream as ds
    s, sent, ended = _Session.make()
    orig = s.t.exchange

    def exchange(report):
        r = orig(report)
        if (report[6], report[7], report[8]) == (0, 4, 3):
            s.stop()  # stop lands while the switch is in flight
        return r
    s.t.exchange = exchange
    monkeypatch.setattr(ds, "_IOKit", _FakeIOKit)
    monkeypatch.setattr(ds.DepthSession, "_run", lambda self, io, ready, failure: ready.set())
    assert s.start() is False
    assert s.t.mode == 0 and s.running is False


def test_stop_unregisters_atexit(monkeypatch):
    import depth_stream as ds
    reg, unreg = [], []
    monkeypatch.setattr(ds.atexit, "register", reg.append)
    monkeypatch.setattr(ds.atexit, "unregister", unreg.append)
    monkeypatch.setattr(ds, "_IOKit", _FakeIOKit)
    monkeypatch.setattr(ds.DepthSession, "_run", lambda self, io, ready, failure: ready.set())
    s, sent, ended = _Session.make()
    s.start()
    s.stop()
    assert reg == [s.stop] and unreg == [s.stop]


def test_signal_stops_running_sessions_then_exits(monkeypatch):
    # The handler work happens on a watcher thread fed by signal.set_wakeup_fd: under the Cocoa run
    # loop the main thread may never run Python-level handlers, and a swallowed SIGTERM would hang.
    import depth_stream as ds
    import signal
    import time
    exited, installed, wake = [], {}, []
    monkeypatch.setattr(ds.os, "_exit", lambda code: exited.append(code))
    monkeypatch.setattr(ds.signal, "signal", lambda sig, h: installed.setdefault(sig, h))
    monkeypatch.setattr(ds.signal, "set_wakeup_fd", lambda fd, **kw: wake.append(fd) or -1)
    monkeypatch.setattr(ds, "_IOKit", _FakeIOKit)
    monkeypatch.setattr(ds.DepthSession, "_run", lambda self, io, ready, failure: ready.set())
    s, sent, ended = _Session.make()
    s.start()
    ds.install_signal_stop()
    assert set(installed) >= {signal.SIGTERM, signal.SIGHUP} and wake
    ds.os.write(wake[0], bytes([signal.SIGTERM]))  # what the C-level handler writes
    deadline = time.monotonic() + 2
    while not exited and time.monotonic() < deadline:
        time.sleep(0.01)
    assert s.running is False and s.t.mode == 0 and exited == [128 + signal.SIGTERM]


@pytest.mark.parametrize("mode,switched", [(3, True), (0, False)])
def test_recover_typing_after_a_crash(mode, switched):
    import depth_stream as ds
    t = FakeTransport()
    t.mode = mode
    assert ds.recover_typing(hc.Keyboard(t)) is switched
    assert t.mode == 0 and bool(t.writes(0, 4)) is switched


def test_recover_typing_never_raises():
    import depth_stream as ds

    class Refuse(FakeTransport):
        def refuse(self, r):
            return True
    assert ds.recover_typing(hc.Keyboard(Refuse())) is False


def test_fire_effect_is_not_offered():
    # Firmware 1.03 of the Huntsman V3 Pro refuses effect 09 (fire) with status 03; checked on hardware.
    assert "fire" not in hc.EFFECTS
    with pytest.raises(ValueError):
        hc.encode_effect("fire")


def test_not_supported_status_gets_a_plain_message():
    req = hc.build_report(0x0F, 0x02, [1, 5, 9, 0, 0, 0])
    resp = bytearray(req); resp[0] = 0x03; resp[88] = hc.crc(resp)
    with pytest.raises(hc.DeviceError, match="doesn't support"):
        hc.check_reply(req, bytes(resp))
