# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The app as the control panel: its Studio calls go to the lighting service (started when missing), every
keyboard operation runs under a pause lease, and service events reach the window through the pusher."""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ipc  # noqa: E402
from test_studio import REAL_KEYBOARD, app, fake  # noqa: E402,F401 (fixtures)


class FakeService:
    """Stands in for the socket: records requests; `up` False makes connecting fail."""

    def __init__(self, up=True):
        self.up, self.calls, self.leases, self.n = up, [], set(), 0

    def connect(self):
        if not self.up:
            raise ipc.ServiceUnavailable("no service")
        return self

    def request(self, cmd, args=None):
        args = dict(args or {})
        self.calls.append((cmd, args))
        if cmd == "pause":
            tok = args.get("token")
            if tok is None:
                self.n += 1
                tok = f"t{self.n}"
                self.leases.add(tok)
            return {"ok": True, "data": {"token": tok}}
        if cmd == "resume":
            self.leases.discard(args["token"])
            return {"ok": True, "data": None}
        if cmd == "export_preset":
            return {"ok": True, "data": '{"x": 1}'}
        if cmd == "studio_state":
            return {"ok": True, "data": {"enabled": True}}
        return {"ok": True, "data": cmd}

    def cmds(self):
        return [c for c, _ in self.calls]


def make_api(app, svc, starter=None, **kw):
    link = app.ServiceLink(connect=svc.connect, starter=starter or (lambda: None), wait=0.2, **kw)
    return app.Api(service=link)


def test_studio_call_is_proxied(app):
    svc = FakeService()
    api = make_api(app, svc)
    assert api.studio_enable(True) == {"ok": True, "data": "studio_enable"}
    assert svc.calls == [("studio_enable", {"on": True})]
    assert api.update_layers([{"id": "a"}])["ok"] and svc.calls[-1] == ("update_layers", {"layers": [{"id": "a"}]})
    api.rename_preset("a", "b")
    assert svc.calls[-1] == ("rename_preset", {"old": "a", "new": "b"})


def test_missing_service_is_started_then_used(app):
    svc = FakeService(up=False)
    started = []

    def starter():
        started.append(1)
        svc.up = True
    api = make_api(app, svc, starter)
    assert api.studio_state() == {"ok": True, "data": {"enabled": True}}
    assert started == [1]


def test_service_that_cannot_start_gives_a_clear_error(app):
    svc = FakeService(up=False)

    def starter():
        raise RuntimeError("launchctl said no")
    r = make_api(app, svc, starter).studio_state()
    assert r["ok"] is False and "lighting service" in r["error"] and "launchctl said no" in r["error"]


def test_service_that_never_answers_gives_a_clear_error(app):
    r = make_api(app, FakeService(up=False)).studio_enable(True)
    assert r["ok"] is False and "lighting service" in r["error"]


def test_device_calls_hold_a_lease(app, fake):
    svc = FakeService()
    api = make_api(app, svc)
    seen = []
    real = REAL_KEYBOARD.set_brightness

    def spy(kb, *a, **k):
        seen.append(set(svc.leases))
        return real(kb, *a, **k)
    REAL_KEYBOARD.set_brightness = spy
    try:
        assert api.set_brightness(40)["ok"]
    finally:
        REAL_KEYBOARD.set_brightness = real
    assert seen and seen[0] and svc.leases == set()          # held during the call, released after


def test_device_calls_work_without_a_service(app, fake):
    api = make_api(app, FakeService(up=False))
    assert api.set_brightness(40)["ok"]


def test_firmware_effect_turns_studio_off_in_the_service_without_starting_it(app, fake):
    svc = FakeService()
    api = make_api(app, svc)
    assert api.set_effect("static", {"rgb1": [0, 0, 255]})["ok"]
    assert ("studio_enable", {"on": False, "restore": False}) in svc.calls
    started = []
    down = FakeService(up=False)
    api2 = make_api(app, down, lambda: started.append(1))
    assert api2.set_custom([0, 0, 0], {})["ok"] and started == []


def test_lease_is_renewed_while_held(app):
    svc = FakeService()
    link = app.ServiceLink(connect=svc.connect, starter=lambda: None, lease_seconds=0.5, renew_every=0.02)
    with link.lease():
        time.sleep(0.15)
    renewals = [a for c, a in svc.calls if c == "pause" and a.get("token")]
    assert len(renewals) >= 2 and svc.leases == set()


def test_abandoned_lease_is_left_to_expire(app):
    svc = FakeService()
    link = app.ServiceLink(connect=svc.connect, starter=lambda: None)
    lease = link.lease().acquire()
    lease.abandon()
    assert svc.leases == {"t1"} and "resume" not in svc.cmds()


def _session(app, monkeypatch, end_ok=True):
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
            self.ended(reason, end_ok)
            return end_ok
    monkeypatch.setattr(app.depth_stream, "DepthSession", Session)
    monkeypatch.setattr(app, "in_background", lambda fn: fn())
    return sessions


def test_key_tester_holds_a_lease_until_it_ends(app, fake, monkeypatch):
    svc = FakeService()
    api = make_api(app, svc)
    _session(app, monkeypatch)
    assert api.start_test()["ok"]
    assert len(svc.leases) == 1                       # still held after start_test returned
    api.stop_test()
    assert svc.leases == set()


@pytest.mark.parametrize("reason,kind", [("cmd", "cmd"), ("Live view paused after 5 minutes without a key press.", "")])
def test_key_tester_tells_the_window_when_cmd_ended_it(app, fake, monkeypatch, reason, kind):
    """⌘ on the Huntsman stops the session in the stream thread (normal stop path: lease released, settings
    re-sent); the window then learns it was ⌘, so it holds live view off like the idle pause."""
    svc = FakeService()
    api = make_api(app, svc)
    sessions = _session(app, monkeypatch)
    pushed = []
    api._pusher.push = lambda fn, *a: pushed.append((fn, a))
    reason = app.depth_stream.LEAVE if reason == "cmd" else reason
    assert api.start_test()["ok"]
    sessions[0].stop(reason)
    assert svc.leases == set()
    assert ("onTestEnded", (reason, True, kind)) in pushed


def test_key_tester_switch_back_failing_inside_start_abandons_the_lease(app, fake, monkeypatch):
    svc = FakeService()
    api = make_api(app, svc)
    sessions = _session(app, monkeypatch)

    def start():
        raise app.depth_stream.StillInDriverMode(app.depth_stream.UNPLUG)
    monkeypatch.setattr(app.depth_stream, "DepthSession", lambda kb, b, e: sessions.append(None) or
                        type("S", (), {"start": staticmethod(start), "running": False})())
    assert api.start_test()["ok"] is False
    # the call's own lease is released; the tester's is left to expire, so the service switches the keyboard back
    assert len(svc.leases) == 1
    assert api._test_lease is None


def test_key_tester_failed_switch_back_leaves_the_lease_to_expire(app, fake, monkeypatch):
    svc = FakeService()
    api = make_api(app, svc)
    _session(app, monkeypatch, end_ok=False)
    api.start_test()
    api.stop_test()
    # not resumed: on expiry the service switches a stuck keyboard back to typing before sending frames
    assert len(svc.leases) == 1
    assert api._test_lease is None


def test_service_events_reach_the_window_and_unknown_names_are_dropped(app):
    api = make_api(app, FakeService())
    pushed = []
    api._pusher.push = lambda fn, *a: pushed.append((fn, a))
    api._on_service_event("onStudioFrame", [{"1": [1, 2, 3]}])
    api._on_service_event("alert(1)//", ["x"])
    api._on_service_event("onStudioChanged", "not a list")
    assert pushed == [("onStudioFrame", ({"1": [1, 2, 3]},))]


def test_export_without_a_window_returns_the_text(app):
    assert make_api(app, FakeService()).export_preset("x") == {"ok": True, "data": {"json": '{"x": 1}'}}


@pytest.mark.mac_only   # launchctl, os.getuid
def test_default_starter_kickstarts_the_launch_agent(app, monkeypatch):
    ran = []

    class Done:
        returncode = 0
        stderr = ""
    monkeypatch.setattr(app.subprocess, "run", lambda cmd, **k: ran.append(cmd) or Done())
    app.start_service()
    assert ran[0][:2] == ["launchctl", "kickstart"] and "-k" not in ran[0]   # never kill a starting service
    assert ran[0][2] == f"gui/{os.getuid()}/io.github.huntsman-for-mac.lighting"


def test_main_quits_normally_when_the_window_closes(app, monkeypatch):
    import types
    made = {}

    class Win:
        def __init__(self):
            self.events = types.SimpleNamespace(closing=Hook())

    class Hook(list):
        def __iadd__(self, fn):
            self.append(fn)
            return self
    web = types.ModuleType("webview")
    web.create_window = lambda *a, **k: made.setdefault("win", Win())
    web.start = lambda func=None: func and func()
    monkeypatch.setitem(sys.modules, "webview", web)
    monkeypatch.setattr(app.depth_stream, "install_signal_stop", lambda: None)
    monkeypatch.setattr(app.depth_stream, "_SHUTDOWN", [])
    shut = []
    real_api = app.Api

    def fake_api():
        a = real_api(service=app.ServiceLink(connect=FakeService(up=False).connect, starter=lambda: None))
        a.shutdown = lambda: shut.append(1)
        a.start_events = lambda: made.setdefault("events", True)
        return a
    monkeypatch.setattr(app, "Api", fake_api)
    app.main([])
    assert made["events"] is True
    assert [f() for f in made["win"].events.closing] == [None]   # never cancelled: the app just quits
    assert shut and not hasattr(app, "install_app_hooks")


def test_the_studio_preview_poll_never_starts_the_service(app):
    """The Studio tab asks for a preview every few seconds: with the service quit (the tray, or the Windows
    installer's --quit-service before an upgrade) that poll must not start it again."""
    svc = FakeService(up=False)
    started = []
    r = make_api(app, svc, lambda: started.append(1)).studio_preview(10)
    assert r["ok"] is False and started == [] and "unavailable" not in r
    svc.up = True
    assert make_api(app, svc).studio_preview(10)["ok"] is True
