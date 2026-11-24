# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Shared test settings, for running the suite on a Windows host (CI) as well as on the Mac.

- Most tests describe the Mac behaviour (the verified V3 Pro writes without the Experimental switch, the key
  tester runs, ...). On a Windows host they still run, with platforms.current() answering "mac", so the shared
  code (protocol, lighting, Studio, the app's handlers) is checked on Windows Python too. A test that pretends
  Windows (`monkeypatch.setattr(sys, "platform", "win32")`) gets the Windows code paths as usual. File locks and
  the service endpoint always follow the real host (msvcrt and the named pipe on Windows): the Mac's fcntl and
  UNIX socket don't exist there.
- `@pytest.mark.mac_only` (or `pytestmark = pytest.mark.mac_only`) marks tests that need macOS-only pieces
  (fcntl, UNIX sockets, pyusb, IOKit); they are skipped on Windows.
- `@pytest.mark.windows_host` marks tests that check the real Windows host (no pinning); skipped elsewhere.
- No test reaches the real keyboard (the suite runs with a Huntsman plugged in). Every test gets refusing stand-ins
  for each way in: hc.open_transport, the transports under it (hc.UsbTransport: pyusb; win_hid.HidTransport:
  hidapi, unless the test passes its own `hid_module` or puts a fake or None in sys.modules["hid"]), and the IOKit layers of the key
  tester (depth_stream._IOKit) and of the typing listener (inputs.keys._HID). A test that needs one replaces it
  itself (the `fake` fixture replaces hc.Keyboard; monkeypatch.setattr overrides a stand-in). Tests marked
  `@pytest.mark.transport_internals` get the real hc.open_transport, to check how it picks a transport, but the
  transports under it stay refused. A refused call fails the test at teardown too, even when the code under test
  catches the error. Not covered: programs a test starts in a subprocess (none of them may open the keyboard).
  The fixture's value is the list of refused calls (tests/test_keyboard_guard.py clears it on purpose)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ipc  # noqa: E402
import platforms  # noqa: E402

ON_WINDOWS = sys.platform == "win32"


def pytest_configure(config):
    config.addinivalue_line("markers", "mac_only: needs macOS-only pieces; skipped on Windows")
    config.addinivalue_line("markers", "windows_host: checks the real Windows host; skipped elsewhere")
    config.addinivalue_line("markers", "transport_internals: calls the real hc.open_transport (fakes underneath)")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if ON_WINDOWS and "mac_only" in item.keywords:
            item.add_marker(pytest.mark.skip(reason="macOS only"))
        if not ON_WINDOWS and "windows_host" in item.keywords:
            item.add_marker(pytest.mark.skip(reason="Windows host only"))


class _HostPlatform(str):
    """The real "win32", told apart from a test's own monkeypatched "win32" (a plain str)."""


@pytest.fixture(autouse=True)
def _mac_semantics_on_a_windows_host(request, monkeypatch):
    if not ON_WINDOWS or "windows_host" in request.keywords:
        yield
        return
    real_current = platforms.current
    host = {"real": False}

    def current():
        if type(sys.platform) is _HostPlatform and not host["real"]:
            return platforms.MAC
        return real_current()

    def on_host(fn):
        def run(*a, **kw):
            host["real"] = True
            try:
                return fn(*a, **kw)
            finally:
                host["real"] = False
        return run

    monkeypatch.setattr(sys, "platform", _HostPlatform(sys.platform))
    monkeypatch.setattr(platforms, "current", current)
    monkeypatch.setattr(platforms, "lock_fd", on_host(platforms.lock_fd))
    monkeypatch.setattr(platforms, "unlock_fd", on_host(platforms.unlock_fd))
    monkeypatch.setattr(ipc, "service_endpoint", on_host(ipc.service_endpoint))
    yield


def _real_hidapi():
    """`import hid` would load the real hidapi: nothing in sys.modules yet, or a module from a file. A test that put
    a fake module (no __file__) or None (import fails) there has replaced that layer."""
    missing = object()
    mod = sys.modules.get("hid", missing)
    return mod is missing or getattr(mod, "__file__", None) is not None


@pytest.fixture(autouse=True)
def _never_the_real_keyboard(request, monkeypatch):
    """Refusing stand-ins for every way to the plugged-in Huntsman (see the module docstring)."""
    import depth_stream
    import huntsman_core as hc
    from platforms import win_hid

    tried = []

    def refuse(*_a, **_kw):
        tried.append(1)
        raise AssertionError("a test tried to open the real keyboard: use the `fake` fixture")

    class RefusedUsb(hc.UsbTransport):   # a subclass: tests that build one by hand (object.__new__) still can
        def __init__(self, *a, **kw):
            refuse()

    class RefusedHid(win_hid.HidTransport):
        def __init__(self, hid_module=None):
            if hid_module is None and _real_hidapi():
                refuse()
            super().__init__(hid_module=hid_module)

    if request.node.get_closest_marker("transport_internals") is None:
        monkeypatch.setattr(hc, "open_transport", refuse)
    monkeypatch.setattr(hc, "UsbTransport", RefusedUsb)
    monkeypatch.setattr(win_hid, "HidTransport", RefusedHid)
    monkeypatch.setattr(depth_stream, "_IOKit", refuse)
    try:
        from inputs import keys
    except ImportError:
        keys = None
    if keys is not None:
        monkeypatch.setattr(keys, "_HID", refuse)
    yield tried
    if tried:   # code under test may catch the error above (the service's start does): fail the test anyway
        pytest.fail("this test tried to open the real keyboard; use the `fake` fixture", pytrace=False)
