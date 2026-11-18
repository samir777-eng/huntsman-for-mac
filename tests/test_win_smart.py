# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Smart lighting's Windows sources (platforms/win_smart.py), behind the same adapter interface as MacAdapters:
idle time (GetLastInputInfo), sleep/wake (WM_POWERBROADCAST, display off/on), lock/unlock (WTS session
notifications) and the frontmost app (the foreground window's program name stands in for the Mac's bundle id).
The Win32 calls are replaced by fakes; the platform picks the adapters and the key listener."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from inputs import smart  # noqa: E402
from platforms import win_smart as ws  # noqa: E402


def test_idle_seconds_from_tick_counts_including_the_49_day_wrap():
    assert ws.idle_from_ticks(10_000, 4_000) == 6.0
    assert ws.idle_from_ticks(500, 0xFFFFFFFF - 499) == 1.0
    assert ws.idle_from_ticks(4_000, 4_000) == 0.0


def test_session_events():
    assert ws.session_event(ws.WTS_SESSION_LOCK) == "lock"
    assert ws.session_event(ws.WTS_SESSION_UNLOCK) == "unlock"
    assert ws.session_event(1) is None   # console connect etc.


def test_power_events():
    assert ws.power_event(ws.PBT_APMSUSPEND) == "sleep"
    assert ws.power_event(ws.PBT_APMRESUMESUSPEND) == "wake"
    assert ws.power_event(ws.PBT_APMRESUMEAUTOMATIC) == "wake"
    assert ws.power_event(ws.PBT_POWERSETTINGCHANGE, display=0) == "sleep"     # display off
    assert ws.power_event(ws.PBT_POWERSETTINGCHANGE, display=1) == "wake"
    assert ws.power_event(ws.PBT_POWERSETTINGCHANGE, display=2) is None        # dimmed
    assert ws.power_event(0x000A) is None                                      # power status change


def test_program_names_stand_in_for_bundle_ids():
    assert ws.exe_name(r"C:\Program Files (x86)\Steam\Steam.exe") == "steam.exe"
    assert ws.exe_name("") is None and ws.exe_name(None) is None


class FakeApi:
    def __init__(self):
        self.tick, self.last, self.fg = 60_000, 30_000, r"C:\Games\Game.EXE"

    def tick_count(self):
        return self.tick

    def last_input_tick(self):
        return self.last

    def foreground_exe(self):
        return self.fg


class FakeWindow:
    made = []

    def __init__(self, name, handlers, message_only=True, on_create=None, on_destroy=None):
        self.handlers, self.message_only = handlers, message_only
        self.started = self.stopped = False
        FakeWindow.made.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def send(self, msg, wparam, lparam=0):
        return self.handlers[msg](None, wparam, lparam)


def test_the_windows_adapters_read_idle_time_and_the_frontmost_app():
    a = ws.WinAdapters(api=FakeApi(), window_cls=FakeWindow)
    assert a.idle_seconds() == 30.0
    assert a.frontmost_bundle_id() == "game.exe"
    a.api.fg = None
    assert a.frontmost_bundle_id() is None


def test_observers_turn_window_messages_into_smart_events():
    FakeWindow.made.clear()
    got = []
    a = ws.WinAdapters(api=FakeApi(), window_cls=FakeWindow, display_state=lambda lparam: lparam)
    a.start_observers(got.append)
    w, = FakeWindow.made
    assert w.started and w.message_only is False   # power broadcasts don't reach message-only windows
    assert w.send(ws.WM_POWERBROADCAST, ws.PBT_APMSUSPEND) == 1       # TRUE: the broadcast is handled
    w.send(ws.WM_POWERBROADCAST, ws.PBT_APMRESUMEAUTOMATIC)
    w.send(ws.WM_WTSSESSION_CHANGE, ws.WTS_SESSION_LOCK)
    w.send(ws.WM_WTSSESSION_CHANGE, ws.WTS_SESSION_UNLOCK)
    w.send(ws.WM_POWERBROADCAST, ws.PBT_POWERSETTINGCHANGE, 0)
    w.send(ws.WM_WTSSESSION_CHANGE, 3)
    assert got == ["sleep", "wake", "lock", "unlock", "sleep"]
    a.stop_observers()
    assert w.stopped
    a.stop_observers()   # twice is fine


def test_a_failing_event_consumer_does_not_break_the_window():
    FakeWindow.made.clear()
    a = ws.WinAdapters(api=FakeApi(), window_cls=FakeWindow)

    def boom(_e):
        raise RuntimeError("x")
    a.start_observers(boom)
    FakeWindow.made[0].send(ws.WM_WTSSESSION_CHANGE, ws.WTS_SESSION_LOCK)


def test_smart_lighting_runs_on_the_windows_adapters():
    FakeWindow.made.clear()
    actions = []
    api = FakeApi()
    api.last = api.tick - 11 * 60 * 1000
    cfg = {"idle": {"enabled": True, "minutes": 10, "action": "off"},
           "app_rules": [{"bundle_id": "game.exe", "preset": "Gaming"}]}
    sl = smart.SmartLighting(cfg, actions.append, adapters=ws.WinAdapters(api=api, window_cls=FakeWindow))
    sl.start(poll=False)
    assert actions[-1]["off"] is True
    api.last = api.tick
    sl.tick()
    assert actions[-1] == {"brightness": 1.0, "off": False, "preset": "Gaming"}
    FakeWindow.made[0].send(ws.WM_WTSSESSION_CHANGE, ws.WTS_SESSION_LOCK)
    assert actions[-1]["off"] is True
    sl.stop()


def test_the_platform_picks_the_adapters(monkeypatch):
    assert isinstance(smart.default_adapters(), smart.MacAdapters)
    monkeypatch.setattr(sys, "platform", "win32")
    assert isinstance(smart.default_adapters(), ws.WinAdapters)


def test_the_platform_picks_the_key_listener(monkeypatch):
    import studio
    from inputs.keys import KeyListener
    from platforms.win_keys import RawKeyListener
    assert isinstance(studio._key_listener(lambda e: None), KeyListener)
    monkeypatch.setattr(sys, "platform", "win32")
    assert isinstance(studio._key_listener(lambda e: None), RawKeyListener)


def test_running_apps_are_listed_once_per_program():
    rows = ws.app_list([r"C:\a\Steam.exe", r"C:\b\steam.exe", r"C:\Windows\explorer.exe", None,
                        r"C:\Program Files\Mozilla Firefox\firefox.exe"])
    assert rows == [{"name": "explorer.exe", "bundle_id": "explorer.exe"},
                    {"name": "firefox.exe", "bundle_id": "firefox.exe"},
                    {"name": "steam.exe", "bundle_id": "steam.exe"}]


def test_the_service_lists_windows_apps_on_windows(monkeypatch):
    import service
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ws, "list_running_apps", lambda: [{"name": "steam.exe", "bundle_id": "steam.exe"}])
    assert service.list_running_apps() == [{"name": "steam.exe", "bundle_id": "steam.exe"}]


def test_without_notifications_polling_still_works():
    class Broken(FakeWindow):
        def start(self):
            raise OSError("CreateWindowExW failed")
    a = ws.WinAdapters(api=FakeApi(), window_cls=Broken)
    a.start_observers(lambda e: None)   # logged, not raised
    assert a.idle_seconds() == 30.0
    a.stop_observers()
