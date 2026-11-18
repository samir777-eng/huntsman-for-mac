# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Shared test settings. `@pytest.mark.mac_only` (or `pytestmark = pytest.mark.mac_only` in a module) marks tests
that need macOS-only pieces (fcntl, UNIX sockets, launchctl, pyusb, the Mac data folders); they are skipped on
Windows, where CI runs everything else."""
import sys

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "mac_only: needs macOS-only pieces; skipped on Windows")


def pytest_collection_modifyitems(config, items):
    if sys.platform != "win32":
        return
    skip = pytest.mark.skip(reason="macOS only")
    for item in items:
        if "mac_only" in item.keywords:
            item.add_marker(skip)
