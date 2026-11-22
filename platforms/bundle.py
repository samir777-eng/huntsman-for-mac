# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""What the packaged Windows build (packaging/windows/huntsman.spec, PyInstaller) must contain, in one place.

The spec reads this file for its hidden imports and data files, and `Huntsman.exe --self-test` (app.self_test)
imports the same modules and reads the same data, so the build and its smoke test can't drift apart. Plain data
only: no imports, so the spec can load it without the app's dependencies."""

# Modules the app imports lazily (inside functions), which PyInstaller's analysis of app.py can't see.
APP_MODULES = [
    "app", "service", "huntsman_core", "models", "ipc", "studio", "depth_stream", "menubar",
    "platforms", "platforms.win_hid", "platforms.win_tray", "platforms.win_autostart", "platforms.win_keys",
    "platforms.win_smart", "platforms.win_guard", "platforms.win_window", "platforms.bundle",
    "lighting", "lighting.engine", "lighting.frame", "lighting.hid_usage", "lighting.layers", "lighting.presets",
    "lighting.effects", "lighting.effects.ambient", "lighting.effects.audio", "lighting.effects.base",
    "lighting.effects.basic", "lighting.effects.reactive",
    "inputs", "inputs.audio", "inputs.keys", "inputs.smart", "inputs.types",
]

# Third-party modules (requirements-win.txt) the app imports lazily.
THIRD_PARTY = [
    "webview", "webview.platforms.winforms", "webview.platforms.edgechromium", "clr_loader", "clr", "pythonnet",
    "pystray", "pystray._win32", "PIL.Image", "PIL.ImageDraw", "hid", "sounddevice", "numpy", "bottle",
    "proxy_tools",
]

HIDDEN_IMPORTS = APP_MODULES + THIRD_PARTY

# Only importable on Windows (or with requirements-win.txt): the self-test skips them elsewhere.
WINDOWS_ONLY = {
    "webview.platforms.winforms", "webview.platforms.edgechromium", "clr_loader", "clr", "pythonnet",
    "pystray", "pystray._win32", "PIL.Image", "PIL.ImageDraw", "hid",
}

# Data files: (path in the repository, folder in the bundle). Folders are copied whole.
DATA = [
    ("ui", "ui"),
    ("layouts", "layouts"),
    ("layout.json", "."),
    ("keymap.json", "."),
]

# Files the window can't start without (checked by the self-test, under the bundle root).
REQUIRED_FILES = ["ui/index.html", "ui/app.js", "ui/studio.js", "ui/style.css", "layout.json", "keymap.json"]
