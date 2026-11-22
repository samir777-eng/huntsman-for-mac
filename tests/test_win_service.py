# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The lighting service and the app on Windows (pretended with sys.platform; fakes only): the app starts the
service itself (no launchd), start at login is turned on when the service or Studio is used, quitting the service
leaves it off until the next login or Studio use (as on the Mac), the Synapse guard is re-checked while the service
runs, signals work without SIGHUP or a wakeup pipe, and the key tester's depth stream stays refused."""
import os
import signal
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import depth_stream  # noqa: E402
import huntsman_core as hc  # noqa: E402
import models  # noqa: E402
from platforms import win_autostart, win_guard  # noqa: E402
from test_core import FakeTransport  # noqa: E402
from test_platforms import FakeMsvcrt  # noqa: E402
from test_studio import FakeEngine, app, fake, hooks  # noqa: E402,F401 (fixtures)
from test_win_guard import Clock, Procs  # noqa: E402

V3PRO = models.MODELS[0x02A6]


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt())
    procs, clock = Procs(), Clock()
    monkeypatch.setattr(win_guard, "_guard", win_guard.Guard(list_processes=procs, clock=clock))
    return procs, clock


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    import app as appmod
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(appmod, "STATE_FILE", str(tmp_path / "state.json"))
    return tmp_path


class Run:
    """The Run value, as win_autostart.ensure() sees it (current() and enable() replaced)."""

    def __init__(self, monkeypatch, value=None):
        self.value, self.writes = value, []
        monkeypatch.setattr(win_autostart, "current", lambda winreg=None: self.value)
        monkeypatch.setattr(win_autostart, "command_line", lambda *a, **k: "cmd")
        monkeypatch.setattr(win_autostart, "enable", self.enable)

    def enable(self, winreg=None, command=None):
        if self.value == command:
            return False
        self.value = command
        self.writes.append(command)
        return True


def test_the_app_starts_the_service_itself_on_windows(windows, state_dir, monkeypatch):
    import app as appmod
    run, started = Run(monkeypatch), []
    monkeypatch.setattr(win_autostart, "spawn", lambda argv, popen=None: started.append(argv))
    monkeypatch.setattr(appmod.subprocess, "run", lambda *a, **kw: pytest.fail("launchctl on Windows"))
    appmod.start_service()
    assert started == [win_autostart.service_argv()] and run.writes == ["cmd"]
    assert appmod.load_state()["autostart_added"] is True


def test_start_at_login_removed_by_the_user_stays_removed(windows, state_dir, monkeypatch):
    """Added once, then deleted (by hand, or a cleanup tool): neither the service nor the app adds it back,
    until Studio is turned on from the app."""
    import app as appmod
    import service
    run = Run(monkeypatch)
    service.ensure_autostart()
    assert run.writes == ["cmd"]
    run.value = None                                   # the user removed it
    service.ensure_autostart()
    monkeypatch.setattr(win_autostart, "spawn", lambda argv, popen=None: None)
    appmod.start_service()
    assert run.writes == ["cmd"]
    from test_models_wiring import FakeService, make_api
    api = make_api(appmod, FakeService())
    assert api.studio_enable(True)["ok"] is True
    assert run.writes == ["cmd", "cmd"]
    api.studio_enable(False)
    run.value = None
    service.ensure_autostart()
    assert run.writes == ["cmd", "cmd"]


def test_the_not_running_message_fits_the_platform(windows):
    import app as appmod
    msg = appmod.not_running_message("no pipe")
    assert "no pipe" in msg and "install.sh" not in msg and "Library/Logs" not in msg
    assert "Huntsman for Mac" in msg and "Logs" in msg


def test_the_mac_message_is_unchanged():
    import app as appmod
    assert appmod.not_running_message("x") == appmod.NOT_RUNNING.format("x")


def test_the_service_turns_start_at_login_on_only_on_windows(windows, state_dir, monkeypatch):
    import service
    run = Run(monkeypatch)
    service.ensure_autostart()
    assert run.writes == ["cmd"]
    run.value = "elsewhere"                            # a moved Huntsman.exe: followed
    service.ensure_autostart()
    assert run.writes == ["cmd", "cmd"]
    monkeypatch.setattr(sys, "platform", "darwin")
    run.value = None
    service.ensure_autostart()
    assert run.writes == ["cmd", "cmd"]


def test_a_refused_registry_write_never_stops_the_service(windows, state_dir, monkeypatch):
    import service

    def refuse(**kw):
        raise PermissionError("policy")
    Run(monkeypatch)
    monkeypatch.setattr(win_autostart, "enable", refuse)
    service.ensure_autostart()   # logged, not raised


def test_the_app_still_starts_the_service_when_the_registry_refuses(windows, state_dir, monkeypatch):
    import app as appmod
    started = []

    def refuse(**kw):
        raise PermissionError("policy")
    Run(monkeypatch)
    monkeypatch.setattr(win_autostart, "enable", refuse)
    monkeypatch.setattr(win_autostart, "spawn", lambda argv, popen=None: started.append(argv))
    appmod.start_service()
    assert started == [win_autostart.service_argv()]


def test_quitting_the_service_keeps_start_at_login(windows, monkeypatch):
    """Like the Mac's LaunchAgent (exit 0: launchd leaves it quit until the next login): the Run value stays."""
    import service
    calls = []
    monkeypatch.setattr(win_autostart, "disable", lambda **kw: calls.append("disable"))
    assert "disable" not in service.QUIT_STEPS and calls == []


def test_the_app_opens_from_the_tray_without_a_console(windows, monkeypatch):
    import service
    started = []
    monkeypatch.setattr(service.subprocess, "Popen", lambda argv, **kw: started.append((argv, kw)))
    service.open_app()
    (argv, kw), = started
    assert argv == win_autostart.app_argv()
    assert kw["creationflags"] & win_autostart.CREATE_NO_WINDOW


def test_the_service_comes_back_once_synapse_quits(app, fake, hooks, windows):
    import service
    procs, clock = windows
    hc.set_experimental(True)
    with app.update_state() as st:
        st["studio"]["enabled"] = True
    procs.names = ["RazerAppEngine.exe"]
    notices = []
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    s.on_guard(notices.append)
    s.start()
    try:
        assert not s.studio.engine.running
        assert "Razer Synapse" in s.check_guard() and "Razer Synapse" in notices[-1]
        procs.names = []
        clock.t += win_guard.CHECK_EVERY
        assert s.check_guard() is None and notices[-1] is None
        assert s.studio.engine.running        # the user's choice from state.json is back
        assert s.check_guard() is None and len(notices) == 2   # told once per change
    finally:
        s.shutdown()


def test_studio_turned_off_by_synapse_comes_back_too(app, fake, hooks, windows):
    import service
    procs, clock = windows
    hc.set_experimental(True)
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    s.start()
    try:
        s.set_studio_enabled(True)
        procs.names = ["RazerAppEngine.exe"]
        clock.t += win_guard.CHECK_EVERY
        s._engine_error(hc.SynapseRunning(win_guard.SYNAPSE_MESSAGE))   # the engine's next frame was refused
        assert not s.studio.engine.running
        procs.names = []
        clock.t += win_guard.CHECK_EVERY
        s.check_guard()
        assert s.studio.engine.running
    finally:
        s.shutdown()


def test_the_user_turning_studio_off_is_not_undone(app, fake, hooks, windows):
    import service
    procs, clock = windows
    hc.set_experimental(True)
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    s.start()
    try:
        procs.names = ["RazerAppEngine.exe"]
        s.check_guard()
        procs.names = []
        clock.t += win_guard.CHECK_EVERY
        s.check_guard()
        assert not s.studio.engine.running
    finally:
        s.shutdown()


def test_the_mac_service_has_no_guard(app, fake, hooks):
    import service
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"])
    s.start()
    try:
        assert s.check_guard() is None
    finally:
        s.shutdown()


def test_signals_on_windows_need_no_sighup_or_wakeup_pipe(windows, monkeypatch):
    installed = []
    monkeypatch.setattr(depth_stream.signal, "signal", lambda sig, fn: installed.append(sig))
    monkeypatch.setattr(depth_stream.signal, "set_wakeup_fd", lambda fd: pytest.fail("wakeup fd on Windows"))
    monkeypatch.setattr(depth_stream.os, "pipe", lambda: pytest.fail("pipe on Windows"))
    depth_stream.install_signal_stop()
    assert signal.SIGTERM in installed and all(s != getattr(signal, "SIGHUP", -1) for s in installed)


def test_the_depth_stream_is_refused_on_windows(windows, tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    hc.set_experimental(True)
    t = FakeTransport()
    s = depth_stream.DepthSession(hc.Keyboard(t, model=V3PRO), lambda b: None, lambda r: None)
    with pytest.raises(hc.FeatureUnavailable, match="Windows"):
        s.start()
    assert t.sent == []


def test_the_frozen_exe_runs_the_service_with_dash_dash_service(monkeypatch):
    import app as appmod
    import service
    ran = []
    monkeypatch.setattr(service, "main", lambda argv=None: ran.append("service") or 0)
    monkeypatch.setattr(appmod, "main", lambda argv=None: ran.append("app"))
    assert appmod.entry(["Huntsman.exe", "--service"]) == 0
    appmod.entry(["Huntsman.exe"])
    assert ran == ["service", "app"]


def test_a_windowed_exe_logs_to_the_log_file(windows, tmp_path, monkeypatch):
    import platforms
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    platforms.redirect_output()
    print("hello from the service", file=sys.stderr)
    sys.stderr.flush()
    with open(platforms.log_path(), encoding="utf-8") as f:
        assert "hello from the service" in f.read()
    sys.stderr.close()


def test_studio_switched_off_while_synapse_runs_stays_off(app, fake, hooks, windows):
    """The restore after switching off finds Synapse: nothing to put back (Synapse owns the lights), and the
    user's off is not undone when Synapse quits."""
    import service
    procs, clock = windows
    hc.set_experimental(True)
    s = service.LightingService(engine_cls=FakeEngine, inputs=hooks["inputs"], clock=clock)
    s.start()
    try:
        s.set_studio_enabled(True)
        procs.names = ["RazerAppEngine.exe"]
        clock.t += win_guard.CHECK_EVERY
        s.check_guard()
        s.set_studio_enabled(False)
        s._restore_lighting()            # what the engine's restore callback does; must not raise
        assert s._guard_wants_on is False
        procs.names = []
        clock.t += win_guard.CHECK_EVERY
        s.check_guard()
        assert not s.studio.engine.running
    finally:
        s.shutdown()
