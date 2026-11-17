# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Pure parts of the key listener: value filtering and per-interface de-duplication. No IOKit."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from inputs import keys  # noqa: E402
from inputs.types import InputError, InputPermissionError, KeyEvent  # noqa: E402


def test_key_event_fields():
    e = KeyEvent(usage=0x1A, down=True, t=1.5)
    assert (e.usage, e.down, e.t) == (0x1A, True, 1.5)


def test_permission_error_is_an_input_error():
    assert issubclass(InputPermissionError, InputError)


@pytest.mark.parametrize("usage,value,expected", [
    (0x1A, 1, (0x1A, True)),     # W down
    (0x04, 0, (0x04, False)),    # A up
    (0xE1, 1, (0xE1, True)),     # left shift (modifier byte bits arrive as usages 0xE0-0xE7)
    (0x16, 2, (0x16, True)),     # any non-zero value is a press
])
def test_key_value_accepts_keyboard_usages(usage, value, expected):
    assert keys.key_value(keys.KEYBOARD_PAGE, usage, value) == expected


@pytest.mark.parametrize("page,usage,value", [
    (0x0C, 0xE9, 1),             # consumer page (volume up): not a key on the key map
    (0x01, 0x06, 1),             # generic desktop
    (0x07, 0x00, 1),             # "no event"
    (0x07, 0x01, 1),             # ErrorRollOver (too many keys held)
    (0x07, 0x03, 1),             # ErrorUndefined
    (0x07, 0xFFFFFFFF, 1),       # array element with no usage
    (0x07, 0x10000, 1),          # out of the page-7 range
])
def test_key_value_rejects_everything_else(page, usage, value):
    assert keys.key_value(page, usage, value) is None


def test_dedupe_drops_the_same_press_from_a_second_interface():
    d = keys.Deduper(window=0.005)
    assert d.accept(0x1A, True, 10.000)
    assert not d.accept(0x1A, True, 10.003)


def test_dedupe_keeps_presses_further_apart_than_the_window():
    d = keys.Deduper(window=0.005)
    assert d.accept(0x1A, True, 10.000)
    assert d.accept(0x1A, True, 10.010)


def test_dedupe_keeps_release_right_after_press():
    d = keys.Deduper(window=0.005)
    assert d.accept(0x1A, True, 10.000)
    assert d.accept(0x1A, False, 10.001)
    assert not d.accept(0x1A, False, 10.002)


def test_dedupe_is_per_key():
    d = keys.Deduper(window=0.005)
    assert d.accept(0x1A, True, 10.000)
    assert d.accept(0x04, True, 10.001)


def test_handle_value_emits_one_event_per_physical_press():
    got = []
    h = keys.ValueHandler(got.append, clock=iter([1.0, 1.001, 1.002, 1.003, 1.004]).__next__)
    h.handle(keys.KEYBOARD_PAGE, 0x1A, 1)   # interface 1
    h.handle(keys.KEYBOARD_PAGE, 0x1A, 1)   # interface 2, same press
    h.handle(0x0C, 0xE9, 1)                  # consumer key: ignored (no clock read needed)
    h.handle(keys.KEYBOARD_PAGE, 0x1A, 0)
    h.handle(keys.KEYBOARD_PAGE, 0x1A, 0)
    assert got == [KeyEvent(0x1A, True, 1.0), KeyEvent(0x1A, False, 1.002)]


def test_handle_value_survives_a_failing_callback():
    calls = []

    def boom(e):
        calls.append(e)
        raise RuntimeError("ui gone")

    h = keys.ValueHandler(boom, clock=iter([1.0, 2.0]).__next__)
    h.handle(keys.KEYBOARD_PAGE, 0x04, 1)
    h.handle(keys.KEYBOARD_PAGE, 0x04, 0)
    assert len(calls) == 2


def test_open_result_messages():
    assert keys.open_error(0) is None
    msg = keys.open_error(keys.NOT_PERMITTED)
    assert "Input Monitoring" in msg
    assert keys.open_error(-536870174) == msg  # the same IOReturn read as a signed int32
    assert "0xe00002c0" in keys.open_error(0xE00002C0).lower()  # anything else names the code


def test_listener_is_not_running_before_start():
    lst = keys.KeyListener(lambda e: None)
    assert not lst.running
    lst.stop()  # safe without start
