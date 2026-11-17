# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Model table, layouts, detection, the experimental-support gate and the LED check, against FakeTransport.
Settings go to tmp_path; nothing here opens USB."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import depth_stream  # noqa: E402
import huntsman_core as hc  # noqa: E402
import models  # noqa: E402
from test_core import FakeTransport  # noqa: E402

PIDS = [0x02A6, 0x02A7, 0x02CF, 0x02B0, 0x026C, 0x026B, 0x0266]
MATRIX = {0x02A6: (6, 22), 0x02A7: (6, 22), 0x02CF: (6, 22), 0x02B0: (5, 15),
          0x026C: (6, 22), 0x026B: (6, 18), 0x0266: (8, 23)}
KEY_COUNT = {0x02A6: 104, 0x02A7: 84, 0x02CF: 104, 0x02B0: 61, 0x026C: 104, 0x026B: 87, 0x0266: 104}
V3 = [0x02A7, 0x02CF, 0x02B0]
V2 = [0x026C, 0x026B, 0x0266]
EXPERIMENTAL = V3 + V2
HEX = "{:04X}".format
FIELDS = {"name", "label", "x", "y", "w", "h", "id", "led"}
WRITES = {(0x0F, 0x02), (0x0F, 0x03), (0x0F, 0x04), (0x02, 0x12), (0x02, 0x1A), (0x02, 0x20), (0x02, 0x21),
          (0x00, 0x04)}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    import app as appmod
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(appmod, "STATE_FILE", str(tmp_path / "state.json"))
    hc.set_active_model(0x02A6)
    yield
    hc.set_active_model(0x02A6)


def kb_for(pid, t=None):
    return hc.Keyboard(t or FakeTransport(), model=models.by_pid(pid))


def writes(t):
    return [r for r in t.sent if (r[6], r[7]) in WRITES]


# ---------- the table ----------

def test_table_has_the_seven_models_in_search_order():
    assert list(models.MODELS) == PIDS
    assert models.DEFAULT is models.by_pid(0x02A6)
    assert models.by_pid(0x1234) is None


def test_only_the_02a6_is_verified():
    assert [p for p, m in models.MODELS.items() if m.verified] == [0x02A6]
    assert all(models.by_pid(p).status == models.EXPERIMENTAL for p in EXPERIMENTAL)


@pytest.mark.parametrize("pid", PIDS, ids=HEX)
def test_matrix_sizes(pid):
    assert models.by_pid(pid).matrix == MATRIX[pid]


def test_02a6_is_exactly_todays_keyboard():
    m = models.by_pid(0x02A6)
    assert set(m.effects) == set(hc.EFFECTS)
    assert m.matrix == (hc.FRAME_ROWS, hc.FRAME_COLS) and m.frame_size == hc.FRAME_SIZE
    assert m.layout == "layout.json"
    assert all(m.has(f) for f in models.FEATURES)


def test_capabilities():
    for p in V3:
        m = models.by_pid(p)
        assert m.actuation and m.rapid and m.snap_tap and m.per_key and m.studio and not m.key_tester
    for p in V2:
        m = models.by_pid(p)
        assert not (m.actuation or m.rapid or m.snap_tap or m.key_tester) and m.per_key and m.studio


def test_effects_are_only_ones_verified_on_the_02a6():
    for p in PIDS:
        assert set(models.by_pid(p).effects) <= set(hc.EFFECTS)
    for p in (0x02A7, 0x02CF, 0x02B0, 0x026C, 0x026B):
        assert set(models.by_pid(p).effects) == set(hc.EFFECTS)
    analog = set(models.by_pid(0x0266).effects)
    assert analog == {e for e in hc.EFFECTS if not e.startswith("starlight")}


def test_frame_size_field():
    assert {p: models.by_pid(p).frame_size for p in PIDS} == {**{p: 0x47 for p in PIDS}, 0x0266: 5 + 23 * 3}


# ---------- layouts ----------

@pytest.mark.parametrize("pid", PIDS, ids=HEX)
def test_layout_fits_the_matrix(pid):
    m = models.by_pid(pid)
    layout = hc.load_layout(m)
    assert len(layout) == KEY_COUNT[pid]
    assert all(set(k) == FIELDS for k in layout)
    ids = [k["id"] for k in layout]
    names = [k["name"] for k in layout]
    leds = [tuple(k["led"]) for k in layout]
    assert len(set(ids)) == len(ids) and len(set(names)) == len(names)
    assert len(set(leds)) == len(leds), "two keys share an LED"
    assert all(0 <= r < m.rows and 0 <= c < m.cols for r, c in leds)
    assert "RIGHT_GUI" in names  # Fn


def test_layout_files_exist_for_every_experimental_model():
    for p in EXPERIMENTAL:
        assert os.path.exists(os.path.join(ROOT, "layouts", f"{p:04X}.json"))


def test_full_size_leds_follow_the_02a6_by_name():
    ref = {k["name"]: k["led"] for k in hc.load_layout(models.DEFAULT)}
    for p in (0x02A7, 0x02CF, 0x026C, 0x026B, 0x0266):
        assert all(k["led"] == ref[k["name"]] for k in hc.load_layout(models.by_pid(p)))


def test_mini_leds_are_one_row_up_from_the_same_spot():
    full = {(k["x"], k["y"]): k["led"] for k in hc.load_layout(models.DEFAULT)}
    for k in hc.load_layout(models.by_pid(0x02B0)):
        r, c = full[(k["x"], k["y"] + 1.25)]
        assert k["led"] == [r - 1, c]


def test_layout_follows_the_active_model():
    hc.set_active_model(0x02B0)
    assert len(hc.load_layout()) == 61 and hc.frame_shape() == (5, 15)
    assert hc.active_model().pid == 0x02B0
    assert 59 not in hc.all_key_ids() and set(hc.all_key_ids()) < set(hc.every_key_id())
    hc.set_active_model(models.by_pid(0x02A6))
    assert len(hc.load_layout()) == 104 and hc.frame_shape() == (6, 22)


def test_set_active_model_refuses_unknown_pid():
    with pytest.raises(hc.DeviceError):
        hc.set_active_model(0x1234)


# ---------- detection ----------

def finder(*present):
    calls = []

    def find(vid, pid):
        calls.append((vid, pid))
        return f"dev-{pid:04X}" if vid == hc.VID and pid in present else None
    find.calls = calls
    return find


@pytest.mark.parametrize("pid", PIDS, ids=HEX)
def test_detect_each_model(pid):
    model, dev = hc.detect(finder(pid))
    assert model.pid == pid and dev == f"dev-{pid:04X}"


def test_detect_takes_the_first_in_table_order():
    model, _ = hc.detect(finder(0x0266, 0x02A6))
    assert model.pid == 0x02A6
    model, _ = hc.detect(finder(0x0266, 0x02B0))
    assert model.pid == 0x02B0


def test_detect_refuses_unsupported_keyboards():
    f = finder(0x0227)  # Huntsman (first generation): not in the table
    with pytest.raises(hc.DeviceError):
        hc.detect(f)
    assert {pid for _, pid in f.calls} == set(PIDS)


def test_keyboard_uses_the_transport_model_then_the_active_one():
    t = FakeTransport()
    assert hc.Keyboard(t).model is models.DEFAULT
    t.model = models.by_pid(0x02B0)
    assert hc.Keyboard(t).model.pid == 0x02B0
    hc.set_active_model(0x026B)
    assert hc.Keyboard(FakeTransport()).model.pid == 0x026B


def test_listeners_match_the_active_pid():
    from inputs import keys
    assert keys.product_id() == 0x02A6
    hc.set_active_model(0x02A7)
    assert keys.product_id() == 0x02A7 and depth_stream.product_id() == 0x02A7


# ---------- the experimental-support setting ----------

def test_experimental_setting_defaults_off_and_persists(tmp_path):
    assert hc.experimental_enabled() is False
    hc.set_experimental(True)
    assert hc.experimental_enabled() is True
    with open(tmp_path / "state.json") as f:
        assert json.load(f)["experimental"] is True
    hc.set_experimental(False)
    assert hc.experimental_enabled() is False


@pytest.mark.parametrize("raw", ["{not json", "[]", '{"experimental": "yes"}', '{"experimental": 1}'])
def test_bad_setting_reads_as_off(tmp_path, raw):
    (tmp_path / "state.json").write_text(raw)
    assert hc.experimental_enabled() is False


def test_app_state_keeps_the_setting():
    import app as appmod
    hc.set_experimental(True)
    with appmod.update_state() as st:
        st["ui"]["accent"] = "#112233"
    assert appmod.load_state()["experimental"] is True and hc.experimental_enabled() is True
    assert appmod.DEFAULT_STATE["experimental"] is False


def test_set_experimental_keeps_other_state():
    import app as appmod
    with appmod.update_state() as st:
        st["ui"]["accent"] = "#112233"
    hc.set_experimental(True)
    assert appmod.load_state()["ui"]["accent"] == "#112233"


# ---------- the gate ----------

LIGHTING_WRITES = {
    "set_effect": lambda kb: kb.set_effect("static", [1, 2, 3]),
    "set_brightness": lambda kb: kb.set_brightness(50),
    "set_custom": lambda kb: kb.set_custom({31: [1, 2, 3]}, hc.load_layout(kb.model)),
    "enter_custom_mode": lambda kb: kb.enter_custom_mode(),
    "send_frame_fast": lambda kb: kb.send_frame_fast([[[0, 0, 0]] * kb.model.cols for _ in range(kb.model.rows)]),
    "light_cell": lambda kb: kb.light_cell(0, 1),
}
ANALOG_WRITES = {
    "set_actuation": lambda kb: kb.set_actuation([31], 2.0),
    "restore_factory": lambda kb: kb.restore_factory([31]),
    "restore_snapshot": lambda kb: kb.restore_snapshot(
        {"saved_profile": 1, "profiles": {"0": {"31": "001f00804c02020004"}}, "skipped": []}),
    "set_rapid": lambda kb: kb.set_rapid([(31, (0.3, 0.3))]),
    "set_rapid_off": lambda kb: kb.set_rapid([(31, None)]),
    "set_continuous": lambda kb: kb.set_continuous(True),
    "set_snap_tap": lambda kb: kb.set_snap_tap((31, 33)),
    "set_snap_tap_off": lambda kb: kb.set_snap_tap(None),
}
DRIVER_MODE = {"driver_mode": lambda kb: kb.cmd(0x00, 0x04, [3, 0], 2),
               "hardware_mode": lambda kb: kb.cmd(0x00, 0x04, [0, 0], 2)}
ALL_WRITES = {**LIGHTING_WRITES, **ANALOG_WRITES, **DRIVER_MODE}


@pytest.mark.parametrize("pid", EXPERIMENTAL, ids=HEX)
@pytest.mark.parametrize("name", sorted(ALL_WRITES))
def test_switch_off_blocks_every_write_before_the_transport(pid, name):
    t = FakeTransport()
    with pytest.raises(hc.DeviceError) as e:
        ALL_WRITES[name](kb_for(pid, t))
    assert isinstance(e.value, (hc.ExperimentalLocked, hc.FeatureUnavailable))
    assert t.sent == []


@pytest.mark.parametrize("pid", EXPERIMENTAL, ids=HEX)
def test_switch_off_message_is_plain(pid):
    with pytest.raises(hc.ExperimentalLocked, match="Experimental support"):
        kb_for(pid).set_effect("spectrum")


@pytest.mark.parametrize("pid", EXPERIMENTAL, ids=HEX)
def test_reads_are_always_allowed(pid):
    t = FakeTransport()
    kb = kb_for(pid, t)
    kb.firmware()
    kb.brightness()
    kb.get_effect_raw()
    kb.active_profile()
    assert len(t.sent) == 4 and writes(t) == []


@pytest.mark.parametrize("pid", EXPERIMENTAL, ids=HEX)
@pytest.mark.parametrize("name", sorted(LIGHTING_WRITES))
def test_switch_on_allows_lighting(pid, name):
    hc.set_experimental(True)
    t = FakeTransport()
    LIGHTING_WRITES[name](kb_for(pid, t))
    assert writes(t)


@pytest.mark.parametrize("pid", V3, ids=HEX)
@pytest.mark.parametrize("name", sorted(ANALOG_WRITES))
def test_switch_on_allows_analog_settings_on_v3_models(pid, name):
    hc.set_experimental(True)
    t = FakeTransport()
    ANALOG_WRITES[name](kb_for(pid, t))
    assert writes(t)


@pytest.mark.parametrize("pid", V2, ids=HEX)
@pytest.mark.parametrize("name", sorted(ANALOG_WRITES))
def test_v2_family_never_gets_analog_settings(pid, name):
    hc.set_experimental(True)
    t = FakeTransport()
    with pytest.raises(hc.FeatureUnavailable):
        ANALOG_WRITES[name](kb_for(pid, t))
    assert t.sent == []


@pytest.mark.parametrize("pid", V2, ids=HEX)
def test_v2_family_has_no_key_reads_either(pid):
    t = FakeTransport()
    kb = kb_for(pid, t)
    with pytest.raises(hc.FeatureUnavailable):
        kb.read_points(31)
    with pytest.raises(hc.FeatureUnavailable):
        kb.snapshot([31])
    assert t.sent == []


@pytest.mark.parametrize("pid", EXPERIMENTAL, ids=HEX)
@pytest.mark.parametrize("name", sorted(DRIVER_MODE))
def test_driver_mode_never_on_experimental_models(pid, name):
    hc.set_experimental(True)
    t = FakeTransport()
    with pytest.raises(hc.FeatureUnavailable):
        DRIVER_MODE[name](kb_for(pid, t))
    assert t.sent == []


@pytest.mark.parametrize("pid", EXPERIMENTAL, ids=HEX)
def test_key_tester_session_refuses_experimental_models(pid):
    hc.set_experimental(True)
    t = FakeTransport()
    s = depth_stream.DepthSession(kb_for(pid, t), lambda b: None, lambda r: None)
    with pytest.raises(hc.FeatureUnavailable):
        s.start()
    assert t.sent == []


@pytest.mark.parametrize("pid", EXPERIMENTAL, ids=HEX)
def test_recover_typing_leaves_experimental_models_alone(pid):
    hc.set_experimental(True)
    t = FakeTransport()
    t.mode = depth_stream.MODE_DRIVER
    assert depth_stream.recover_typing(kb_for(pid, t)) is False
    assert t.sent == []


@pytest.mark.parametrize("pid", EXPERIMENTAL, ids=HEX)
def test_unknown_commands_never_reach_experimental_models(pid):
    hc.set_experimental(True)
    t = FakeTransport()
    with pytest.raises(hc.FeatureUnavailable):
        kb_for(pid, t).cmd(0x0F, 0x10, [1, 2, 3])
    assert t.sent == []


@pytest.mark.parametrize("name", sorted(ALL_WRITES))
def test_verified_model_never_consults_the_switch(monkeypatch, name):
    def boom():
        raise AssertionError("the switch was read for the verified model")
    monkeypatch.setattr(hc, "experimental_enabled", boom)
    t = FakeTransport()
    ALL_WRITES[name](kb_for(0x02A6, t))
    assert writes(t)


def test_effect_missing_on_the_model_is_refused():
    hc.set_experimental(True)
    t = FakeTransport()
    with pytest.raises(hc.FeatureUnavailable):
        kb_for(0x0266, t).set_effect("starlight_random", speed=1)
    assert t.sent == []


def test_gate_function_for_the_interface():
    m = models.by_pid(0x02A7)
    with pytest.raises(hc.ExperimentalLocked):
        hc.gate(m, "lighting")
    hc.set_experimental(True)
    hc.gate(m, "actuation")
    with pytest.raises(hc.FeatureUnavailable):
        hc.gate(m, "key_tester")
    with pytest.raises(hc.FeatureUnavailable):
        hc.gate(models.by_pid(0x026C), "rapid")
    assert kb_for(0x02A7).allowed("lighting") is True
    assert kb_for(0x02A7).allowed("key_tester") is False


# ---------- frame size follows the matrix ----------

@pytest.mark.parametrize("pid", PIDS, ids=HEX)
def test_custom_frames_follow_the_matrix(pid):
    hc.set_experimental(True)
    m = models.by_pid(pid)
    t = FakeTransport()
    kb_for(pid, t).set_custom({31: [255, 255, 255]}, hc.load_layout(m))
    frames = t.writes(0x0F, 0x03)
    assert len(frames) == m.rows
    for i, r in enumerate(frames):
        assert r[5] == m.frame_size and list(r[8:13]) == [0, 0, i, 0, m.cols - 1]
        assert not any(r[13 + 3 * m.cols:88])  # nothing after the last column
    lit = {(i, c) for i, r in enumerate(frames) for c in range(m.cols) if r[13 + 3 * c]}
    a = next(k for k in hc.load_layout(m) if k["id"] == 31)
    assert lit == {tuple(a["led"])}


@pytest.mark.parametrize("pid", PIDS, ids=HEX)
def test_fast_frames_follow_the_matrix(pid):
    hc.set_experimental(True)
    m = models.by_pid(pid)
    t = FakeTransport()
    kb = kb_for(pid, t)
    kb.send_frame_fast([[[1, 2, 3]] * m.cols for _ in range(m.rows)])
    assert [list(r[8:13]) for r in t.sent] == [[0, 0, i, 0, m.cols - 1] for i in range(m.rows)]
    assert all(r[5] == m.frame_size for r in t.sent)
    wrong = (6, 22) if m.matrix != (6, 22) else (5, 15)
    with pytest.raises(ValueError):
        kb.send_frame_fast([[[0, 0, 0]] * wrong[1] for _ in range(wrong[0])])


def test_frame_rows_uses_the_given_shape():
    rows = hc.frame_rows({31: [1, 2, 3]}, hc.load_layout(models.by_pid(0x0266)), shape=(8, 23))
    assert len(rows) == 8 and all(len(r) == 23 for r in rows)
    hc.set_active_model(0x026B)
    assert [len(r) for r in hc.frame_rows({}, hc.load_layout())] == [18] * 6


def test_engine_rows_follow_the_active_model():
    from lighting import engine as eng
    hc.set_active_model(0x02B0)
    import lighting.frame as fr
    e = eng.Engine.__new__(eng.Engine)
    e.keymap = fr.Keymap.load()
    e._lut = list(range(256))
    rows = e._rows({e.keymap.ids[0]: (9, 9, 9)})
    assert len(rows) == 5 and all(len(r) == 15 for r in rows)


# ---------- LED check ----------

@pytest.mark.parametrize("pid", PIDS, ids=HEX)
def test_light_cell_lights_exactly_one_cell(pid):
    hc.set_experimental(True)
    m = models.by_pid(pid)
    t = FakeTransport()
    r0, c0 = m.rows - 1, m.cols - 1
    kb_for(pid, t).light_cell(r0, c0)
    frames = t.writes(0x0F, 0x03)
    assert len(frames) == m.rows
    lit = {(i, c) for i, r in enumerate(frames) for c in range(m.cols) if any(r[13 + 3 * c:16 + 3 * c])}
    assert lit == {(r0, c0)}
    assert list(frames[r0][13 + 3 * c0:16 + 3 * c0]) == [255, 255, 255]
    last = t.sent[-1]
    assert (last[6], last[7]) == (0x0F, 0x02) and list(last[8:11]) == [0, 0, 8]


@pytest.mark.parametrize("cell", [(-1, 0), (0, -1), (5, 0), (0, 15), (1.5, 0), ("1", 0), (True, 0)])
def test_light_cell_rejects_cells_outside_the_matrix(cell):
    hc.set_experimental(True)
    t = FakeTransport()
    with pytest.raises(ValueError):
        kb_for(0x02B0, t).light_cell(*cell)
    assert t.sent == []


def test_light_cell_is_gated():
    t = FakeTransport()
    with pytest.raises(hc.ExperimentalLocked):
        kb_for(0x02B0, t).light_cell(0, 0)
    assert t.sent == []


def test_model_info_for_the_interface():
    info = models.by_pid(0x026B).info()
    assert info["pid"] == "026B" and info["status"] == "experimental" and info["matrix"] == [6, 18]
    assert info["features"]["actuation"] is False and info["features"]["lighting"] is True
