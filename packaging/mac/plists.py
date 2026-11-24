# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The installed app's Info.plists (packaging/mac/huntsman-mac.spec): the source install's packaging/Info.plist and
packaging/Lighting-Info.plist (one place for names, bundle ids, permission texts, CFBundleShortVersionString and the
build number CFBundleVersion, which a release bumps), with what differs in the frozen build: macOS 14.0 at least
(the numpy wheel's minimum; install.sh keeps 12.0). Plain standard library, so the spec can load it with runpy."""
import os
import plistlib

PACKAGING = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAC_OVERRIDES = {"LSMinimumSystemVersion": "14.0"}


def mac_info(name, version):
    """packaging/<name> for the frozen build. version: huntsman_core.__version__, which the plist must carry
    (a release bumps both); ValueError otherwise, and when CFBundleVersion isn't a whole number."""
    with open(os.path.join(PACKAGING, name), "rb") as f:
        info = plistlib.load(f)
    if info.get("CFBundleShortVersionString") != version:
        raise ValueError(f"packaging/{name}: CFBundleShortVersionString is {info.get('CFBundleShortVersionString')!r},"
                         f" the app is {version!r}")
    if not str(info.get("CFBundleVersion", "")).isdigit():
        raise ValueError(f"packaging/{name}: CFBundleVersion must be a whole number")
    return {**info, **MAC_OVERRIDES}
