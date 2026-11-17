import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import huntsman_core as hc  # noqa: E402


class FakeTransport:
    """Answers like the keyboard: echoes the request with status 0x02 and stores key assignments."""

    def __init__(self):
        self.sent = []
        self.keys = {}  # (profile, key) -> bytearray assignment

    def exchange(self, report):
        self.sent.append(bytes(report))
        r = bytearray(report)
        r[0] = hc.STATUS_OK
        cls, cid, args = r[6], r[7], r[8:88]
        if (cls, cid) == (0x02, 0x92):
            p, k = args[0], args[1]
            a = self.keys.setdefault((p, k), bytearray([p, k, 0, 76, 70, 2, 2, 0, 4]))
            r[8:8 + len(a)] = a
        elif (cls, cid) == (0x05, 0x84):
            r[8] = 1
        elif (cls, cid) == (0x02, 0x12):
            fn = args[6]
            self.keys[(args[0], args[1])] = bytearray(args[:7 + fn])
        return bytes(r)


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


@pytest.mark.parametrize("mm,thr", [(1.2, 77), (2.0, 128), (4.0, 255), (0.1, 6)])
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
    ("static", {}), ("wave", {"speed": 0, "direction": "left"}), ("wave", {"speed": 5}),
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
        def exchange(self, report):
            r = bytearray(super().exchange(report))
            r[0] = 0x03
            return bytes(r)
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


@pytest.mark.parametrize("thr,rel", [(76, 70), (128, 122), (6, 0), (255, 249)])
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
        def exchange(self, report):
            r = bytearray(super().exchange(report))
            if (r[6], r[7]) == (2, 0x92):
                r[9] = 99
            return bytes(r)
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
    class Prof2(FakeTransport):
        def exchange(self, report):
            r = bytearray(super().exchange(report))
            if (r[6], r[7]) == (5, 0x84):
                r[8] = 2
            return bytes(r)
    snap = hc.Keyboard(FakeTransport()).snapshot([31])
    with pytest.raises(hc.DeviceError):
        hc.Keyboard(Prof2()).restore_snapshot(snap)


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
    def make(fail_mode_switch=False, fail_reply=False):
        import depth_stream as ds
        t = FakeTransport()
        sent = []
        orig = t.exchange

        def exchange(report):
            sent.append((report[6], report[7], report[8]))
            if fail_reply and (report[6], report[7], report[8]) == (0, 4, 3):
                raise OSError("reply lost")
            r = bytearray(orig(report))
            if (r[6], r[7]) == (0, 0x84):  # mode query answers "hardware"
                r[8] = 0
            return bytes(r)
        t.exchange = exchange
        ended = []
        s = ds.DepthSession(hc.Keyboard(t), lambda b: None, lambda reason, ok: ended.append((reason, ok)))
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
    with pytest.raises(hc.DeviceError):
        kb.restore_snapshot(snap)
