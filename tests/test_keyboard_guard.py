# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The test suite's own guard (tests/conftest.py, _never_the_real_keyboard): no test reaches the plugged-in
Huntsman, through hc.open_transport or the layers under it (pyusb, hidapi, IOKit for the key tester and the typing
listener), unless it replaces that layer itself. Each test here trips the guard on purpose and then clears its record
(the fixture's value), so it doesn't fail at teardown."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import depth_stream  # noqa: E402
import huntsman_core as hc  # noqa: E402
from inputs import keys  # noqa: E402
from platforms import win_hid  # noqa: E402

REAL = "a test tried to open the real keyboard"


def _refused(tried, make):
    with pytest.raises(AssertionError, match=REAL):
        make()
    assert tried
    tried.clear()


def test_open_transport_is_refused(_never_the_real_keyboard):
    _refused(_never_the_real_keyboard, hc.open_transport)


def test_pyusb_transport_is_refused(_never_the_real_keyboard):
    _refused(_never_the_real_keyboard, hc.UsbTransport)


def test_hidapi_transport_is_refused(_never_the_real_keyboard):
    _refused(_never_the_real_keyboard, win_hid.HidTransport)


def test_the_key_testers_iokit_is_refused(_never_the_real_keyboard):
    _refused(_never_the_real_keyboard, depth_stream._IOKit)


def test_the_typing_listeners_hid_is_refused(_never_the_real_keyboard):
    _refused(_never_the_real_keyboard, keys._HID)


@pytest.mark.transport_internals
def test_transport_internals_still_refuses_the_layers_underneath(_never_the_real_keyboard):
    """Marked tests may call hc.open_transport itself, but the real pyusb and hidapi stay refused."""
    _refused(_never_the_real_keyboard, hc.UsbTransport)
    _refused(_never_the_real_keyboard, win_hid.HidTransport)
    _refused(_never_the_real_keyboard, hc.open_transport)   # it reaches one of the two above


def test_the_transports_keep_their_methods_for_tests_that_build_them_by_hand():
    t = object.__new__(hc.UsbTransport)
    assert isinstance(t, hc.UsbTransport) and hasattr(t, "exchange")


def test_a_fake_hid_module_is_allowed(_never_the_real_keyboard):
    """HidTransport(hid_module=<fake>) never imports hidapi: allowed (test_hid_win.py does this)."""
    class NoDevices:
        @staticmethod
        def enumerate(vid=0, pid=0):
            return []
    with pytest.raises(hc.DeviceError):
        win_hid.HidTransport(hid_module=NoDevices)
    assert not _never_the_real_keyboard


def test_a_test_that_replaces_a_layer_gets_its_replacement(monkeypatch):
    monkeypatch.setattr(depth_stream, "_IOKit", lambda: "fake io")
    assert depth_stream._IOKit() == "fake io"


def test_a_fake_hid_in_sys_modules_is_allowed(monkeypatch, _never_the_real_keyboard):
    class FakeHidModule:   # no __file__: a test's stand-in, as test_win_guard.py puts there
        @staticmethod
        def enumerate(vid=0, pid=0):
            return []
    monkeypatch.setitem(sys.modules, "hid", FakeHidModule())
    with pytest.raises(hc.DeviceError):
        win_hid.HidTransport()
    assert not _never_the_real_keyboard
