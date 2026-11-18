# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Huntsman V2 Analog (1532:0266) actuation, experimental: its own threshold scale and range, the release rule,
read-modify-write that keeps the key's function bytes, the gate, no factory point, the first-launch snapshot,
the window's model info and the command line. Also checks that the V3 scale didn't move. FakeTransport only;
settings go to tmp_path; nothing here opens USB.

Protocol: easyrazer 53a3dd3, docs/en/devices/huntsman-v2-analog/protocol.md (Actuation) and firmware.md
(Sensors and actuation), crates/core/src/analog.rs, actuation.rs, keymap.rs, devices/1532-0266.json."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import huntsman_core as hc  # noqa: E402
import models  # noqa: E402
from test_core import FakeTransport  # noqa: E402

ANALOG = 0x0266
A, S = 31, 32
KEY_A = [1, A, 0, 0, 0, 0x02, 0x02, 0x00, 0x04]     # easyrazer's capture of key A: thresholds 0/0, key 00 04


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    import app as appmod
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(appmod, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(appmod, "SNAPSHOT_FILE", str(tmp_path / "first-launch-snapshot.json"))
    hc.set_active_model(0x02A6)
    yield
    hc.set_active_model(0x02A6)


def scale():
    return models.by_pid(ANALOG).scale


def analog(t=None):
    return hc.Keyboard(t or FakeTransport(), model=models.by_pid(ANALOG))


def writes(t):
    return t.writes(0x02, 0x12)


def steps(lo, hi, d=0.01):
    n = round((hi - lo) / d)
    return [round(lo + i * d, 2) for i in range(n + 1)]


# ---------- the V3 scale is unchanged ----------

def _old_v3_threshold(mm):   # huntsman_core.mm_to_threshold as of v0.3.0
    mm = round(float(mm), 1)
    if not 0.1 <= mm <= 4.0:
        raise ValueError(f"{mm} mm is outside 0.1-4.0")
    if mm == 1.2:
        return 76
    return max(7, min(255, round(mm / (255 * 256 / 16380) * 255)))


def test_every_v3_model_keeps_the_v3_scale():
    for p in (0x02A6, 0x02A7, 0x02CF, 0x02B0):
        assert models.by_pid(p).scale is models.V3_SCALE
    v3 = models.V3_SCALE
    assert (v3.zero_mm, v3.full_mm, v3.min_thr, v3.max_thr) == (0, hc.FULL_MM, hc.MIN_THR, 255)
    assert v3.factory == (hc.FACTORY_THR, hc.FACTORY_REL)


def test_v3_thresholds_are_byte_for_byte_the_old_ones():
    for tenth in range(1, 41):
        mm = tenth / 10
        assert hc.mm_to_threshold(mm) == models.V3_SCALE.threshold(mm) == _old_v3_threshold(mm)
        assert hc.release_for(hc.mm_to_threshold(mm)) == hc.mm_to_threshold(mm) - hc.RELEASE_GAP
    for t in range(256):
        assert hc.threshold_to_mm(t) == round(t * hc.FULL_MM / 255, 1)
    with pytest.raises(ValueError, match="outside 0.1-4.0"):
        hc.mm_to_threshold(4.1)
    with pytest.raises(ValueError, match="at least 0.1 mm above"):
        hc.release_for(100, 7.0)


# ---------- the V2 Analog scale ----------

def test_v2_analog_has_actuation_only():
    m = models.by_pid(ANALOG)
    assert m.has("actuation") and m.experimental
    assert not (m.has("rapid") or m.has("snap_tap") or m.has("key_tester"))
    assert m.scale is not models.V3_SCALE


def test_scale_is_easyrazers():
    s = scale()
    assert (s.zero_mm, s.full_mm) == (1.5, 3.6)
    assert s.threshold(2.4) == 109           # easyrazer analog.rs v2_threshold_conversion
    assert s.mm(0x6F) == 2.41
    assert s.mm(0) == 1.5 and s.mm(255) == 3.6


def test_offered_range_is_the_hardware_clamp():
    s = scale()
    assert (s.min_mm, s.max_mm, s.step) == (1.62, 3.56, 0.01)
    assert s.threshold(1.62) == 15 and s.threshold(3.56) == 250
    for bad in (1.5, 1.61, 3.57, 3.6, 0.5, 4.0, float("nan")):
        with pytest.raises(ValueError, match="outside 1.62-3.56"):
            s.threshold(bad)


def test_every_offered_step_survives_a_round_trip():
    s = scale()
    thrs = []
    for mm in steps(1.62, 3.56):
        t = s.threshold(mm)
        assert 15 <= t <= 250 and s.mm(t) == mm
        thrs.append(t)
    assert len(set(thrs)) == len(thrs), "two slider steps give the same threshold"


def test_default_release_is_a_tenth_above_and_obeys_the_firmware_rule():
    s = scale()
    for mm in steps(1.62, 3.56):
        t = s.threshold(mm)
        r = s.release(t)
        assert 5 <= r <= t - 10
        assert s.mm(r) == max(1.54, round(mm - 0.1, 2))
    assert s.release(s.threshold(1.62)) == 5
    assert s.release(s.threshold(2.0)) == s.threshold(1.9)


def test_explicit_release():
    s = scale()
    t = s.threshold(2.0)                         # 61: the release may go up to 51
    assert s.release(t, 1.7) == s.threshold(1.7)
    assert s.release(t, 1.0) == 5                # below the firmware's floor: clamped, as the V3 clamps to 1
    assert s.release(t, 1.93) == t - 10          # within one step of the limit: clamped to it
    with pytest.raises(ValueError, match="at least 0.08 mm above"):
        s.release(t, 2.0)
    with pytest.raises(ValueError, match="below the minimum 15"):
        s.release(14)


def test_read_back_shows_what_the_firmware_uses():
    """The firmware clamps thrL to 15-250 and thrH to 5..thrL-10 when it uses them (firmware.md, 0x08017554);
    Synapse leaves 0/0 on every key."""
    s = scale()
    assert s.effective(0, 0) == (15, 5)
    assert s.effective(255, 255) == (250, 240)
    assert s.effective(100, 95) == (100, 90)
    assert s.effective(61, 49) == (61, 49)
    assert models.V3_SCALE.effective(3, 0) == (3, 0)   # the V3 Pro: as read


def test_info_for_the_window():
    assert models.by_pid(0x02A6).info()["actuation"] == {
        "min": 0.1, "max": 4.0, "step": 0.1, "decimals": 1, "release_min": 0.0, "reset_gap": 0.1, "factory": 1.2,
        "presets": [["Light", 0.5], ["Gaming", 1.0], ["Factory", 1.2], ["Balanced", 1.5], ["Typing", 2.0],
                    ["Firm", 3.0]]}
    a = models.by_pid(ANALOG).info()["actuation"]
    assert {k: a[k] for k in ("min", "max", "step", "decimals", "release_min", "reset_gap", "factory")} == {
        "min": 1.62, "max": 3.56, "step": 0.01, "decimals": 2, "release_min": 1.54, "reset_gap": 0.1,
        "factory": None}
    assert all(1.62 <= v <= 3.56 for _, v in a["presets"]) and len(a["presets"]) >= 4
    assert models.by_pid(0x026C).info()["actuation"] is None


# ---------- key ids ----------

def test_layout_ids_are_easyrazers_0266_key_ids():
    """layouts/0266.json against easyrazer's crates/core/src/keymap.rs (Synapse InputIDToMapping for 1532:0266),
    which keymap.json copies: every key, by name."""
    with open(os.path.join(ROOT, "keymap.json")) as f:
        fw = json.load(f)
    layout = hc.load_layout(models.by_pid(ANALOG))
    assert {k["name"]: k["id"] for k in layout} == {k["name"]: fw[k["name"]] for k in layout}
    assert 59 not in hc.all_key_ids(models.by_pid(ANALOG))   # Fn is never written


# ---------- the keyboard ----------

def test_writes_are_locked_until_the_switch_is_on():
    t = FakeTransport()
    with pytest.raises(hc.ExperimentalLocked):
        analog(t).set_actuation([A], 2.0)
    assert t.sent == []


def test_reads_need_no_switch_and_show_the_effective_point():
    t = FakeTransport()
    t.keys[(0, A)] = bytearray([0] + KEY_A[1:])
    assert analog(t).read_points(A) == (1.62, 1.54)
    t.keys[(0, S)] = bytearray([0, S, 0, 61, 49, 2, 2, 0, 0x16])
    assert analog(t).read_points(S) == (2.0, 1.9)
    assert writes(t) == []


def test_set_actuation_changes_only_the_thresholds_saved_profile_first():
    hc.set_experimental(True)
    t = FakeTransport()
    macro = [0x03, 0x03, 0x00, 0x07, 0x02]          # fnId 03: macro 7, twice
    for p in (0, 1):
        t.keys[(p, A)] = bytearray([p, A, 0, 0, 0, 0x02, 0x02, 0x00, 0x04])
        t.keys[(p, S)] = bytearray([p, S, 0, 200, 150] + macro)
    assert analog(t).set_actuation([A, S], 2.0) == []
    w = [bytes(r[8:8 + 7 + r[14]]) for r in writes(t)]
    assert [(x[0], x[1]) for x in w] == [(1, A), (0, A), (1, S), (0, S)]
    for p in (0, 1):
        assert t.keys[(p, A)] == bytearray([p, A, 0, 61, 49, 0x02, 0x02, 0x00, 0x04])
        assert t.keys[(p, S)] == bytearray([p, S, 0, 61, 49] + macro)
    assert all(r[5] == 80 for r in writes(t))


def test_explicit_release_is_written():
    hc.set_experimental(True)
    t = FakeTransport()
    analog(t).set_actuation([A], 3.0, 2.5)
    assert tuple(t.keys[(0, A)][3:5]) == (scale().threshold(3.0), scale().threshold(2.5))


def test_a_write_that_doesnt_read_back_is_reported_and_live_is_left_alone():
    hc.set_experimental(True)
    t = FakeTransport()
    t.ignore_writes = {A}
    assert analog(t).set_actuation([A, S], 2.0) == [A]
    assert [(r[8], r[9]) for r in writes(t)] == [(1, A), (1, S), (0, S)]


def test_out_of_range_sends_nothing():
    hc.set_experimental(True)
    t = FakeTransport()
    for mm in (1.2, 1.5, 3.6, 4.0):
        with pytest.raises(ValueError, match="1.62-3.56"):
            analog(t).set_actuation([A], mm)
    assert writes(t) == []


def test_no_factory_point_so_no_factory_restore():
    """easyrazer documents no factory actuation point for the V2 Analog (Synapse writes 0/0 and decides in driver
    mode), so restoring "factory depth" isn't offered; the first-launch snapshot is the way back."""
    hc.set_experimental(True)
    assert scale().factory is None
    t = FakeTransport()
    with pytest.raises(hc.FeatureUnavailable, match="factory"):
        analog(t).restore_factory([A])
    assert t.sent == []


def test_app_factory_restore_refuses_before_anything_is_sent():
    import app
    hc.set_experimental(True)
    t = FakeTransport()
    kb = analog(t)
    with pytest.raises(hc.FeatureUnavailable, match="factory"):
        app.restore_factory(kb)
    assert t.sent == []


@pytest.mark.parametrize("call", [lambda kb: kb.set_rapid([(A, (0.3, 0.3))]), lambda kb: kb.set_continuous(True),
                                  lambda kb: kb.set_snap_tap((A, 33))], ids=["rapid", "continuous", "snap_tap"])
def test_no_rapid_trigger_or_snap_tap(call):
    hc.set_experimental(True)
    t = FakeTransport()
    with pytest.raises(hc.FeatureUnavailable):
        call(analog(t))
    assert t.sent == []


def test_snapshot_and_restore_round_trip():
    hc.set_experimental(True)
    t = FakeTransport()
    for p in (0, 1):
        t.keys[(p, A)] = bytearray([p, A, 0, 0, 0, 0x02, 0x02, 0x00, 0x04])
    kb = analog(t)
    snap = kb.snapshot([A])
    assert snap["pid"] == "0266" and snap["profiles"]["1"][str(A)] == bytes([1, A, 0, 0, 0, 2, 2, 0, 4]).hex()
    kb.set_actuation([A], 3.0)
    assert kb.restore_snapshot(snap) == []
    assert t.keys[(1, A)] == bytearray([1, A, 0, 0, 0, 0x02, 0x02, 0x00, 0x04])


def test_first_launch_snapshot_is_taken_without_a_write():
    import app
    t = FakeTransport()
    app.ensure_snapshot(analog(t))
    with open(app.SNAPSHOT_FILE) as f:
        assert json.load(f)["pid"] == "0266"
    assert writes(t) == []


# ---------- app and command line ----------

_REAL = hc.Keyboard


class _Plug:
    """hc.Keyboard() as detection would build it for a plugged-in V2 Analog; key A as easyrazer captured it."""

    def __init__(self):
        self.t = FakeTransport()
        for p in (0, 1):
            self.t.keys[(p, A)] = bytearray([p] + KEY_A[1:])

    def __call__(self, transport=None):
        self.t.model = hc.set_active_model(ANALOG)
        return _REAL(transport or self.t)


@pytest.fixture
def plugged(monkeypatch):
    p = _Plug()
    monkeypatch.setattr(hc, "Keyboard", p)
    return p


def test_api_reads_and_sets_depth(plugged):
    from test_app_proxy import FakeService, make_api
    import app
    hc.set_experimental(True)
    api = make_api(app, FakeService())
    assert api.model()["data"]["actuation"]["min"] == 1.62
    r = api.set_depth([A], 2.5)
    assert r["ok"] and r["data"]["failed"] == [] and r["data"]["done"] == {A: (2.5, 2.4)}
    assert api.set_depth([A], 1.0)["ok"] is False
    assert api.read_depths()["data"][A] == (2.5, 2.4)


def test_cli_depth_respects_the_model_range(plugged, capsys):
    import huntsman
    hc.set_experimental(True)
    huntsman.main(["depth", "2.25", "A"])
    assert "1 keys now type at 2.25 mm" in capsys.readouterr().out
    assert tuple(plugged.t.keys[(0, A)][3:5]) == (scale().threshold(2.25), scale().threshold(2.15))
    with pytest.raises(ValueError, match="1.62-3.56"):
        huntsman.main(["depth", "0.5", "A"])


def test_cli_status_shows_the_a_key(plugged, capsys):
    import huntsman
    huntsman.main(["status"])
    out = capsys.readouterr().out
    assert "Huntsman V2 Analog (1532:0266), experimental" in out and "A key: types at 1.62 mm, resets at 1.54 mm" in out


def test_cli_factory_is_refused(plugged):
    import huntsman
    hc.set_experimental(True)
    with pytest.raises(hc.FeatureUnavailable, match="factory"):
        huntsman.main(["factory"])
    assert writes(plugged.t) == []


def test_just_above_always_follows_the_actuation_point():
    """Without a reset point the reset point follows 0.1 mm above the new actuation point, as the window's "Just
    above" says, even when the stored release byte would still fit; the saved and live copies end up the same."""
    hc.set_experimental(True)
    t = FakeTransport()
    t.keys[(0, A)] = bytearray([0, A, 0, 200, 20, 0x02, 0x02, 0x00, 0x04])
    t.keys[(1, A)] = bytearray([1, A, 0, 200, 60, 0x02, 0x02, 0x00, 0x04])
    thr = scale().threshold(2.0)
    analog(t).set_actuation([A], 2.0)
    for p in (0, 1):
        assert tuple(t.keys[(p, A)][3:5]) == (thr, scale().release(thr))


def test_keys_already_at_the_target_are_not_written_again():
    hc.set_experimental(True)
    t = FakeTransport()
    thr = scale().threshold(2.0)
    rel = scale().release(thr)
    for p in (0, 1):
        t.keys[(p, A)] = bytearray([p, A, 0, thr, rel, 0x02, 0x02, 0x00, 0x04])
    assert analog(t).set_actuation([A], 2.0) == []
    assert writes(t) == []


def test_the_v3_pro_still_writes_keys_already_at_the_target():
    t = FakeTransport()
    for p in (0, 1):
        t.keys[(p, A)] = bytearray([p, A, 0, 76, 70, 0x02, 0x02, 0x00, 0x04])
    hc.Keyboard(t).set_actuation([A], 1.2)   # 1.2 mm is the factory 76/70
    assert len(writes(t)) == 2
