# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Studio integration (studio.py + the Api methods in app.py) with a fake engine, fake listeners and a fake
keyboard. State files go to tmp_path; no USB device, IOKit, microphone or window is touched."""
import contextlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import huntsman_core as hc  # noqa: E402
from inputs.types import InputPermissionError, KeyEvent  # noqa: E402
from test_core import FakeTransport  # noqa: E402

REAL_KEYBOARD = hc.Keyboard


class FakeEngine:
    def __init__(self, keyboard_factory, keymap, fps=30, *, restore=None, on_error=None, heat_enabled=False, **_):
        self.factory, self.keymap, self.fps, self.restore = keyboard_factory, keymap, fps, restore
        self.preset, self.brightness, self.running, self.depth = None, 1.0, False, 0
        self.log, self.events, self.audio, self.frames = [], [], None, []
        self.heat, self.heat_enabled = {}, heat_enabled

    def set_fps(self, fps):
        self.fps = fps

    def set_preset(self, p):
        self.preset = p
        self.log.append(("preset", p.name if p else None))

    def set_brightness(self, b):
        self.brightness = b

    def start(self):
        self.running = True
        self.log.append(("start",))

    def stop(self, restore=True):
        self.running = False
        self.log.append(("stop", restore))
        if restore and self.restore:
            self.restore()

    def pause(self):
        self.depth += 1

    def resume(self):
        self.depth = max(0, self.depth - 1)

    @contextlib.contextmanager
    def paused(self):
        self.pause()
        try:
            yield
        finally:
            self.resume()

    def push_key_event(self, e):
        self.events.append(e)

    def set_audio(self, a):
        self.audio = a

    def set_heat_enabled(self, on):
        self.heat_enabled = on

    def set_heat(self, counts):
        self.heat = dict(counts)

    def reset_heat(self):
        self.heat = {}

    def heat_counts(self):
        return dict(self.heat)

    def on_frame(self, cb):
        self.frames.append(cb)


class FakeListener:
    instances = []

    def __init__(self, *args, fail=None, **kw):
        self.args, self.kw, self.running, self.fail = args, kw, False, fail
        FakeListener.instances.append(self)

    def start(self):
        if self.fail:
            raise self.fail
        self.running = True

    def stop(self):
        self.running = False


class FakeSmart:
    def __init__(self, config, on_change):
        self.config, self.on_change, self.started = config, on_change, False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def set_config(self, cfg):
        self.config = cfg


@pytest.fixture
def app(tmp_path, monkeypatch):
    import app as appmod
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(appmod, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(appmod, "SNAPSHOT_FILE", str(tmp_path / "first-launch-snapshot.json"))
    return appmod


@pytest.fixture
def fake(monkeypatch):
    t = FakeTransport()
    monkeypatch.setattr(hc, "Keyboard", lambda transport=None: REAL_KEYBOARD(transport or t))
    return t


@pytest.fixture
def hooks():
    FakeListener.instances = []
    h = {"keys": [], "audio": [], "smart": [], "key_fail": None, "audio_fail": None}

    def keys(callback):
        lst = FakeListener(callback, fail=h["key_fail"])
        h["keys"].append(lst)
        return lst

    def audio(device, callback, sensitivity=1.0, on_error=None):
        lst = FakeListener(device, callback, sensitivity=sensitivity, on_error=on_error, fail=h["audio_fail"])
        h["audio"].append(lst)
        return lst

    def smart(config, on_change):
        s = FakeSmart(config, on_change)
        h["smart"].append(s)
        return s

    h["inputs"] = {"key_listener": keys, "audio_listener": audio, "smart_lighting": smart,
                   "list_devices": lambda: [{"index": 0, "name": "MacBook Microphone", "loopback": False},
                                            {"index": 3, "name": "BlackHole 2ch", "loopback": True}],
                   "schedule": None}
    return h


@pytest.fixture
def api(app, fake, hooks):
    a = app.Api(engine_cls=FakeEngine, inputs=hooks["inputs"])
    yield a
    a.shutdown()


def ok(r):
    assert r["ok"], r.get("error")
    return r["data"]


def err(r):
    assert not r["ok"]
    return r["error"]


def engine(api):
    return api._get_studio().engine


def layer(effect="solid", lid="l1", **kw):
    return {"id": lid, "effect": effect, "params": kw.pop("params", {}), "keys": "all", "blend": "normal",
            "opacity": 1.0, "enabled": True, **kw}


# ---------- state.json ----------

def test_studio_state_defaults(app):
    st = app.load_state()
    assert st["studio"] == {"enabled": False, "active": "Rainbow wave", "fps": 30, "brightness": 1.0,
                            "audio": {"device": None, "sensitivity": 1.0}, "heat": False}
    assert st["smart"]["idle"]["enabled"] is False and st["smart"]["app_rules"] == []


def test_studio_bad_fields_fall_back_one_by_one(app):
    with open(app.STATE_FILE, "w") as f:
        json.dump({"studio": {"enabled": "yes", "active": "", "fps": 240, "brightness": 0.5,
                              "audio": {"device": True, "sensitivity": 2.0}, "heat": True},
                   "smart": {"idle": {"enabled": True, "minutes": -3}, "sleep_off": False,
                             "app_rules": [{"bundle_id": "com.valve.steam", "preset": "Fire"}, {"bundle_id": 4}]}}, f)
    st = app.load_state()
    assert st["studio"] == {"enabled": False, "active": "Rainbow wave", "fps": 30, "brightness": 0.5,
                            "audio": {"device": None, "sensitivity": 2.0}, "heat": True}
    assert st["smart"]["sleep_off"] is False
    assert st["smart"]["idle"]["minutes"] == 10
    assert st["smart"]["app_rules"] == [{"bundle_id": "com.valve.steam", "preset": "Fire"}]


# ---------- reads ----------

def test_studio_state_lists_effects_and_presets(api):
    d = ok(api.studio_state())
    fx = {e["name"]: e for e in d["effects"]}
    assert fx["rainbow"]["category"] == "basic" and fx["rainbow"]["description"]
    assert fx["reactive_ripple"]["needs"] == ["keys"]
    speed = next(p for p in fx["rainbow"]["params"] if p["name"] == "speed")
    assert speed["kind"] == "float" and speed["min"] is not None
    names = {p["name"]: p for p in d["presets"]}
    assert names["Aurora"]["builtin"] is True
    assert d["active"] == "Rainbow wave" and d["working"]["name"] == "Rainbow wave"
    assert d["enabled"] is False and d["fps"] == 30
    assert [x["name"] for x in d["audio"]["devices"]] == ["MacBook Microphone", "BlackHole 2ch"]
    json.dumps(d)  # everything crosses to JavaScript


# ---------- presets ----------

def test_set_active_preset(api):
    err(api.set_active_preset("Nope"))
    ok(api.set_active_preset("Aurora"))
    assert engine(api).preset.name == "Aurora"
    assert ok(api.studio_state())["active"] == "Aurora"
    assert json.load(open(api_state_file(api)))["studio"]["active"] == "Aurora"


def api_state_file(api):
    import app as appmod
    return appmod.STATE_FILE


def test_save_preset_refuses_builtin_names_and_saves_new(api, tmp_path):
    assert "built in" in err(api.save_preset({"name": "Aurora", "layers": [layer()]}))
    err(api.save_preset({"name": "Mine", "layers": [layer(effect="nope")]}))
    ok(api.save_preset({"name": "Mine", "layers": [layer(params={"color": [1, 2, 3]})]}))
    saved = json.load(open(tmp_path / "presets.json"))
    assert [p["name"] for p in saved["presets"]] == ["Mine"]
    d = ok(api.studio_state())
    assert d["active"] == "Mine" and d["dirty"] is False
    assert engine(api).preset.name == "Mine"


def test_rename_duplicate_delete(api):
    ok(api.save_preset({"name": "Mine", "layers": [layer()]}))
    err(api.rename_preset("Aurora", "X"))
    err(api.rename_preset("Mine", "Aurora"))
    ok(api.rename_preset("Mine", "Ours"))
    assert ok(api.studio_state())["active"] == "Ours"
    new = ok(api.duplicate_preset("Aurora"))
    assert new == "Aurora copy"
    assert ok(api.studio_state())["active"] == "Aurora copy"
    err(api.delete_preset("Aurora"))
    ok(api.delete_preset("Aurora copy"))
    d = ok(api.studio_state())
    assert "Aurora copy" not in [p["name"] for p in d["presets"]]
    assert d["active"] == "Rainbow wave"


def test_import_export_round_trip(api):
    ok(api.save_preset({"name": "Mine", "layers": [layer(params={"color": [9, 9, 9]})]}))
    text = ok(api.export_preset("Mine"))["json"]
    ok(api.delete_preset("Mine"))
    assert ok(api.import_preset(text)) == "Mine"
    assert ok(api.import_preset(text)) == "Mine 2"   # a name clash gets a number
    err(api.import_preset("{not json"))
    err(api.import_preset("x" * 300_000))
    err(api.import_preset(json.dumps({"name": "Bad", "layers": [layer(effect="nope")]})))


# ---------- live edits ----------

def test_update_layers_validates_now_and_applies_debounced(api, hooks):
    pending = []
    api._get_studio()._schedule = lambda delay, fn: pending.append((delay, fn)) or _Cancel()
    eng = engine(api)
    ok(api.studio_enable(True))
    before = len(eng.log)
    err(api.update_layers([layer(effect="nope")]))
    ok(api.update_layers([layer(params={"color": [255, 0, 0]})]))
    ok(api.update_layers([layer(params={"color": [0, 255, 0]})]))
    assert len(eng.log) == before          # nothing sent to the engine yet
    assert pending and 0.1 <= pending[-1][0] <= 0.2
    pending[-1][1]()
    assert eng.preset.layers[0].params["color"] == [0, 255, 0]
    assert ok(api.studio_state())["dirty"] is True


class _Cancel:
    def cancel(self):
        pass


def test_brightness_fps_audio_validation(api, app):
    err(api.set_studio_brightness(1.5))
    ok(api.set_studio_brightness(0.4))
    assert engine(api).brightness == pytest.approx(0.4)
    err(api.set_fps(10))
    err(api.set_fps(61))
    err(api.set_fps(True))
    ok(api.set_fps(45))
    assert engine(api).fps == 45
    err(api.set_audio_device(True))
    err(api.set_audio_device(-1))
    ok(api.set_audio_device(3))
    err(api.set_audio_sensitivity(0))
    ok(api.set_audio_sensitivity(2.5))
    st = app.load_state()["studio"]
    assert st["fps"] == 45 and st["brightness"] == 0.4 and st["audio"] == {"device": 3, "sensitivity": 2.5}


# ---------- engine and listeners ----------

def test_enable_disable_starts_and_stops_engine_and_restores(api, fake, app):
    with app.update_state() as st:
        st["effect"] = {"name": "static", "rgb1": [255, 0, 0]}
    eng = engine(api)
    ok(api.studio_enable(True))
    assert eng.running and eng.preset.name == "Rainbow wave"
    ok(api.studio_enable(False))
    assert not eng.running and ("stop", True) in eng.log
    assert fake.writes(0x0F, 0x02)   # the saved static effect went back on the keyboard
    assert app.load_state()["studio"]["enabled"] is False


def test_listeners_follow_what_the_preset_needs(api, hooks):
    ok(api.studio_enable(True))
    assert not hooks["keys"] and not hooks["audio"]
    ok(api.set_active_preset("Typing glow"))
    assert hooks["keys"][-1].running
    ok(api.set_active_preset("Music"))
    assert not hooks["keys"][-1].running and hooks["audio"][-1].running
    ok(api.set_active_preset("Aurora"))
    assert not hooks["audio"][-1].running
    ok(api.set_heat(True))                     # the heatmap counts presses, so it needs keys too
    assert hooks["keys"][-1].running
    ok(api.studio_enable(False))
    assert not hooks["keys"][-1].running


def test_key_events_and_audio_reach_the_engine(api, hooks):
    ok(api.studio_enable(True))
    ok(api.set_active_preset("Typing glow"))
    hooks["keys"][-1].args[0](KeyEvent(0x1A, True, 1.0))
    assert engine(api).events[-1].usage == 0x1A
    ok(api.set_active_preset("Music"))
    from inputs.types import AudioState
    hooks["audio"][-1].args[1](AudioState(0.5, [0.1] * 16))
    assert engine(api).audio.level == 0.5


def test_permission_errors_are_reported(api, hooks):
    hooks["key_fail"] = InputPermissionError("Allow Input Monitoring in System Settings, Privacy & Security")
    ok(api.studio_enable(True))
    ok(api.set_active_preset("Typing glow"))
    d = ok(api.studio_state())
    assert "Input Monitoring" in d["errors"]["keys"]
    hooks["key_fail"] = None
    ok(api.set_active_preset("Aurora"))
    assert ok(api.studio_state())["errors"]["keys"] is None


def test_smart_actions_dim_switch_off_and_pick_presets(api, hooks):
    ok(api.studio_enable(True))
    api.gui_ready()
    smart = hooks["smart"][-1]
    assert smart.started
    smart.on_change({"brightness": 0.2, "off": False, "preset": None})
    assert engine(api).brightness == pytest.approx(0.2)
    smart.on_change({"brightness": 0.0, "off": True, "preset": None})
    assert engine(api).brightness == 0
    smart.on_change({"brightness": 1.0, "off": False, "preset": "Fire"})
    assert engine(api).preset.name == "Fire" and engine(api).brightness == 1.0
    assert ok(api.studio_state())["active"] == "Rainbow wave"   # the user's own choice is kept
    err(api.set_smart({"idle": {"minutes": 0}}))
    ok(api.set_smart({"idle": {"enabled": True, "minutes": 5, "action": "off", "dim_to": 0.2}}))
    assert smart.config["idle"]["minutes"] == 5


def test_heat_reset(api):
    eng = engine(api)
    eng.heat = {31: 4}
    ok(api.reset_heat())
    assert eng.heat == {}


# ---------- device operations and the engine ----------

def test_device_calls_run_with_the_engine_paused(api, fake):
    eng = engine(api)
    ok(api.studio_enable(True))
    depths = []
    real = REAL_KEYBOARD.set_brightness
    REAL_KEYBOARD.set_brightness = lambda kb, *a, **k: (depths.append(eng.depth), real(kb, *a, **k))[1]
    try:
        ok(api.set_brightness(40))
    finally:
        REAL_KEYBOARD.set_brightness = real
    assert depths == [1] and eng.depth == 0


def test_firmware_effect_turns_studio_off_without_restoring(api, fake):
    eng = engine(api)
    ok(api.studio_enable(True))
    ok(api.set_effect("static", {"rgb1": [0, 0, 255]}))
    assert ("stop", False) in eng.log and not eng.running
    assert ok(api.studio_state())["enabled"] is False


def test_key_tester_holds_the_engine_paused_until_it_ends(api, app, monkeypatch):
    eng = engine(api)
    ok(api.studio_enable(True))
    sessions = []

    class Session:
        def __init__(self, kb, batch, ended):
            self.ended, self.running = ended, False
            sessions.append(self)

        def start(self):
            self.running = True
            return True

        def stop(self, reason=None):
            self.running = False
            self.ended(reason, True)
            return True

    monkeypatch.setattr(app.depth_stream, "DepthSession", Session)
    ok(api.start_test())
    assert eng.depth == 1
    api.stop_test()
    assert eng.depth == 0
    sessions[0].ended("again", True)   # a second end never resumes twice
    assert eng.depth == 0


def test_restore_lighting_uses_saved_custom_colours(app, fake):
    kb = hc.Keyboard()
    st = app.load_state()
    st["custom"] = {"base": [1, 2, 3], "keys": {}}
    app.restore_lighting(kb, st)
    assert len(fake.writes(0x0F, 0x03)) == hc.FRAME_ROWS


def test_shutdown_stops_everything(api, hooks):
    ok(api.studio_enable(True))
    api.gui_ready()
    ok(api.set_active_preset("Typing glow"))
    api.shutdown()
    eng = engine(api)
    assert not eng.running and ("stop", True) in eng.log
    assert not hooks["keys"][-1].running and not hooks["smart"][-1].started
    assert api.app_state()["enabled"] is True     # quitting doesn't turn Studio off for next time


# ---------- window and menu bar lifecycle (main) with a fake pywebview ----------

class _Events:
    def __init__(self):
        self.closing = _Hook()


class _Hook:
    def __init__(self):
        self.fns = []

    def __iadd__(self, fn):
        self.fns.append(fn)
        return self

    def fire(self):
        return [f() for f in self.fns]


class _Window:
    def __init__(self, hidden):
        self.hidden, self.events, self.destroyed = hidden, _Events(), False

    def hide(self):
        self.hidden = True

    def show(self):
        self.hidden = False

    def destroy(self):
        self.destroyed = True


class _Menu:
    last = None

    def __init__(self, on_toggle, on_preset, on_open, on_quit, presets=(), enabled=True, active=None):
        self.on_toggle, self.on_preset, self.on_open, self.on_quit = on_toggle, on_preset, on_open, on_quit
        self.presets, self.enabled, self.active, self.installed = list(presets), enabled, active, False
        _Menu.last = self

    def install_soon(self):
        self.installed = True

    def set_state(self, enabled=None, presets=None, active=...):
        if enabled is not None:
            self.enabled = enabled


@pytest.fixture
def run_main(app, fake, hooks, monkeypatch):
    import types

    import menubar
    made = {}
    web = types.ModuleType("webview")

    def create_window(*a, hidden=False, **k):
        made["win"] = _Window(hidden)
        return made["win"]
    web.create_window = create_window
    web.start = lambda func=None: func and func()
    monkeypatch.setitem(sys.modules, "webview", web)
    monkeypatch.setattr(menubar, "StatusMenu", _Menu)
    monkeypatch.setattr(app, "on_main", lambda fn: fn())
    monkeypatch.setattr(app, "in_background", lambda fn: fn())
    dock = []
    monkeypatch.setattr(app, "set_dock_icon", dock.append)
    monkeypatch.setattr(app.depth_stream, "install_signal_stop", lambda: None)
    real_api = app.Api
    monkeypatch.setattr(app, "Api", lambda: made.setdefault("api", real_api(engine_cls=FakeEngine,
                                                                           inputs=hooks["inputs"])))

    def run(argv):
        app.main(argv)
        return made["win"], made["api"], dock
    return run


def test_background_launch_starts_hidden_with_the_menu(run_main):
    win, api, dock = run_main(["--background"])
    assert win.hidden and _Menu.last.installed and dock == [False]


def test_closing_hides_while_studio_runs_and_quits_otherwise(run_main):
    win, api, dock = run_main([])
    assert not win.hidden and _Menu.last.installed
    ok(api.studio_enable(True))
    assert win.events.closing.fire() == [False]      # cancelled: lighting keeps running in the menu bar
    assert win.hidden and dock[-1] is False
    _Menu.last.on_open()
    assert not win.hidden and dock[-1] is True
    ok(api.studio_enable(False))
    assert win.events.closing.fire() == [None]       # Studio off: the window closes and the app quits


def test_menu_quit_restores_and_closes(run_main):
    win, api, _ = run_main([])
    _Menu.last.on_preset("Aurora")                   # picking a preset from the menu also turns Studio on
    eng = engine(api)
    assert eng.running and eng.preset.name == "Aurora" and _Menu.last.enabled
    _Menu.last.on_quit()
    assert ("stop", True) in eng.log and win.destroyed
    assert win.events.closing.fire() == [None]


def test_real_engine_streams_pauses_for_device_calls_and_restores(app, fake, hooks):
    """The real engine thread on the fake keyboard: frames go out, an app call in between doesn't deadlock,
    and turning Studio off waits for the thread and puts the keyboard's own effect back."""
    import threading
    import time
    api = app.Api(inputs=hooks["inputs"])
    try:
        ok(api.set_active_preset("Rainbow wave"))
        ok(api.studio_enable(True))
        deadline = time.monotonic() + 3
        while len(fake.writes(0x0F, 0x03)) < 12 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(fake.writes(0x0F, 0x03)) >= 12          # at least two frames of six rows
        done = threading.Event()
        threading.Thread(target=lambda: (api.set_brightness(50), done.set()), daemon=True).start()
        assert done.wait(3), "an app call while the engine runs deadlocked"
        before = len(fake.writes(0x0F, 0x02))
        ok(api.studio_enable(False))
        assert not api.studio.engine.running
        assert len(fake.writes(0x0F, 0x02)) > before        # restore re-sent the stored effect
    finally:
        api.shutdown()
