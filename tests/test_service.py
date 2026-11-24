# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The lighting service (service.py) with a fake engine, fake listeners, a fake clock and a fake keyboard:
pause leases, expiry, command validation, events, start-up re-send, quitting and the menu bar handlers."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import huntsman_core as hc  # noqa: E402
from test_studio import FakeEngine, _Menu, app, fake, hooks  # noqa: E402,F401 (fixtures)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def svc(app, fake, hooks, clock):
    import service
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    s.start()
    yield s
    s.shutdown()


def ok(r):
    assert r["ok"], r.get("error")
    return r.get("data")


def err(r):
    assert not r["ok"]
    return r["error"]


# ---------- leases ----------

def test_pause_lease_pauses_the_engine_and_resume_releases_it(svc):
    eng = svc.studio.engine
    tok = ok(svc.handle("pause", {"lease_seconds": 5}))["token"]
    assert eng.depth == 1
    ok(svc.handle("resume", {"token": tok}))
    assert eng.depth == 0
    assert "lease" in err(svc.handle("resume", {"token": tok}))   # a second resume is refused, never resumes twice
    assert eng.depth == 0


def test_two_leases_nest(svc):
    eng = svc.studio.engine
    a = ok(svc.handle("pause", {"lease_seconds": 5}))["token"]
    b = ok(svc.handle("pause", {"lease_seconds": 5}))["token"]
    ok(svc.handle("resume", {"token": a}))
    assert eng.depth == 1
    ok(svc.handle("resume", {"token": b}))
    assert eng.depth == 0


def test_expired_lease_resumes_and_switches_a_stuck_keyboard_back(svc, clock, fake):
    eng = svc.studio.engine
    ok(svc.handle("pause", {"lease_seconds": 5}))
    fake.mode = 3                       # the app crashed during a key test: still in driver mode
    clock.t += 4.9
    svc.expire_leases()
    assert eng.depth == 1
    clock.t += 0.2
    svc.expire_leases()
    assert eng.depth == 0 and fake.mode == 0


def test_renewing_keeps_the_lease(svc, clock):
    eng = svc.studio.engine
    tok = ok(svc.handle("pause", {"lease_seconds": 5}))["token"]
    clock.t += 4
    assert ok(svc.handle("pause", {"lease_seconds": 5, "token": tok}))["token"] == tok
    clock.t += 4
    svc.expire_leases()
    assert eng.depth == 1                # renewed 4 s ago, still held
    assert "lease" in err(svc.handle("pause", {"lease_seconds": 5, "token": "nope"}))


@pytest.mark.parametrize("args", [{"lease_seconds": 0}, {"lease_seconds": 31}, {"lease_seconds": "5"},
                                  {"lease_seconds": True}, {}, {"lease_seconds": 5, "token": 3}])
def test_bad_lease_requests_are_refused(svc, args):
    err(svc.handle("pause", args))
    assert svc.studio.engine.depth == 0


def test_lease_count_is_capped(svc):
    import service
    for _ in range(service.MAX_LEASES):
        ok(svc.handle("pause", {"lease_seconds": 5}))
    err(svc.handle("pause", {"lease_seconds": 5}))


def test_restore_waits_for_the_lease(svc):
    eng = svc.studio.engine
    ok(svc.handle("studio_enable", {"on": True}))
    tok = ok(svc.handle("pause", {"lease_seconds": 5}))["token"]
    ok(svc.handle("studio_enable", {"on": False}))
    restores = [e for e in eng.log if e == ("restore",)]
    assert eng.restore is not None
    n_before = len(svc.restored)
    ok(svc.handle("resume", {"token": tok}))
    assert len(restores) == 1 and len(svc.restored) == n_before + 1   # deferred, then done once


def test_studio_off_without_restore(svc):
    ok(svc.handle("studio_enable", {"on": True}))
    ok(svc.handle("studio_enable", {"on": False, "restore": False}))
    assert ("stop", False) in svc.studio.engine.log and svc.restored == []


# ---------- commands ----------

def test_unknown_command_and_bad_arguments(svc):
    assert "unknown" in err(svc.handle("format_disk", {}))
    err(svc.handle("studio_enable", {"on": "yes"}))
    err(svc.handle("studio_enable", {}))
    err(svc.handle("set_fps", {"fps": 30, "extra": 1}))
    err(svc.handle("set_fps", {"fps": 7}))                    # range checked by studio.py


def test_studio_commands_mirror_the_old_api(svc):
    assert ok(svc.handle("studio_state", {}))["enabled"] is False
    ok(svc.handle("set_active_preset", {"name": "Aurora"}))
    ok(svc.handle("studio_enable", {"on": True}))
    assert svc.studio.engine.running and svc.studio.engine.preset.name == "Aurora"
    name = ok(svc.handle("duplicate_preset", {"name": "Aurora", "new": None}))
    ok(svc.handle("rename_preset", {"old": name, "new": "Mine"}))
    text = ok(svc.handle("export_preset", {"name": "Mine"}))
    assert '"Mine"' in text
    ok(svc.handle("delete_preset", {"name": "Mine"}))
    ok(svc.handle("set_studio_brightness", {"level": 0.5}))
    ok(svc.handle("set_fps", {"fps": 45}))
    ok(svc.handle("set_heat", {"on": True}))
    ok(svc.handle("reset_heat", {}))
    assert ok(svc.handle("summary", {}))["enabled"] is True


def test_settings_survive_a_service_restart(svc, app, hooks, clock):
    import service
    ok(svc.handle("set_active_preset", {"name": "Aurora"}))
    ok(svc.handle("studio_enable", {"on": True}))
    svc.shutdown()
    again = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    again.start()
    try:
        assert again.studio.engine.running and again.studio.settings["active"] == "Aurora"
    finally:
        again.shutdown()


# ---------- start-up and quit ----------

def test_start_resends_what_the_keyboard_keeps_only_in_ram(app, fake, hooks, clock):
    import service
    with app.update_state() as st:
        st["custom"] = {"base": [1, 2, 3], "keys": {}}
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    s.start()
    try:
        assert len(fake.writes(0x0F, 0x03)) == hc.FRAME_ROWS
    finally:
        s.shutdown()


def test_start_survives_a_missing_keyboard(app, hooks, clock, monkeypatch):
    import service

    def missing(transport=None):
        raise hc.DeviceError("keyboard not found")
    monkeypatch.setattr(hc, "Keyboard", missing)
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    s.start()
    s.shutdown()


def test_quit_stops_studio_and_restores(svc):
    ok(svc.handle("studio_enable", {"on": True}))
    tok = ok(svc.handle("pause", {"lease_seconds": 5}))["token"]
    assert tok
    svc.shutdown()
    eng = svc.studio.engine
    assert not eng.running and ("restore",) in eng.log and svc.restored   # quitting restores even under a lease
    assert svc.studio.settings["enabled"] is True                         # back on at the next start


# ---------- events ----------

def test_events_reach_subscribers_and_frames_only_those_that_asked(svc):
    plain, framed = [], []
    off = svc.subscribe(lambda n, a: plain.append(n), frames=False)
    svc.subscribe(lambda n, a: framed.append(n), frames=True)
    ok(svc.handle("studio_enable", {"on": True}))
    for cb in svc.studio.engine.frames:
        cb({1: (1, 2, 3)})
    assert "onStudioChanged" in plain and "onStudioFrame" not in plain
    assert "onStudioChanged" in framed and "onStudioFrame" in framed
    off()
    ok(svc.handle("studio_enable", {"on": False}))
    assert plain.count("onStudioChanged") == 1


# ---------- menu bar and single instance ----------

def test_menu_handlers(svc):
    import service
    opened, quit_ = [], []
    menu = service.make_menu(svc, _Menu, on_open=lambda: opened.append(1), on_quit=lambda: quit_.append(1),
                             run=lambda fn: fn())
    assert menu is _Menu.last and "Aurora" in menu.presets
    menu.on_preset("Aurora")                         # picking a preset also turns lighting on
    assert svc.studio.engine.running and menu.enabled
    menu.on_toggle(False)
    assert not svc.studio.engine.running and not menu.enabled
    menu.on_open()
    menu.on_quit()
    assert opened == [1] and quit_ == [1]


def test_only_one_service_runs(tmp_path):
    import service
    first = service.acquire_instance_lock(str(tmp_path / "service.lock"))
    assert first is not None
    assert service.acquire_instance_lock(str(tmp_path / "service.lock")) is None
    os.close(first)
    assert service.acquire_instance_lock(str(tmp_path / "service.lock")) is not None


# ---------- requests that arrive while the service is still starting ----------

def test_a_request_during_start_waits_for_studio_instead_of_failing(app, hooks, clock):
    # The socket is up before start() has built Studio (seen on the frozen 0.5.0 build: a "summary" from the window
    # failed once with "'NoneType' object has no attribute 'summary'"). It now waits for start() to finish.
    import threading
    import service
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    got = {}
    t = threading.Thread(target=lambda: got.update(r=s.handle("summary", {})))
    t.start()
    t.join(0.2)
    assert t.is_alive()                     # held, not answered with an error
    s.start()
    t.join(5)
    try:
        assert not t.is_alive() and got["r"]["ok"], got
    finally:
        s.shutdown()


def test_ping_answers_while_starting(app, hooks, clock):
    import service
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    assert s.handle("ping", {}) == {"ok": True, "data": True}


def test_a_request_gets_a_plain_error_if_start_never_finishes(app, hooks, clock, monkeypatch):
    import service
    monkeypatch.setattr(service, "START_WAIT", 0.1)
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    r = s.handle("summary", {})
    assert not r["ok"] and r["error"] == "The lighting service is still starting. Try again in a moment."


def test_the_service_answers_before_the_app_gives_up():
    # A held request must be answered (or refused) before ipc's client times out and sends it again, or it runs twice.
    import ipc
    import service
    assert service.START_WAIT < ipc.TIMEOUT


def test_a_failed_start_gives_a_plain_error_not_a_traceback(app, hooks, clock, monkeypatch):
    import service
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    monkeypatch.setattr(s, "_start", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        s.start()
    assert s.handle("summary", {}) == {"ok": False, "error": service.STARTING}


def test_shutdown_before_start_releases_waiting_requests(app, hooks, clock):
    import service
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    s.shutdown()
    assert s._started.is_set()
