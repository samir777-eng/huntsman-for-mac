# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Shared value types for inputs/ (and for lighting/, which may import them from here)."""
from dataclasses import dataclass, field

BANDS = 16


@dataclass(frozen=True)
class KeyEvent:
    """One physical key press or release from the Huntsman.

    usage: HID usage on the keyboard page (page 7), e.g. W = 0x1A. Map it to a key id with
    lighting Keymap.by_hid_usage(usage). t: time.monotonic() seconds when it arrived.
    """
    usage: int
    down: bool
    t: float


@dataclass
class AudioState:
    """Loudness (level) and 16 log-spaced bands from 40 Hz to 16 kHz, all 0..1 after auto-gain."""
    level: float = 0.0
    bands: list = field(default_factory=lambda: [0.0] * BANDS)


class InputError(RuntimeError):
    """An input can't start; the message is written for the user."""


class InputPermissionError(InputError):
    """macOS privacy settings block the input (Input Monitoring or Microphone)."""
