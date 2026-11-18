# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Other Huntsman models through the app (app.Api), the lighting service, Studio and the command line: the
detected model is reported, writes to experimental models are refused with a plain message until Experimental
support is on, features a model lacks are skipped quietly, and Studio and its presets follow the model's
layout. FakeTransport only; settings go to tmp_path; nothing here opens USB."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import huntsman_core as hc  # noqa: E402
import models  # noqa: E402
from test_app_proxy import FakeService, make_api  # noqa: E402
from test_core import FakeTransport  # noqa: E402
from test_studio import REAL_KEYBOARD, FakeEngine, _Menu, hooks  # noqa: E402,F401 (fixtures)

MINI, TKL, V2, ANALOG, V3 = 0x02B0, 0x02A7, 0x026C, 0x0266, 0x02A6
WRITES = {(0x0F, 0x02), (0x0F, 0x03), (0x0F, 0x04), (0x02, 0x12), (0x02, 0x1A), (0x02, 0x20), (0x02, 0x21),
          (0x00, 0x04)}


@pytest.fixture
def app(tmp_path, monkeypatch):
    import app as appmod
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(appmod, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(appmod, "SNAPSHOT_FILE", str(tmp_path / "first-launch-snapshot.json"))
    hc.set_active_model(V3)
    yield appmod
    hc.set_active_model(V3)


class Plugged:
    """hc.Keyboard() as UsbTransport would build it: detection sets the active model, then the keyboard uses it.
    `pid` None means no keyboard is plugged in."""

    def __init__(self, pid):
        self.pid, self.t = pid, FakeTransport()

    def __call__(self, transport=None):
        if transport is not None:
            return REAL_KEYBOARD(transport)
        if self.pid is None:
            raise hc.DeviceError("No supported Razer Huntsman found. Is it plugged in by USB?")
        self.t.model = hc.set_active_model(self.pid)
        return REAL_KEYBOARD(self.t)


@pytest.fixture
def plug(monkeypatch):
    def make(pid):
        p = Plugged(pid)
        monkeypatch.setattr(hc, "Keyboard", p)
        return p
    return make


def writes(t):
    return [r for r in t.sent if (r[6], r[7]) in WRITES]


def api_for(app, svc=None):
    return make_api(app, svc or FakeService())


# ---------- the model, as the window sees it ----------

def test_model_reports_the_verified_keyboard(app, plug):
    plug(V3)
    m = api_for(app).model()
    assert m["ok"] is True
    d = m["data"]
    assert d["pid"] == "02A6" and d["name"] == "Huntsman V3 Pro" and d["status"] == "verified"
    assert d["matrix"] == [6, 22] and all(d["features"].values())
    assert d["experimental_on"] is False and d["locked"] is False


def test_model_reports_an_experimental_keyboard_and_the_switch(app, plug):
    plug(MINI)
    api = api_for(app)
    d = api.model()["data"]
    assert d["pid"] == "02B0" and d["status"] == "experimental" and d["matrix"] == [5, 15]
    assert d["features"]["key_tester"] is False and d["locked"] is True
    assert api.experimental() == {"ok": True, "data": False}
    assert api.set_experimental(True) == {"ok": True, "data": True}
    assert hc.experimental_enabled() is True and api.experimental()["data"] is True
    assert api.model()["data"]["locked"] is False and api.model()["data"]["experimental_on"] is True


def test_set_experimental_needs_true_or_false(app, plug):
    plug(MINI)
    r = api_for(app).set_experimental("yes")
    assert r["ok"] is False and "true or false" in r["error"] and hc.experimental_enabled() is False


def test_turning_the_switch_off_stops_studio_first(app, plug):
    plug(MINI)
    svc = FakeService()
    api = api_for(app, svc)
    api.set_experimental(True)
    svc.calls.clear()
    assert api.set_experimental(False)["ok"]
    # Studio stops (and the keyboard's own lighting comes back) while writes are still allowed
    assert ("studio_enable", {"on": False}) in svc.calls and hc.experimental_enabled() is False


def test_layout_and_effects_follow_the_detected_model(app, plug):
    plug(ANALOG)
    api = api_for(app)
    assert api.model()["ok"]
    assert len(api.layout()) == 104
    assert not any(n.startswith("starlight") for n in api.effects())
    plug(MINI)
    api = api_for(app)
    api.model()
    assert len(api.layout()) == 61 and "starlight_one" in api.effects()


def test_info_carries_the_model(app, plug):
    plug(TKL)
    d = api_for(app).info()["data"]
    assert d["model"]["pid"] == "02A7" and d["model"]["status"] == "experimental"


# ---------- writes while locked ----------

@pytest.mark.parametrize("call", [
    lambda a: a.set_effect("static", {"rgb1": [0, 0, 255]}),
    lambda a: a.set_custom([0, 0, 0], {}),
    lambda a: a.set_brightness(40),
    lambda a: a.set_depth([], 1.0),
    lambda a: a.set_rapid({"enabled": True, "press": 0.3, "release": 0.3, "keys": "all", "continuous": False}),
    lambda a: a.set_snap([4, 7]),
], ids=["effect", "custom", "brightness", "depth", "rapid", "snap"])
def test_locked_writes_get_a_plain_error_and_keep_the_connection(app, plug, call):
    p = plug(MINI)
    svc = FakeService()
    api = api_for(app, svc)
    api.model()
    svc.calls.clear()
    r = call(api)
    assert r["ok"] is False and r["reason"] == "experimental"
    assert "experimental" in r["error"] and "Experimental support" in r["error"]
    assert writes(p.t) == [] and api._kb is not None          # nothing sent; no reconnect needed
    assert ("studio_enable", {"on": False, "restore": False}) not in svc.calls   # Studio left alone


def test_missing_features_get_a_plain_error(app, plug):
    p = plug(V2)
    api = api_for(app)
    api.model()
    hc.set_experimental(True)
    r = api.set_depth([], 1.0)
    assert r["ok"] is False and r["reason"] == "unavailable" and "isn't available on the Huntsman V2" in r["error"]
    assert api.start_test()["reason"] == "unavailable"
    assert writes(p.t) == [] and api._kb is not None


def test_v2_has_no_depths_to_read(app, plug):
    plug(V2)
    assert api_for(app).read_depths() == {"ok": True, "data": {}}


def test_switch_on_lets_lighting_through(app, plug):
    p = plug(MINI)
    api = api_for(app)
    api.set_experimental(True)
    assert api.set_custom([1, 2, 3], {})["ok"]
    assert len([r for r in p.t.sent if (r[6], r[7]) == (0x0F, 0x03)]) == 5   # five rows on the 5 x 15 Mini


# ---------- LED check ----------

def test_led_check_is_locked_until_the_switch_is_on(app, plug):
    p = plug(MINI)
    api = api_for(app)
    r = api.led_check(0, 0)
    assert r["ok"] is False and r["reason"] == "experimental" and writes(p.t) == []


def test_led_check_lights_a_cell_and_ending_it_restores_the_lighting(app, plug):
    p = plug(MINI)
    svc = FakeService()
    api = api_for(app, svc)
    api.set_experimental(True)
    assert api.led_check(4, 14) == {"ok": True, "data": [4, 14]}
    frames = [r for r in p.t.sent if (r[6], r[7]) == (0x0F, 0x03)]
    assert len(frames) == 5
    lit = [(r[10], i) for r in frames for i in range(15) if any(r[13 + 3 * i:16 + 3 * i])]
    assert lit == [(4, 14)]
    assert ("studio_enable", {"on": False, "restore": False}) in svc.calls   # Studio would hide the cell
    p.t.sent.clear()
    assert api.end_led_check()["ok"]
    assert [(r[6], r[7]) for r in writes(p.t)] == [(0x0F, 0x02)]   # the effect stored on the keyboard, in RAM


def test_led_check_refuses_cells_outside_the_matrix(app, plug):
    plug(MINI)
    api = api_for(app)
    api.set_experimental(True)
    for cell in [(5, 0), (0, 15), (-1, 0), ("1", 2), (True, 0)]:
        r = api.led_check(*cell)
        assert r["ok"] is False and api._kb is not None


# ---------- re-sending what the keyboard keeps only in RAM ----------

def saved_everything(app):
    with app.update_state() as st:
        st["custom"] = {"base": [1, 2, 3], "keys": {}}
        st["rapid"] = {"enabled": True, "press": 0.3, "release": 0.3, "keys": "all", "continuous": False}
        st["snap"] = [4, 7]


def test_locked_model_resends_nothing_and_says_so_once(app, plug, capsys):
    p = plug(MINI)
    saved_everything(app)
    kb = hc.Keyboard()
    capsys.readouterr()
    assert app.apply_saved(kb) == []
    assert writes(p.t) == []
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "Traceback" not in err
    assert "experimental" in err and "per-key colours" in err


def test_v2_skips_settings_it_lacks_without_noise(app, plug, capsys):
    p = plug(V2)
    saved_everything(app)
    hc.set_experimental(True)
    kb = hc.Keyboard()
    capsys.readouterr()
    assert app.apply_saved(kb) == ["per-key colours"]
    assert {(r[6], r[7]) for r in writes(p.t)} == {(0x0F, 0x03), (0x0F, 0x02)}
    err = capsys.readouterr().err
    assert "Traceback" not in err and err.count("\n") <= 1


def test_v2_connects_without_a_snapshot_or_traceback(app, plug, capsys):
    plug(V2)
    capsys.readouterr()
    assert api_for(app).startup()["ok"] is True
    assert not os.path.exists(app.SNAPSHOT_FILE)
    assert "Traceback" not in capsys.readouterr().err


def test_experimental_v3_still_gets_its_first_launch_snapshot(app, plug):
    plug(TKL)
    assert api_for(app).startup()["ok"] is True
    assert os.path.exists(app.SNAPSHOT_FILE)


def test_restore_lighting_sends_nothing_while_locked(app, plug):
    p = plug(MINI)
    app.restore_lighting(hc.Keyboard())
    assert writes(p.t) == []


# ---------- the lighting service ----------

def make_service(hooks, **kw):
    import service
    from test_studio import Clock
    return service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=Clock(), **kw)


def test_service_opens_the_keyboard_before_loading_the_layout(app, plug, hooks):
    plug(MINI)
    s = make_service(hooks)
    s.start()
    try:
        assert len(s.studio.keymap.ids) == 61 and len(s.studio.engine.keymap.ids) == 61
    finally:
        s.shutdown()


def test_service_follows_a_keyboard_plugged_in_later(app, plug, hooks):
    p = plug(None)
    s = make_service(hooks)
    s.start()
    try:
        assert len(s.studio.engine.keymap.ids) == 104
        p.pid = MINI
        s._engine_keyboard()
        assert len(s.studio.engine.keymap.ids) == 61 and len(s.studio.keymap.ids) == 61
    finally:
        s.shutdown()


def test_service_keeps_studio_off_on_a_locked_model_with_one_log_line(app, plug, hooks, capsys):
    plug(MINI)
    with app.update_state() as st:
        st["studio"]["enabled"] = True
    s = make_service(hooks)
    capsys.readouterr()
    s.start()
    try:
        assert not s.studio.engine.running and hooks["keys"] == []
        assert s.studio.summary()["enabled"] is False    # the window and the menu show it off
        err = capsys.readouterr().err
        assert err.count("\n") == 1 and "Traceback" not in err and "experimental" in err
        r = s.handle("studio_enable", {"on": True})
        assert r["ok"] is False and "Experimental support" in r["error"] and not s.studio.engine.running
    finally:
        s.shutdown()


def test_service_runs_studio_once_the_switch_is_on(app, plug, hooks):
    plug(MINI)
    hc.set_experimental(True)
    s = make_service(hooks)
    s.start()
    try:
        assert s.handle("studio_enable", {"on": True})["ok"] and s.studio.engine.running
    finally:
        s.shutdown()


def test_menu_toggle_on_a_locked_model_logs_one_line(app, plug, hooks, capsys):
    import service
    plug(MINI)
    s = make_service(hooks)
    s.start()
    try:
        menu = service.make_menu(s, _Menu, on_open=lambda: None, on_quit=lambda: None, run=lambda fn: fn())
        capsys.readouterr()
        menu.on_toggle(True)
        menu.on_preset("Aurora")
        assert not s.studio.engine.running
        err = capsys.readouterr().err
        assert "Traceback" not in err and err.count("\n") == 2
    finally:
        s.shutdown()


# ---------- Studio presets on smaller layouts ----------

@pytest.mark.parametrize("pid", [MINI, TKL, 0x026B], ids="{:04X}".format)
def test_builtin_presets_render_on_smaller_layouts(app, pid):
    """Every built-in preset streams real frames to a Mini or TKL: keys the layout lacks (numpad, function row,
    arrows) are skipped, including ones a layer names explicitly and presses of keys that aren't there."""
    from lighting.engine import Engine
    from lighting.frame import KeyEvent, Keymap
    from lighting.layers import Layer
    from lighting.presets import Preset, builtin_presets
    hc.set_experimental(True)
    m = hc.set_active_model(pid)
    km = Keymap(hc.load_layout(m))
    t = FakeTransport()
    t.model = m
    full = Keymap(hc.load_layout(models.DEFAULT))
    numpad = [k.id for k in full.keys if k.name.startswith("KEYPAD") or k.name.startswith("NUM")]
    missing = [k for k in full.ids if k not in km]
    assert missing
    extra = Preset("Numpad", [Layer("base", "solid", {"color": [9, 9, 9]}),
                              Layer("pad", "solid", {"color": [255, 0, 0]}, keys=numpad + missing[:3] + km.ids[:2])])
    for preset in builtin_presets(km) + [extra]:
        eng = Engine(lambda: REAL_KEYBOARD(t, model=m), km, fps=30)
        eng.set_preset(preset)
        for k in [km.ids[0], missing[0]]:
            eng.push_key_event(KeyEvent(k, True, 1.0))
        t.sent.clear()
        assert eng.step(1.05) is True, preset.name
        rows = [r for r in t.sent if (r[6], r[7]) == (0x0F, 0x03)]
        assert len(rows) == m.rows and all(r[12] == m.cols - 1 for r in rows), preset.name


# ---------- command line ----------

def test_cli_status_names_the_model(app, plug, capsys):
    import huntsman
    plug(MINI)
    huntsman.main(["status"])
    out = capsys.readouterr().out
    assert "Huntsman V3 Pro Mini" in out and "1532:02B0" in out and "experimental" in out
    assert "Experimental support: off" in out


def test_cli_status_of_the_verified_keyboard(app, plug, capsys):
    import huntsman
    plug(V3)
    huntsman.main(["status"])
    out = capsys.readouterr().out
    assert "Huntsman V3 Pro (1532:02A6), verified" in out and "A key: types at" in out
    assert "Experimental support" not in out


def test_cli_status_on_a_v2_skips_the_depth(app, plug, capsys):
    import huntsman
    plug(V2)
    huntsman.main(["status"])
    out = capsys.readouterr().out
    assert "Huntsman V2 (1532:026C)" in out and "A key" not in out


def test_cli_experimental_switch_needs_no_keyboard(app, plug, capsys):
    import huntsman
    plug(None)
    huntsman.main(["experimental", "on"])
    assert hc.experimental_enabled() is True and "Experimental support: on" in capsys.readouterr().out
    huntsman.main(["experimental", "off"])
    assert hc.experimental_enabled() is False and "Experimental support: off" in capsys.readouterr().out
    with pytest.raises(ValueError):
        huntsman.main(["experimental", "maybe"])


def test_cli_write_on_a_locked_model_raises_the_plain_error(app, plug):
    import huntsman
    p = plug(MINI)
    with pytest.raises(hc.ExperimentalLocked, match="Turn on Keyboard, Experimental support"):
        huntsman.main(["color", "255", "0", "0"])
    assert writes(p.t) == []


def test_switching_off_ends_an_led_check_first(app, plug):
    p = plug(MINI)
    api = api_for(app)
    api.set_experimental(True)
    api.led_check(0, 3)
    p.t.sent.clear()
    assert api.set_experimental(False)["ok"]
    assert [(r[6], r[7]) for r in writes(p.t)] == [(0x0F, 0x02)]   # lighting put back while still allowed
    assert hc.experimental_enabled() is False


# ---------- the first-launch snapshot belongs to one model ----------

def _snapshot(app):
    import json
    with open(app.SNAPSHOT_FILE) as f:
        return json.load(f)


def test_snapshot_records_the_model(app, plug):
    plug(V3)
    assert api_for(app).startup()["ok"] is True
    assert _snapshot(app)["pid"] == "02A6"


def test_locked_experimental_model_gets_its_snapshot_without_a_write(app, plug):
    """Chosen: the snapshot is taken even while Experimental support is off. It only reads, and it is the copy
    a tester wants before turning writes on."""
    p = plug(MINI)
    assert api_for(app).startup()["ok"] is True
    assert _snapshot(app)["pid"] == "02B0" and writes(p.t) == []


def test_restore_snapshot_refuses_another_models_snapshot(app, plug):
    plug(TKL)
    snap = hc.Keyboard().snapshot([31, 32])
    assert snap["pid"] == "02A7"
    p = plug(V3)
    with pytest.raises(hc.DeviceError, match=r"Huntsman V3 Pro TKL \(02A7\).*Huntsman V3 Pro \(02A6\)"):
        hc.Keyboard().restore_snapshot(snap)
    assert writes(p.t) == []


def test_snapshot_without_a_pid_is_an_02a6_snapshot(app, plug):
    """Snapshots written before v0.3.0 carry no PID; they came from the V3 Pro and stay valid there."""
    plug(V3)
    old = hc.Keyboard().snapshot([31, 32])
    del old["pid"]
    assert hc.Keyboard().restore_snapshot(old) == []
    hc.set_experimental(True)
    p = plug(TKL)
    with pytest.raises(hc.DeviceError, match=r"Huntsman V3 Pro \(02A6\)"):
        hc.Keyboard().restore_snapshot(old)
    assert writes(p.t) == []


def test_cli_restore_snapshot_refuses_another_model(app, plug):
    import huntsman
    plug(TKL)
    assert api_for(app).startup()["ok"] is True
    p = plug(V3)
    with pytest.raises(hc.DeviceError, match="02A7"):
        huntsman.main(["restore-snapshot"])
    assert writes(p.t) == []


# ---------- Studio meets a locked model while running ----------

def test_engine_refusal_turns_studio_off_with_one_log_line(app, plug, hooks, capsys):
    plug(MINI)
    hc.set_experimental(True)
    s = make_service(hooks)
    s.start()
    try:
        assert s.handle("studio_enable", {"on": True})["ok"] and s.studio.engine.running
        hc.set_experimental(False)          # e.g. the CLI turned the switch off
        capsys.readouterr()
        s._engine_error(hc.ExperimentalLocked("Support for the Huntsman V3 Pro Mini is experimental. Turn on "
                                              "Keyboard, Experimental support to change its settings."))
        assert not s.studio.engine.running and s.studio.summary()["enabled"] is False
        assert s._engine_broken is False    # not a lost connection: no reconnect
        err = capsys.readouterr().err
        assert err.count("\n") == 1 and "Traceback" not in err and "Studio off" in err
    finally:
        s.shutdown()


def test_engine_device_errors_still_reconnect(app, plug, hooks):
    plug(V3)
    s = make_service(hooks)
    s.start()
    try:
        s.handle("studio_enable", {"on": True})
        s._engine_error(hc.DeviceError("unplugged"))
        assert s._engine_broken is True and s.studio.engine.running
    finally:
        s.shutdown()


# ---------- the key listener matches the connected model's product id ----------

def test_key_listener_restarts_when_another_model_is_plugged_in(app, plug, hooks):
    p = plug(V3)
    hc.set_experimental(True)
    s = make_service(hooks)
    s.start()
    try:
        s.handle("set_heat", {"on": True})          # the heatmap counts presses: the key listener runs
        s.handle("studio_enable", {"on": True})
        assert len(hooks["keys"]) == 1 and hooks["keys"][0].running
        s._drop()                                    # same keyboard reconnects: the listener stays
        s._engine_keyboard()
        assert len(hooks["keys"]) == 1 and hooks["keys"][0].running
        s._drop()                                    # a Mini replaces it: a new listener matches 02B0
        p.pid = MINI
        s._engine_keyboard()
        assert len(hooks["keys"]) == 2 and not hooks["keys"][0].running and hooks["keys"][1].running
    finally:
        s.shutdown()


def test_no_key_listener_is_started_by_a_model_change_when_none_ran(app, plug, hooks):
    p = plug(None)
    s = make_service(hooks)
    s.start()
    try:
        p.pid = MINI
        s._engine_keyboard()
        assert hooks["keys"] == []
    finally:
        s.shutdown()


# ---------- huntsman.py experimental off stops Studio first, like the window ----------

class _SwitchWatcher(FakeService):
    """Records, for each request, whether Experimental support was still on when it arrived."""

    def request(self, cmd, args=None):
        self.switch_at = getattr(self, "switch_at", []) + [(cmd, hc.experimental_enabled())]
        return super().request(cmd, args)


def _cli_link(app, monkeypatch, svc):
    real = app.ServiceLink

    def never_start():
        raise AssertionError("the CLI must not start the lighting service to turn the switch off")
    monkeypatch.setattr(app, "ServiceLink", lambda: real(connect=svc.connect, starter=never_start, wait=0.2))


def test_cli_switch_off_stops_studio_while_writes_are_still_allowed(app, plug, monkeypatch, capsys):
    import huntsman
    plug(None)
    svc = _SwitchWatcher()
    _cli_link(app, monkeypatch, svc)
    hc.set_experimental(True)
    huntsman.main(["experimental", "off"])
    assert svc.calls == [("studio_enable", {"on": False})]
    assert svc.switch_at == [("studio_enable", True)]    # the lighting comes back before writes lock
    assert hc.experimental_enabled() is False and "Experimental support: off" in capsys.readouterr().out


def test_cli_switch_off_without_the_service_running(app, plug, monkeypatch, capsys):
    import huntsman
    plug(None)
    svc = FakeService(up=False)
    _cli_link(app, monkeypatch, svc)
    hc.set_experimental(True)
    huntsman.main(["experimental", "off"])
    assert hc.experimental_enabled() is False
    captured = capsys.readouterr()
    assert "Experimental support: off" in captured.out and "Traceback" not in captured.err


@pytest.mark.parametrize("start, arg", [(False, "on"), (False, "off"), (True, "on")])
def test_cli_switch_only_stops_studio_when_turning_it_off(app, plug, monkeypatch, start, arg):
    import huntsman
    plug(None)
    svc = FakeService()
    _cli_link(app, monkeypatch, svc)
    hc.set_experimental(start)
    huntsman.main(["experimental", arg])
    assert svc.calls == [] and hc.experimental_enabled() is (arg == "on")
