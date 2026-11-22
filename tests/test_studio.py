# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Studio integration end to end: app.Api (the control panel) -> ServiceLink -> service.LightingService
(in-process, no socket) -> studio.py, with a fake engine, fake listeners, a fake clock and a fake keyboard.
State files go to tmp_path; no USB device, IOKit, microphone, window or launchd is touched."""
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
        self.previews = []

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
        if restore:
            self.restore_firmware()

    def restore_firmware(self):
        self.log.append(("restore",))
        if self.restore:
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

    def preview(self, now=None, fresh=False):
        self.previews.append(fresh)
        return self.preset is not None


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
                   "schedule": None, "spawn": lambda fn: fn()}
    return h


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Local:
    """The service's request handler called directly, as the socket would."""

    def __init__(self, svc):
        self.svc = svc

    def request(self, cmd, args=None):
        return self.svc.handle(cmd, dict(args or {}))


def link_to(app, svc):
    return app.ServiceLink(connect=lambda: Local(svc), starter=lambda: None)


@pytest.fixture
def api(app, fake, hooks):
    import service
    svc = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=Clock())
    svc.start()
    a = app.Api(service=link_to(app, svc))
    a.svc = svc
    yield a
    a.shutdown()
    svc.shutdown()


def ok(r):
    assert r["ok"], r.get("error")
    return r["data"]


def err(r):
    assert not r["ok"]
    return r["error"]


def engine(api):
    return api.svc.studio.engine


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
    api.svc.studio._schedule = lambda delay, fn: pending.append((delay, fn)) or _Cancel()
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
    assert not eng.running and ("restore",) in eng.log
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
    api.svc.gui_ready()
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
    monkeypatch.setattr(app, "in_background", lambda fn: fn())
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
    api.svc.gui_ready()
    ok(api.set_active_preset("Typing glow"))
    api.shutdown()                                # quitting the app leaves the service's lighting running
    eng = engine(api)
    assert eng.running
    api.svc.shutdown()                            # quitting the service stops and restores
    assert not eng.running and ("restore",) in eng.log
    assert not hooks["keys"][-1].running and not hooks["smart"][-1].started
    assert api.svc.studio.summary()["enabled"] is True     # quitting doesn't turn Studio off for next time


# ---------- menu bar (a fake StatusMenu, used by test_service.py) ----------

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


def test_real_engine_streams_pauses_for_device_calls_and_restores(app, fake, hooks):
    """The real engine thread on the fake keyboard: frames go out, an app call in between doesn't deadlock,
    and turning Studio off waits for the thread and puts the keyboard's own effect back."""
    import threading
    import time

    import service
    svc = service.LightingService(inputs=hooks["inputs"])
    svc.start()
    api = app.Api(service=link_to(app, svc))
    api.svc = svc
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
        assert not svc.studio.engine.running
        assert len(fake.writes(0x0F, 0x02)) > before        # restore re-sent the stored effect
    finally:
        api.shutdown()
        svc.shutdown()


# ---------- review fixes: key tester holds, lock order, quitting, restore in RAM ----------

def _session(app, monkeypatch, start=None, end_ok=True):
    """A fake DepthSession; start() returns or raises `start` (default True); stop() reports end_ok."""
    sessions = []

    class Session:
        def __init__(self, kb, batch, ended):
            self.ended, self.running = ended, False
            sessions.append(self)

        def start(self):
            if isinstance(start, Exception):
                raise start
            self.running = start is not False
            return True if start is None else start

        def stop(self, reason=None):
            self.running = False
            self.ended(reason, end_ok)
            return end_ok

    monkeypatch.setattr(app.depth_stream, "DepthSession", Session)
    monkeypatch.setattr(app, "in_background", lambda fn: fn())
    return sessions


def test_key_tester_resumes_the_engine_when_start_fails(api, app, monkeypatch):
    eng = engine(api)
    ok(api.studio_enable(True))
    _session(app, monkeypatch, start=hc.DeviceError("Allow Input Monitoring"))
    err(api.start_test())
    assert eng.depth == 0


def test_key_tester_resumes_the_engine_when_start_is_cancelled(api, app, monkeypatch):
    eng = engine(api)
    ok(api.studio_enable(True))
    _session(app, monkeypatch, start=False)
    assert ok(api.start_test()) is False
    assert eng.depth == 0


def test_key_tester_failed_switch_back_keeps_the_engine_paused_until_reconnect(api, app, monkeypatch):
    eng = engine(api)
    ok(api.studio_enable(True))
    _session(app, monkeypatch, end_ok=False)
    ok(api.start_test())
    api.stop_test()
    assert eng.depth == 1          # the keyboard may still be in driver mode: no frames
    api.svc._clock.t += 60         # the abandoned lease expires; the service switches the keyboard back first
    api.svc.expire_leases()
    assert eng.depth == 0


def test_key_tester_follow_up_runs_paused_and_keeps_studio_frames(api, app, monkeypatch):
    with app.update_state() as st:
        st["custom"] = {"base": [1, 2, 3], "keys": {}}
    eng = engine(api)
    ok(api.studio_enable(True))
    calls = []
    monkeypatch.setattr(app, "apply_saved", lambda kb, state=None: calls.append(
        (eng.depth, (state or app.load_state()).get("custom"))))
    _session(app, monkeypatch)
    ok(api.start_test())
    del calls[:]                   # the connect-time re-send, not the test's follow-up
    api.stop_test()
    assert calls and calls[0][0] >= 1    # paused; the engine re-sends its frame when the lease ends
    assert eng.depth == 0


def test_studio_off_restores_after_releasing_the_studio_lock(api):
    eng = engine(api)
    s = api.svc.studio
    owned = []
    eng.restore = lambda: owned.append(s._lock._is_owned())
    ok(api.studio_enable(True))
    ok(api.studio_enable(False))
    assert owned == [False]


def test_shutdown_restores_after_releasing_the_studio_lock(api):
    eng = engine(api)
    s = api.svc.studio
    owned = []
    eng.restore = lambda: owned.append(s._lock._is_owned())
    ok(api.studio_enable(True))
    api.svc.shutdown()
    assert owned == [False]


def test_smart_change_never_waits_for_the_studio_lock(api, app):
    import threading
    import time

    import studio as studio_mod
    ok(api.studio_enable(True))
    s = api.svc.studio
    s._spawn = studio_mod._in_thread
    done = threading.Event()
    with s._lock:   # e.g. the menu turning Studio off, waiting on the device
        t = threading.Thread(target=lambda: (s._on_smart({"brightness": 0.3, "off": False, "preset": None}),
                                             done.set()), daemon=True)
        t.start()
        assert done.wait(1), "a smart lighting notification blocked the main thread on Studio's lock"
    deadline = time.monotonic() + 2
    while engine(api).brightness != pytest.approx(0.3) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert engine(api).brightness == pytest.approx(0.3)


def test_progress_never_waits_on_the_window_while_holding_the_device_lock(api, fake):
    import time
    owned = []

    class Win:
        def evaluate_js(self, js):
            if "onProgress" in js:
                owned.append(api._lock._is_owned())
    api._window = Win()
    ok(api.read_depths())
    deadline = time.monotonic() + 2
    while not owned and time.monotonic() < deadline:
        time.sleep(0.01)
    assert owned and not any(owned)


def test_restore_lighting_effect_goes_to_ram_not_flash(app, fake):
    kb = hc.Keyboard()
    st = app.load_state()
    st["effect"] = {"name": "static", "rgb1": [255, 0, 0]}
    app.restore_lighting(kb, st)
    assert [r[8] for r in fake.writes(0x0F, 0x02)] == [0]


def test_restore_lighting_stored_effect_is_resent_to_ram(app, fake):
    kb = hc.Keyboard()
    app.restore_lighting(kb, app.load_state())
    assert [r[8] for r in fake.writes(0x0F, 0x02)] == [0]


# ---------- preview while Studio is off ----------

@pytest.fixture
def preview_api(app, fake, hooks):
    """Like api, with a fake clock and sleep for the preview loop (spawn is synchronous, so it runs to its end)."""
    import service
    clock, naps = Clock(), []

    def sleep(s):
        naps.append(s)
        clock.t += s
    hooks["inputs"].update(clock=clock, sleep=sleep)
    svc = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=Clock())
    svc.start()
    a = app.Api(service=link_to(app, svc))
    a.svc, a.naps = svc, naps
    yield a
    a.shutdown()
    svc.shutdown()


def test_preview_while_off_composes_frames_for_the_window_only(preview_api):
    eng = preview_api.svc.studio.engine
    assert ok(preview_api.studio_preview(1.0)) is None
    assert eng.preset is not None                          # the working preset, handed over to compose
    assert 14 <= len(eng.previews) <= 16                   # one second at the preview rate
    assert eng.previews[0] is True and not any(eng.previews[1:])   # the first frame is sent even if unchanged
    assert not eng.running and ("start",) not in eng.log   # nothing streams to the keyboard


def test_no_preview_loop_while_studio_is_on_or_for_zero_seconds(preview_api):
    eng = preview_api.svc.studio.engine
    ok(preview_api.studio_preview(0))
    assert eng.previews == []
    ok(preview_api.studio_enable(True))
    ok(preview_api.studio_preview(1.0))
    assert eng.previews == []                              # the engine sends previews of what it streams


def test_preview_seconds_are_checked(preview_api):
    assert not preview_api.studio_preview(-1)["ok"]
    assert not preview_api.studio_preview("soon")["ok"]
    ok(preview_api.studio_preview(3600))                   # capped, so a lost window can't keep it running
    assert len(preview_api.svc.studio.engine.previews) <= 31 * 15


def test_preview_flag_resets_if_the_loop_raises(preview_api):
    st, eng = preview_api.svc.studio, preview_api.svc.studio.engine
    real = eng.preview

    def boom(**_):
        raise RuntimeError("compose failed")
    eng.preview = boom
    with pytest.raises(RuntimeError):
        st.preview(1.0)
    assert st._previewing is False
    eng.preview = real
    st.preview(1.0)                                         # a later request starts a loop again
    assert len(eng.previews) >= 14


def test_preview_flag_resets_if_the_loop_cannot_start(preview_api):
    st, eng = preview_api.svc.studio, preview_api.svc.studio.engine

    def no_thread(fn):
        raise RuntimeError("can't start a thread")
    spawn, st._spawn = st._spawn, no_thread
    with pytest.raises(RuntimeError):
        st.preview(1.0)
    assert st._previewing is False
    st._spawn = spawn
    st.preview(1.0)
    assert len(eng.previews) >= 14


# ---------- live key tester review: stale ends, Input Monitoring refused ----------

def test_a_stale_session_end_is_not_pushed(api, app, monkeypatch):
    """An old session's end (pushed after its re-send) must not tell the window that a newer session stopped."""
    sessions = _session(app, monkeypatch)
    pushed = []
    monkeypatch.setattr(api._pusher, "push", lambda name, *a: pushed.append((name, a)))
    ok(api.start_test())
    api.stop_test()                                   # session A ends (the window stopped it: nothing to push)
    ok(api.start_test())                              # session B starts
    sessions[0].ended("Testing stopped after 5 minutes without a key press.", True)   # A's late end
    assert [p for p in pushed if p[0] == "onTestEnded"] == []
    sessions[1].ended("Testing stopped after 5 minutes without a key press.", True)   # B's own end is pushed
    assert [p[0] for p in pushed].count("onTestEnded") == 1


def test_input_monitoring_refused_keeps_the_keyboard(api, app, monkeypatch):
    eng = engine(api)
    ok(api.studio_enable(True))
    ok(api.startup())
    _session(app, monkeypatch, start=app.depth_stream.PermissionNeeded("Allow Input Monitoring for this app."))
    r = api.start_test()
    assert r == {"ok": False, "error": "Allow Input Monitoring for this app.", "reason": "permission"}
    assert api._kb is not None and eng.depth == 0     # not a lost connection: no reconnect, no re-send
