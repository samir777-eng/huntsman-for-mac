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
- No test opens the real keyboard: hc.open_transport (the only way to a real device) raises unless a test replaces it
  (the `fake` fixture replaces hc.Keyboard) or is marked `@pytest.mark.transport_internals` (it checks
  open_transport itself, with fake transports underneath). The suite runs with a Huntsman plugged in."""
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


@pytest.fixture(autouse=True)
def _never_the_real_keyboard(request, monkeypatch):
    """A test that reaches hc.open_transport without a fake would talk to the plugged-in Huntsman: refuse it."""
    if "transport_internals" in request.keywords:
        yield
        return
    import huntsman_core as hc

    tried = []

    def refuse():
        tried.append(1)
        raise AssertionError("a test tried to open the real keyboard: use the `fake` fixture")
    monkeypatch.setattr(hc, "open_transport", refuse)
    yield
    if tried:   # code under test may catch the error above (the service's start does): fail the test anyway
        pytest.fail("this test tried to open the real keyboard; use the `fake` fixture", pytrace=False)
