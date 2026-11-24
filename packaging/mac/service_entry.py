# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Entry point of the installed app's nested "Huntsman Lighting.app" (packaging/mac/huntsman-mac.spec): its own
executable, HuntsmanLighting, so macOS names the lighting service by its own bundle (menu bar, permission prompts).
It runs the lighting service (app.entry with --service); --version and --self-test are the build's smoke test."""
import sys


def service_argv(argv):
    """What to pass to app.entry: the smoke-test flags as given, anything else (launchd, a -psn_ argument from the
    Finder) the service."""
    if "--version" in argv[1:] or "--self-test" in argv[1:]:
        return list(argv)
    return [argv[0], "--service"]


if __name__ == "__main__":
    import app
    sys.exit(app.entry(service_argv(sys.argv)))
