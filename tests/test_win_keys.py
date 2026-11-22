# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Typing reactions on Windows (platforms/win_keys.py): Raw Input scancodes (set 1 make codes plus the E0/E1
prefix flags) mapped to the same HID page-7 usages the Mac's IOKit listener reports, only from the Huntsman (the
Raw Input device name carries VID_1532&PID_<active model>), as the same KeyEvent API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import huntsman_core as hc  # noqa: E402
from inputs.types import KeyEvent  # noqa: E402
from platforms import win_keys as wk  # noqa: E402

E0, E1, BREAK = wk.RI_KEY_E0, wk.RI_KEY_E1, wk.RI_KEY_BREAK
VK_PAUSE, VK_NUMLOCK = 0x13, 0x90


def u(make, flags=0, vkey=0x41):
    return wk.usage_for(make, flags, vkey)


# ---------- scancode map ----------

def test_letters_and_digits():
    letters = [0x1E, 0x30, 0x2E, 0x20, 0x12, 0x21, 0x22, 0x23, 0x17, 0x24, 0x25, 0x26, 0x32, 0x31, 0x18, 0x19,
               0x10, 0x13, 0x1F, 0x14, 0x16, 0x2F, 0x11, 0x2D, 0x15, 0x2C]   # A..Z in set 1
    assert [u(c) for c in letters] == list(range(0x04, 0x1E))
    assert [u(c) for c in range(0x02, 0x0C)] == list(range(0x1E, 0x28))   # 1..0


@pytest.mark.parametrize("make,flags,usage", [
    (0x01, 0, 0x29), (0x0E, 0, 0x2A), (0x0F, 0, 0x2B), (0x1C, 0, 0x28), (0x39, 0, 0x2C), (0x3A, 0, 0x39),
    (0x3B, 0, 0x3A), (0x44, 0, 0x43), (0x57, 0, 0x44), (0x58, 0, 0x45),                   # F1, F10, F11, F12
    (0x1D, 0, 0xE0), (0x2A, 0, 0xE1), (0x38, 0, 0xE2), (0x36, 0, 0xE5),                   # left mods, right shift
    (0x1D, E0, 0xE4), (0x38, E0, 0xE6), (0x5B, E0, 0xE3), (0x5C, E0, 0xE7), (0x5D, E0, 0x65),
    (0x48, E0, 0x52), (0x50, E0, 0x51), (0x4B, E0, 0x50), (0x4D, E0, 0x4F),                # arrows
    (0x48, 0, 0x60), (0x50, 0, 0x5A), (0x4B, 0, 0x5C), (0x4D, 0, 0x5E),                    # the same codes: keypad
    (0x52, E0, 0x49), (0x53, E0, 0x4C), (0x47, E0, 0x4A), (0x4F, E0, 0x4D), (0x49, E0, 0x4B), (0x51, E0, 0x4E),
    (0x1C, E0, 0x58), (0x35, E0, 0x54), (0x37, 0, 0x55), (0x4A, 0, 0x56), (0x4E, 0, 0x57), (0x53, 0, 0x63),
    (0x37, E0, 0x46), (0x54, 0, 0x46),                                                     # Print Screen, Alt+PrtSc
    (0x46, 0, 0x47), (0x46, E0, 0x48),                                                     # Scroll Lock, Ctrl+Pause
    (0x29, 0, 0x35), (0x2B, 0, 0x31), (0x56, 0, 0x64), (0x0C, 0, 0x2D), (0x0D, 0, 0x2E),
])
def test_named_keys(make, flags, usage):
    assert u(make, flags) == usage
    assert u(make, flags | BREAK) == usage   # a release maps the same way


def test_pause_and_num_lock_go_by_their_virtual_key():
    assert u(0x1D, E1, VK_PAUSE) == 0x48       # Pause: E1 1D 45, reported as one event with VK_PAUSE
    assert u(0x45, 0, VK_NUMLOCK) == 0x53
    assert u(0x45, E0, VK_NUMLOCK) == 0x53


def test_fake_keys_are_ignored():
    assert u(0x2A, E0, 0xFF) is None            # the fake shift around Print Screen and the arrows
    assert u(0x45, 0, 0xFF) is None             # the second half of Pause
    assert u(0x2A, E0) is None and u(0x36, E0) is None
    assert u(0x00) is None and u(0xFF) is None and u(0x7F, E0) is None


def test_every_mapped_usage_is_a_key_the_mac_listener_reports_too():
    for (code, e0), usage in wk.SCANCODES.items():
        assert 0x04 <= usage <= 0xE7, (hex(code), e0, hex(usage))
    assert len(set(wk.SCANCODES.values())) >= 100


# ---------- device filter ----------

NAME = r"\\?\HID#VID_1532&PID_02A6&MI_00#7&2b0a5c11&0&0000#{884b96c3-56ef-11d1-bc8c-00a0c91405dd}"


def test_only_the_huntsman_of_the_active_model_matches():
    assert wk.device_matches(NAME, 0x02A6)
    assert wk.device_matches(NAME.lower(), 0x02A6)
    assert not wk.device_matches(NAME, 0x02A7)
    assert not wk.device_matches(NAME.replace("VID_1532", "VID_046D"), 0x02A6)
    assert not wk.device_matches(r"\\?\HID#VID_1532&PID_02A60&MI_00#x", 0x02A6)
    assert not wk.device_matches(None, 0x02A6) and not wk.device_matches("", 0x02A6)


def test_the_filter_follows_the_active_model():
    hc.set_active_model(0x02B0)
    try:
        assert wk.product_id() == 0x02B0
    finally:
        hc.set_active_model(0x02A6)


# ---------- events ----------

class Names:
    def __init__(self, names):
        self.names, self.asked = names, []

    def __call__(self, handle):
        self.asked.append(handle)
        return self.names.get(handle)


def handler(names, events, t=None):
    clock = iter(t or [i * 0.1 for i in range(100)])
    return wk.RawKeyHandler(events.append, device_name=Names(names), pid=lambda: 0x02A6, clock=lambda: next(clock))


def test_presses_from_the_huntsman_become_key_events():
    events = []
    h = handler({1: NAME}, events)
    h.handle(1, 0x11, 0, 0x57)           # W down
    h.handle(1, 0x11, BREAK, 0x57)       # W up
    assert events == [KeyEvent(0x1A, True, 0.0), KeyEvent(0x1A, False, 0.1)]


def test_other_keyboards_and_injected_input_are_never_read():
    events = []
    h = handler({1: NAME, 2: r"\\?\HID#VID_046D&PID_C31C&MI_00#x"}, events)
    h.handle(2, 0x11, 0, 0x57)
    h.handle(0, 0x11, 0, 0x57)           # no device: SendInput / injected
    h.handle(3, 0x11, 0, 0x57)           # name lookup failed
    assert events == []


def test_device_names_are_looked_up_once_per_handle():
    events = []
    names = Names({1: NAME})
    h = wk.RawKeyHandler(events.append, device_name=names, pid=lambda: 0x02A6, clock=lambda: 0.0)
    for _ in range(3):
        h.handle(1, 0x1E, 0, 0x41)
        h.handle(1, 0x1E, BREAK, 0x41)
    assert names.asked == [1]


def test_a_new_model_drops_the_cached_matches():
    events, pid = [], [0x02A6]
    h = wk.RawKeyHandler(events.append, device_name=Names({1: NAME}), pid=lambda: pid[0], clock=lambda: 0.0)
    h.handle(1, 0x1E, 0, 0x41)
    pid[0] = 0x02A7
    h.handle(1, 0x1E, BREAK, 0x41)
    assert [e.down for e in events] == [True]


def test_the_same_press_from_two_interfaces_counts_once():
    events = []
    h = handler({1: NAME, 2: NAME.replace("MI_00", "MI_02")}, events, t=[0.0, 0.001, 0.5])
    h.handle(1, 0x1E, 0, 0x41)
    h.handle(2, 0x1E, 0, 0x41)
    h.handle(1, 0x1E, BREAK, 0x41)
    assert events == [KeyEvent(0x04, True, 0.0), KeyEvent(0x04, False, 0.5)]


def test_unmapped_codes_and_a_failing_consumer_do_not_raise():
    def boom(e):
        raise RuntimeError("engine gone")
    h = wk.RawKeyHandler(boom, device_name=Names({1: NAME}), pid=lambda: 0x02A6, clock=lambda: 0.0)
    h.handle(1, 0x7F, E0, 0x00)
    h.handle(1, 0x1E, 0, 0x41)           # consumer raises: swallowed


def test_the_listener_has_the_mac_listener_api_and_imports_on_the_mac():
    lst = wk.RawKeyListener(lambda e: None)
    assert lst.running is False and callable(lst.start) and callable(lst.stop)
    lst.stop()   # safe before start
