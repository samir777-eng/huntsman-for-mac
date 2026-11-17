# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Inputs that drive app-rendered lighting: key presses (keys), sound (audio), and system state (smart).

Importing the package is cheap: keys/audio/smart load IOKit, sounddevice/numpy and pyobjc only when imported.
"""
from inputs.types import AudioState, InputError, InputPermissionError, KeyEvent

__all__ = ["AudioState", "InputError", "InputPermissionError", "KeyEvent"]
