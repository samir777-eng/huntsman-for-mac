# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Smart lighting rules: pure decide() and the SmartLighting state machine with fake platform adapters."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from inputs import smart  # noqa: E402
from inputs.smart import SmartInputs, decide  # noqa: E402

ON = {"brightness": 1.0, "off": False, "preset": None}
OFF = {"brightness": 0.0, "off": True, "preset": None}


def cfg(**over):
    c = {"idle": {"enabled": True, "minutes": 5, "action": "dim", "dim_to": 0.25},
         "sleep_off": True, "lock_off": True,
         "app_rules": [{"bundle_id": "com.valvesoftware.steam", "preset": "Gaming"},
                       {"bundle_id": "com.apple.Music", "preset": "Music"}]}
    c.update(over)
    return smart.normalise_config(c)


def test_defaults_fill_a_partial_config():
    c = smart.normalise_config({})
    assert c == smart.DEFAULT_CONFIG
    c = smart.normalise_config({"idle": {"enabled": True}})
    assert c["idle"] == {"enabled": True, "minutes": smart.DEFAULT_CONFIG["idle"]["minutes"],
                         "action": "dim", "dim_to": smart.DEFAULT_CONFIG["idle"]["dim_to"]}


@pytest.mark.parametrize("bad", [
    {"idle": {"action": "explode"}},
    {"idle": {"minutes": 0}},
    {"idle": {"minutes": "five"}},
    {"idle": {"dim_to": 1.5}},
    {"app_rules": [{"bundle_id": "", "preset": "X"}]},
    {"app_rules": [{"bundle_id": "com.x"}]},
    {"app_rules": "nope"},
    {"sleep_off": "yes"},
])
def test_invalid_config_is_rejected(bad):
    with pytest.raises(ValueError):
        smart.normalise_config(bad)


def test_active_user_gets_full_brightness():
    assert decide(cfg(), SmartInputs(idle_seconds=10)) == ON


def test_idle_dims_after_the_timeout():
    assert decide(cfg(), SmartInputs(idle_seconds=299)) == ON
    assert decide(cfg(), SmartInputs(idle_seconds=300)) == {"brightness": 0.25, "off": False, "preset": None}


def test_idle_can_turn_off_instead():
    c = cfg(idle={"enabled": True, "minutes": 1, "action": "off"})
    assert decide(c, SmartInputs(idle_seconds=60)) == OFF


def test_idle_disabled_never_dims():
    c = cfg(idle={"enabled": False, "minutes": 1})
    assert decide(c, SmartInputs(idle_seconds=10_000)) == ON


def test_sleep_and_lock_turn_off_when_enabled():
    assert decide(cfg(), SmartInputs(sleeping=True)) == OFF
    assert decide(cfg(), SmartInputs(locked=True)) == OFF
    assert decide(cfg(sleep_off=False), SmartInputs(sleeping=True)) == ON
    assert decide(cfg(lock_off=False), SmartInputs(locked=True)) == ON


def test_frontmost_app_picks_its_preset():
    assert decide(cfg(), SmartInputs(frontmost="com.apple.Music"))["preset"] == "Music"
    assert decide(cfg(), SmartInputs(frontmost="com.apple.Safari"))["preset"] is None
    assert decide(cfg(), SmartInputs(frontmost=None))["preset"] is None


def test_app_preset_is_kept_while_dimmed_but_dropped_when_off():
    dim = decide(cfg(), SmartInputs(idle_seconds=600, frontmost="com.apple.Music"))
    assert dim == {"brightness": 0.25, "off": False, "preset": "Music"}
    off = decide(cfg(), SmartInputs(locked=True, frontmost="com.apple.Music"))
    assert off == OFF


class FakeAdapters:
    def __init__(self):
        self.idle = 0.0
        self.front = None
        self.on_event = None
        self.stopped = False

    def idle_seconds(self):
        return self.idle

    def frontmost_bundle_id(self):
        return self.front

    def start_observers(self, on_event):
        self.on_event = on_event

    def stop_observers(self):
        self.stopped = True


def machine(config=None):
    changes = []
    fa = FakeAdapters()
    s = smart.SmartLighting(config if config is not None else cfg(), changes.append, adapters=fa)
    return s, fa, changes


def test_first_tick_reports_the_starting_action_then_only_changes():
    s, fa, changes = machine()
    s.tick()
    s.tick()
    assert changes == [ON]
    fa.idle = 301  # the user walked away (idle time comes from the system clock of input events)
    s.tick()
    s.tick()
    fa.idle = 0.5  # back at the keyboard
    s.tick()
    assert changes == [ON, {"brightness": 0.25, "off": False, "preset": None}, ON]


def test_sleep_and_wake_events_switch_off_and_back_on():
    s, fa, changes = machine()
    s.start(poll=False)
    fa.on_event("sleep")
    fa.on_event("wake")
    assert changes == [ON, OFF, ON]


def test_lock_holds_off_through_a_wake():
    s, fa, changes = machine()
    s.start(poll=False)
    fa.on_event("lock")
    fa.on_event("sleep")
    fa.on_event("wake")
    assert changes[-1] == OFF
    fa.on_event("unlock")
    assert changes[-1] == ON


def test_switching_apps_changes_preset():
    s, fa, changes = machine()
    s.tick()
    fa.front = "com.valvesoftware.steam"
    s.tick()
    fa.front = "com.apple.finder"
    s.tick()
    assert [c["preset"] for c in changes] == [None, "Gaming", None]


def test_unknown_events_are_ignored():
    s, fa, changes = machine()
    s.start(poll=False)
    fa.on_event("teleport")
    assert changes == [ON]


def test_set_config_reevaluates():
    s, fa, changes = machine()
    fa.idle = 120
    s.tick()
    s.set_config(cfg(idle={"enabled": True, "minutes": 1, "action": "off"}))
    assert changes == [ON, OFF]
    assert s.action == OFF


def test_failing_adapter_reads_count_as_active_and_no_app():
    class Broken(FakeAdapters):
        def idle_seconds(self):
            raise OSError("IOKit gone")

        def frontmost_bundle_id(self):
            raise RuntimeError("no workspace")

    changes = []
    s = smart.SmartLighting(cfg(), changes.append, adapters=Broken())
    s.tick()
    assert changes == [ON]


def test_failing_on_change_does_not_break_the_machine():
    fa = FakeAdapters()
    calls = []

    def boom(a):
        calls.append(a)
        raise RuntimeError("engine gone")

    s = smart.SmartLighting(cfg(), boom, adapters=fa)
    s.tick()
    fa.idle = 1000
    s.tick()
    assert len(calls) == 2


def test_stop_removes_observers():
    s, fa, changes = machine()
    s.start(poll=False)
    s.stop()
    assert fa.stopped


def test_poll_thread_ticks_and_stops():
    import time
    s, fa, changes = machine()
    s.start(poll=True, interval=0.01)
    deadline = time.monotonic() + 2
    while not changes and time.monotonic() < deadline:
        time.sleep(0.01)
    s.stop()
    assert changes == [ON]


def test_parse_idle_ns_from_ioreg_text():
    text = '    |   "HIDIdleTime" = 4523000000\n    |   "Other" = 1\n'
    assert smart.parse_ioreg_idle(text) == pytest.approx(4.523)
    assert smart.parse_ioreg_idle("nothing here") is None
