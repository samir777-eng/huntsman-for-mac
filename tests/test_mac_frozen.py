# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The Mac's self-contained build (packaging/mac, PyInstaller, installed by the .pkg into /Applications): how the
code behaves when frozen, and that a source install (install.sh, not frozen) behaves as before.

Everything is simulated: sys.frozen / sys.executable / sys._MEIPASS are patched, HOME is a temporary folder, and
launchctl, osascript and pkgutil are fakes that only record their arguments. Nothing here starts a process, opens
the keyboard or touches the real LaunchAgent or /Applications."""
import os
import plistlib
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import huntsman_core as hc  # noqa: E402
import platforms  # noqa: E402
from platforms import bundle  # noqa: E402
from test_studio import app  # noqa: E402,F401 (fixture: settings in a temporary folder)

LABEL = "io.github.huntsman-for-mac.lighting"
MAIN_EXE = "Contents/MacOS/HuntsmanForMac"
PKG_APP = "/Applications/Huntsman for Mac.app"   # only ever passed to fakes here
LIGHT_EXE = "Contents/Library/LoginItems/Huntsman Lighting.app/Contents/MacOS/HuntsmanLighting"


class Done:
    def __init__(self, returncode=0, stderr="", stdout=""):
        self.returncode, self.stderr, self.stdout = returncode, stderr, stdout


class FakeRun:
    """Stands in for subprocess.run: records argv, answers from a table of (argv prefix -> Done)."""

    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        for prefix, done in self.answers.items():
            if tuple(argv[:len(prefix)]) == prefix:
                return done
        return Done()


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """A frozen main app at <tmp>/Applications/Huntsman for Mac.app (the .pkg's layout)."""
    app_dir = tmp_path / "Applications" / "Huntsman for Mac.app"
    (app_dir / "Contents" / "MacOS").mkdir(parents=True)
    (app_dir / "Contents" / "Frameworks").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_dir / MAIN_EXE))
    monkeypatch.setattr(sys, "_MEIPASS", str(app_dir / "Contents" / "Frameworks"), raising=False)
    return app_dir


@pytest.fixture
def not_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)


# ---------- libusb ----------

@pytest.mark.mac_only
def test_frozen_loads_the_bundled_libusb_first(frozen, monkeypatch):
    bundled = os.path.join(sys._MEIPASS, "libusb-1.0.dylib")
    open(bundled, "w").close()
    monkeypatch.setattr(hc.os.path, "exists", lambda p, real=os.path.exists: real(p) or p.startswith("/opt/homebrew"))
    assert hc.libusb_path() == bundled


def test_not_frozen_uses_homebrew_as_before(not_frozen, monkeypatch):
    seen = []
    monkeypatch.setattr(hc.os.path, "exists", lambda p: seen.append(p) or p == "/usr/local/lib/libusb-1.0.dylib")
    assert hc.libusb_path() == "/usr/local/lib/libusb-1.0.dylib"
    assert seen == ["/opt/homebrew/lib/libusb-1.0.dylib", "/usr/local/lib/libusb-1.0.dylib"]


def test_frozen_without_a_bundled_libusb_falls_back_to_homebrew(frozen, monkeypatch):
    monkeypatch.setattr(hc.os.path, "exists", lambda p: p == "/opt/homebrew/lib/libusb-1.0.dylib")
    assert hc.libusb_path() == "/opt/homebrew/lib/libusb-1.0.dylib"


def test_no_libusb_anywhere_is_none(not_frozen, monkeypatch):
    monkeypatch.setattr(hc.os.path, "exists", lambda p: False)
    assert hc.libusb_path() is None


# ---------- the bundle manifest and the self-test ----------

def test_mac_only_modules_are_listed_apart_from_the_windows_build():
    need = {"webview.platforms.cocoa", "objc", "AppKit", "Foundation", "WebKit", "PyObjCTools.AppHelper",
            "usb.core", "usb.util", "usb.backend.libusb1"}
    assert need <= set(bundle.MAC_ONLY)
    # packaging/windows/huntsman.spec reads HIDDEN_IMPORTS: the Mac's modules stay out of it
    assert not set(bundle.MAC_ONLY) & set(bundle.HIDDEN_IMPORTS)
    assert not set(bundle.MAC_ONLY) & bundle.WINDOWS_ONLY


def test_mac_modules_lists_the_shared_and_mac_modules_without_the_windows_ones():
    mods = bundle.mac_modules()
    assert set(bundle.MAC_ONLY) <= set(mods)
    assert not set(mods) & bundle.WINDOWS_ONLY
    assert "app" in mods and "service" in mods and "numpy" in mods
    assert len(mods) == len(set(mods))


@pytest.fixture
def no_device(monkeypatch):
    import app as appmod

    def boom(*a, **kw):
        pytest.fail("the self-test opened the keyboard or a window")
    monkeypatch.setattr(hc, "open_transport", boom)
    monkeypatch.setattr(hc, "UsbTransport", boom)
    monkeypatch.setattr(hc, "Keyboard", boom)
    monkeypatch.setattr(appmod, "main", boom)
    return appmod


@pytest.mark.mac_only
def test_self_test_imports_the_mac_modules_and_checks_the_native_libraries(no_device, monkeypatch, capsys):
    appmod = no_device
    monkeypatch.setattr(hc, "libusb_path", lambda: "/fake/libusb-1.0.dylib")
    opened = []

    class Lib:
        def __init__(self, path):
            opened.append(path)

        def __getattr__(self, name):   # a symbol lookup, never a call
            return lambda *a: pytest.fail(f"the self-test called {name}")
    monkeypatch.setattr(appmod, "_dlopen", Lib)
    assert appmod.self_test() == 0
    out = capsys.readouterr().out
    assert "ok   webview.platforms.cocoa" in out and "ok   usb.backend.libusb1" in out
    assert "ok   libusb /fake/libusb-1.0.dylib" in out
    assert "ok   IOKit" in out and "ok   CoreFoundation" in out
    assert "/fake/libusb-1.0.dylib" in opened


@pytest.mark.mac_only
def test_self_test_fails_when_frozen_without_libusb(no_device, frozen, monkeypatch, capsys):
    monkeypatch.setattr(hc, "libusb_path", lambda: None)
    assert no_device.self_test() == 1
    out = capsys.readouterr().out
    assert "FAIL libusb" in out and "self-test FAILED" in out


@pytest.mark.mac_only
def test_self_test_from_source_without_libusb_only_skips_it(no_device, not_frozen, monkeypatch, capsys):
    monkeypatch.setattr(hc, "libusb_path", lambda: None)
    assert no_device.self_test() == 0
    assert "skip libusb" in capsys.readouterr().out


@pytest.mark.mac_only
def test_self_test_fails_on_a_missing_native_symbol(no_device, monkeypatch, capsys):
    appmod = no_device
    monkeypatch.setattr(hc, "libusb_path", lambda: "/fake/libusb-1.0.dylib")

    class Lib:
        def __init__(self, path):
            self.path = path

        def __getattr__(self, name):
            if "libusb" in self.path:
                raise AttributeError(f"dlsym: {name} not found")
            return lambda *a: None
    monkeypatch.setattr(appmod, "_dlopen", Lib)
    assert appmod.self_test() == 1
    assert "FAIL libusb" in capsys.readouterr().out


# ---------- the service opens the window ----------

@pytest.mark.mac_only
def test_frozen_service_opens_the_app_by_bundle_id(frozen, monkeypatch, tmp_path):
    import service
    # wherever the frozen modules sit, the app is found by its bundle id, never by a path
    monkeypatch.setattr(service, "HERE", str(tmp_path / "Other.app" / "a" / "b" / "c"))
    started = []
    monkeypatch.setattr(service.subprocess, "Popen", lambda argv, **kw: started.append(argv))
    service.open_app()
    assert started == [["/usr/bin/open", "-b", "io.github.huntsman-for-mac"]]


@pytest.mark.mac_only
def test_source_install_service_opens_its_outer_bundle_as_before(not_frozen, monkeypatch, tmp_path):
    import service
    outer = tmp_path / "Huntsman for Mac.app"
    monkeypatch.setattr(service, "HERE", str(outer / "Contents" / "Resources" / "code"))
    started = []
    monkeypatch.setattr(service.subprocess, "Popen", lambda argv, **kw: started.append(argv))
    service.open_app()
    assert started == [["/usr/bin/open", str(outer)]]


# ---------- the LaunchAgent, written by the frozen app ----------

def _agent(home):
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


@pytest.mark.mac_only
def test_installed_bundle_is_the_frozen_app(frozen):
    import app as appmod
    assert appmod.installed_bundle() == str(frozen)


@pytest.mark.mac_only
def test_installed_bundle_from_the_nested_service_is_still_the_outer_app(frozen, monkeypatch):
    import app as appmod
    monkeypatch.setattr(sys, "executable", str(frozen / LIGHT_EXE))
    assert appmod.installed_bundle() == str(frozen)


@pytest.mark.mac_only
def test_installed_bundle_is_the_part_named_huntsman_for_mac_app(monkeypatch):
    """Another ".app" higher up (a folder named like a bundle) isn't the app."""
    import app as appmod
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Users/x/Tools.app/Applications/Huntsman for Mac.app/" + MAIN_EXE)
    assert appmod.installed_bundle() == "/Users/x/Tools.app/Applications/Huntsman for Mac.app"
    monkeypatch.setattr(sys, "executable", "/Users/x/Other.app/Contents/MacOS/HuntsmanForMac")
    assert appmod.installed_bundle() is None


def test_installed_bundle_is_none_from_source(not_frozen):
    import app as appmod
    assert appmod.installed_bundle() is None


@pytest.mark.mac_only
def test_frozen_start_writes_and_loads_a_missing_agent(app, frozen, home, monkeypatch):
    run = FakeRun({("launchctl", "kickstart"): Done(0)})
    monkeypatch.setattr(app.subprocess, "run", run)
    app.start_service()
    with open(_agent(home), "rb") as f:
        p = plistlib.load(f)
    assert p["Label"] == LABEL
    assert p["ProgramArguments"] == [str(frozen / LIGHT_EXE)]
    assert p["RunAtLoad"] is True and p["KeepAlive"] == {"SuccessfulExit": False}
    assert p["LimitLoadToSessionType"] == "Aqua" and p["ProcessType"] == "Interactive"
    assert p["AssociatedBundleIdentifiers"] == ["io.github.huntsman-for-mac"]
    log = os.path.join(str(home), "Library", "Logs", "Huntsman for Mac.log")
    assert p["StandardOutPath"] == log and p["StandardErrorPath"] == log
    uid = os.getuid()
    assert ["launchctl", "bootstrap", f"gui/{uid}", str(_agent(home))] in run.calls
    assert run.calls[-1] == ["launchctl", "kickstart", f"gui/{uid}/{LABEL}"]
    assert not any(c[:2] == ["launchctl", "bootout"] for c in run.calls)   # nothing was loaded before


@pytest.mark.mac_only
def test_frozen_start_replaces_a_stale_agent(app, frozen, home, monkeypatch):
    _agent(home).parent.mkdir(parents=True)
    old = {"Label": LABEL, "ProgramArguments": [str(home / "Applications/Huntsman for Mac.app" / LIGHT_EXE)]}
    with open(_agent(home), "wb") as f:
        plistlib.dump(old, f)
    run = FakeRun()
    monkeypatch.setattr(app.subprocess, "run", run)
    app.start_service()
    with open(_agent(home), "rb") as f:
        assert plistlib.load(f)["ProgramArguments"] == [str(frozen / LIGHT_EXE)]
    uid = os.getuid()
    boot_out = run.calls.index(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])
    boot_in = run.calls.index(["launchctl", "bootstrap", f"gui/{uid}", str(_agent(home))])
    assert boot_out < boot_in


@pytest.mark.mac_only
def test_frozen_start_leaves_a_current_agent_alone(app, frozen, home, monkeypatch):
    _agent(home).parent.mkdir(parents=True)
    mine = {"Label": LABEL, "ProgramArguments": [str(frozen / LIGHT_EXE)], "Disabled": False, "Custom": "kept"}
    with open(_agent(home), "wb") as f:
        plistlib.dump(mine, f)
    before = _agent(home).read_bytes()
    run = FakeRun({("launchctl", "kickstart"): Done(0)})
    monkeypatch.setattr(app.subprocess, "run", run)
    app.start_service()
    assert _agent(home).read_bytes() == before
    assert run.calls == [["launchctl", "kickstart", f"gui/{os.getuid()}/{LABEL}"]]


@pytest.mark.mac_only
def test_frozen_start_replaces_an_unreadable_agent(app, frozen, home, monkeypatch):
    _agent(home).parent.mkdir(parents=True)
    _agent(home).write_text("not a plist")
    monkeypatch.setattr(app.subprocess, "run", FakeRun())
    app.start_service()
    with open(_agent(home), "rb") as f:
        assert plistlib.load(f)["ProgramArguments"] == [str(frozen / LIGHT_EXE)]


@pytest.mark.mac_only
def test_source_install_never_writes_the_agent(app, not_frozen, home, monkeypatch):
    run = FakeRun({("launchctl", "kickstart"): Done(1, "no such service")})
    monkeypatch.setattr(app.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="login item isn't installed"):
        app.start_service()
    assert not _agent(home).exists()
    assert run.calls == [["launchctl", "kickstart", f"gui/{os.getuid()}/{LABEL}"]]


# ---------- output to the log ----------

@pytest.fixture
def logs(tmp_path, monkeypatch):
    d = tmp_path / "Logs"
    monkeypatch.setattr(platforms, "log_dir", lambda: str(d))
    return d / "Huntsman for Mac.log"


@pytest.mark.mac_only
def test_frozen_app_started_from_finder_writes_to_the_log(frozen, logs, monkeypatch):
    null_out, null_err = open(os.devnull, "w"), open(os.devnull, "w")
    monkeypatch.setattr(sys, "stdout", null_out)
    monkeypatch.setattr(sys, "stderr", null_err)
    try:
        platforms.redirect_output()
        assert sys.stdout is not null_out and sys.stderr is not null_err
        print("hello from the app")
        print("an error", file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        text = logs.read_text()
        assert "hello from the app" in text and "an error" in text
    finally:
        for s in (sys.stdout, sys.stderr):
            if s not in (null_out, null_err):
                s.close()
        null_out.close()
        null_err.close()


@pytest.mark.mac_only
def test_frozen_output_to_a_terminal_or_pipe_stays_there(frozen, logs, monkeypatch, tmp_path):
    f = open(tmp_path / "pipe.txt", "w")
    monkeypatch.setattr(sys, "stdout", f)
    monkeypatch.setattr(sys, "stderr", f)
    try:
        platforms.redirect_output()
        assert sys.stdout is f and sys.stderr is f
        assert not logs.exists()
    finally:
        f.close()


def test_source_install_output_is_left_alone(not_frozen, logs, monkeypatch):
    null = open(os.devnull, "w")
    monkeypatch.setattr(sys, "stdout", null)
    monkeypatch.setattr(sys, "stderr", null)
    try:
        platforms.redirect_output()
        assert sys.stdout is null and sys.stderr is null
        assert not logs.exists()
    finally:
        null.close()


# ---------- Uninstall ----------

def _applescript(call):
    assert call[0] == "/usr/bin/osascript" and call[1] == "-e"
    return call[2]


@pytest.mark.mac_only
def test_uninstall_stops_the_service_removes_the_app_then_the_agent(app, frozen, home):
    _agent(home).parent.mkdir(parents=True)
    _agent(home).write_text("x")
    run = FakeRun()
    r = app.uninstall_mac(PKG_APP, run=run)
    assert r == {"ok": True, "data": True}
    uid = os.getuid()
    assert run.calls[0] == ["launchctl", "bootout", f"gui/{uid}/{LABEL}"]   # restores the keyboard's lighting
    script = _applescript(run.calls[1])
    assert script.endswith("with administrator privileges")
    rm, forget = script.index("/bin/rm -rf"), script.index("/usr/sbin/pkgutil --forget io.github.huntsman-for-mac.pkg")
    assert rm < forget
    assert "Huntsman for Mac.app" in script
    assert len(run.calls) == 3
    assert not _agent(home).exists()


@pytest.mark.mac_only
def test_uninstall_stops_the_service_again_after_the_password_before_removing_the_agent(app, home):
    """A Studio call during the password prompt may have started the service again: stop it once more, while its
    agent still exists, and only then remove the agent."""
    _agent(home).parent.mkdir(parents=True)
    _agent(home).write_text("x")
    seen = []
    run = FakeRun()

    def recording(argv, **kw):
        seen.append((list(argv[:2]), _agent(home).exists()))
        return run(argv, **kw)
    r = app.uninstall_mac(PKG_APP, run=recording)
    assert r["ok"] is True
    bootout = ["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"]
    assert run.calls[0] == bootout and run.calls[1][0] == "/usr/bin/osascript" and run.calls[2] == bootout
    assert seen[2] == (["launchctl", "bootout"], True)      # the agent was still there for the second stop
    assert not _agent(home).exists()


@pytest.mark.mac_only
def test_uninstall_keeps_the_settings_and_the_log(app, frozen, home):
    data = home / "Library" / "Application Support" / "Huntsman for Mac"
    data.mkdir(parents=True)
    (data / "state.json").write_text("{}")
    app.uninstall_mac(PKG_APP, run=FakeRun())
    assert (data / "state.json").exists()
    assert "Application Support" not in app.uninstall_script(PKG_APP)
    assert "Logs" not in app.uninstall_script(PKG_APP)


@pytest.mark.mac_only
def test_uninstall_cancelled_at_the_password_prompt_changes_nothing(app, frozen, home):
    _agent(home).parent.mkdir(parents=True)
    _agent(home).write_text("x")
    run = FakeRun({("/usr/bin/osascript",): Done(1, "execution error: User canceled. (-128)")})
    r = app.uninstall_mac(PKG_APP, run=run)
    assert r["ok"] is False and "still installed" in r["error"]
    assert _agent(home).exists()
    # the service is started again from the same agent
    assert run.calls[-1] == ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(_agent(home))]


@pytest.mark.mac_only
def test_uninstall_script_quotes_the_path_for_the_shell_and_applescript(app):
    s = app.uninstall_script('/Applications/Huntsman for Mac.app')
    assert s.startswith('do shell script "')
    assert "'/Applications/Huntsman for Mac.app'" in s     # shell-quoted inside the AppleScript string


@pytest.mark.parametrize("bad", ["", "relative/Huntsman for Mac.app", "/Applications", "/", "/Users/x/Other.app",
                                 "/Users/x/Applications/Huntsman for Mac.app", "/Volumes/X/Applications/Huntsman for Mac.app",
                                 "/Applications/Other/Huntsman for Mac.app",
                                 "/Applications/Huntsman for Mac.app/..", '/Applications/a"b/Huntsman for Mac.app',
                                 "/Applications/x\n/Huntsman for Mac.app"])
def test_uninstall_refuses_any_other_path(app, bad):
    run = FakeRun()
    r = app.uninstall_mac(bad, run=run)
    assert r["ok"] is False and run.calls == []
    assert "/Applications/Huntsman for Mac.app" in r["error"]


def test_uninstall_from_source_points_at_uninstall_sh(app, not_frozen, monkeypatch):
    api = app.Api(service=object())
    r = api.uninstall()
    assert r["ok"] is False and "uninstall.sh" in r["error"]


@pytest.mark.mac_only
def test_api_uninstall_stops_the_key_test_runs_the_steps_and_quits(app, frozen, monkeypatch):
    order = []
    api = app.Api(service=object())
    monkeypatch.setattr(api, "shutdown", lambda: order.append("shutdown"))
    monkeypatch.setattr(app, "uninstall_mac", lambda b: order.append(("steps", b)) or {"ok": True, "data": True})
    monkeypatch.setattr(api, "_quit_soon", lambda: order.append("quit"))
    assert api.uninstall() == {"ok": True, "data": True}
    assert order == ["shutdown", ("steps", str(frozen)), "quit"]


@pytest.mark.mac_only
def test_api_uninstall_cancelled_gets_the_service_events_back(app, frozen, monkeypatch):
    """After a cancel or failure the window keeps working: live preview and Studio changes reach it again."""
    order = []
    api = app.Api(service=object())
    monkeypatch.setattr(api, "shutdown", lambda: order.append("shutdown"))
    monkeypatch.setattr(api, "start_events", lambda: order.append("events"))
    monkeypatch.setattr(app, "uninstall_mac", lambda b: order.append("steps") or {"ok": False, "error": "cancelled"})
    assert api.uninstall()["ok"] is False
    assert order == ["shutdown", "steps", "events"]


@pytest.mark.mac_only
def test_api_uninstall_done_doesnt_subscribe_again(app, frozen, monkeypatch):
    api = app.Api(service=object())
    monkeypatch.setattr(api, "shutdown", lambda: None)
    monkeypatch.setattr(api, "start_events", lambda: pytest.fail("subscribed after uninstalling"))
    monkeypatch.setattr(app, "uninstall_mac", lambda b: {"ok": True, "data": True})
    monkeypatch.setattr(api, "_quit_soon", lambda: None)
    assert api.uninstall()["ok"] is True


@pytest.mark.mac_only
def test_api_uninstall_that_fails_keeps_the_app_open(app, frozen, monkeypatch):
    api = app.Api(service=object())
    monkeypatch.setattr(api, "shutdown", lambda: None)
    monkeypatch.setattr(api, "start_events", lambda: None)
    monkeypatch.setattr(app, "uninstall_mac", lambda b: {"ok": False, "error": "nope"})
    monkeypatch.setattr(api, "_quit_soon", lambda: pytest.fail("quit after a failed uninstall"))
    assert api.uninstall() == {"ok": False, "error": "nope"}


@pytest.mark.mac_only
def test_platform_status_offers_uninstall_only_in_the_installed_app(app, frozen, monkeypatch):
    api = app.Api(service=object())
    assert api.platform_status()["data"]["can_uninstall"] is True
    monkeypatch.delattr(sys, "frozen")
    assert api.platform_status()["data"]["can_uninstall"] is False


def test_windows_build_never_offers_uninstall(app, frozen, monkeypatch):
    from platforms import win_guard
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(win_guard, "notices", lambda: [])
    monkeypatch.setattr(hc, "synapse_block", lambda: None)
    api = app.Api(service=object())
    assert api.platform_status()["data"]["can_uninstall"] is False
    assert api.uninstall()["ok"] is False


@pytest.mark.mac_only
def test_service_trouble_in_the_installed_app_says_install_again_not_install_sh(app, frozen):
    msg = app.not_running_message("x")
    assert "Install Huntsman for Mac again" in msg and "install.sh" not in msg


def test_service_trouble_from_source_still_points_at_install_sh(app, not_frozen):
    assert "./install.sh" in app.not_running_message("x")
