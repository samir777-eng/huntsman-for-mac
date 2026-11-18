# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Shared test settings, for running the suite on a Windows host (CI) as well as on the Mac.

- Most tests describe the Mac behaviour (the verified V3 Pro writes without the Experimental switch, the key
  tester runs, ...). On a Windows host they still run, with platforms.current() answering "mac", so the shared
  code (protocol, lighting, Studio, the app's handlers) is checked on Windows Python too. A test that pretends
  Windows (`monkeypatch.setattr(sys, "platform", "win32")`) gets the Windows code paths as usual, and file locks
  always use the real host's mechanism (msvcrt on Windows).
- `@pytest.mark.mac_only` (or `pytestmark = pytest.mark.mac_only`) marks tests that need macOS-only pieces
  (fcntl, UNIX sockets, pyusb, IOKit); they are skipped on Windows.
- `@pytest.mark.windows_host` marks tests that check the real Windows host (no pinning); skipped elsewhere."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import platforms  # noqa: E402

ON_WINDOWS = sys.platform == "win32"


def pytest_configure(config):
    config.addinivalue_line("markers", "mac_only: needs macOS-only pieces; skipped on Windows")
    config.addinivalue_line("markers", "windows_host: checks the real Windows host; skipped elsewhere")


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
    host = {"locking": False}

    def current():
        if type(sys.platform) is _HostPlatform and not host["locking"]:
            return platforms.MAC
        return real_current()

    def on_host(fn):
        def run(*a, **kw):
            host["locking"] = True
            try:
                return fn(*a, **kw)
            finally:
                host["locking"] = False
        return run

    monkeypatch.setattr(sys, "platform", _HostPlatform(sys.platform))
    monkeypatch.setattr(platforms, "current", current)
    monkeypatch.setattr(platforms, "lock_fd", on_host(platforms.lock_fd))
    monkeypatch.setattr(platforms, "unlock_fd", on_host(platforms.unlock_fd))
    yield
