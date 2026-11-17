# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Lighting Studio: app-rendered per-key effects, layers, presets and the streaming engine.

Everything here is pure Python except lighting.engine (which talks to the keyboard through an injected
factory) and lighting.presets (which reads/writes presets.json in huntsman_core.data_dir()).
"""
from lighting.frame import AudioState, Frame, KeyEvent, KeyInfo, Keymap

__all__ = ["AudioState", "Frame", "KeyEvent", "KeyInfo", "Keymap"]
