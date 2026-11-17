# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""HID usage page 7 (Keyboard/Keypad) -> layout.json key names, full ANSI layout.

Names follow layout.json exactly (including its spelling "HYPEN"). 0xE7 (right GUI) maps to
"RIGHT_GUI", which this layout uses for the Fn key; Keymap.by_hid_usage only resolves a usage when
the layout has a key with that name, so other layouts never get a wrong match.
"""

USAGE_TO_NAME = {
    **{0x04 + i: chr(ord("A") + i) for i in range(26)},           # A..Z
    **{0x1E + i: str((i + 1) % 10) for i in range(10)},           # 1..9, 0
    0x28: "ENTER", 0x29: "ESC", 0x2A: "BACKSPACE", 0x2B: "TAB", 0x2C: "SPACEBAR",
    0x2D: "HYPEN", 0x2E: "EQUAL", 0x2F: "OPEN_SQUARE_BRACKET", 0x30: "CLOSE_SQUARE_BRACKET",
    0x31: "BACKSLASH", 0x33: "SEMICOLON", 0x34: "APOSTROPHE", 0x35: "TILDE", 0x36: "COMMA",
    0x37: "PERIOD", 0x38: "SLASH", 0x39: "CAPS_LOCK",
    **{0x3A + i: f"F{i + 1}" for i in range(12)},                 # F1..F12
    0x46: "PRINT_SCREEN", 0x47: "SCROLL_LOCK", 0x48: "PAUSE", 0x49: "INSERT", 0x4A: "HOME",
    0x4B: "PAGE_UP", 0x4C: "DELETE", 0x4D: "END", 0x4E: "PAGE_DOWN",
    0x4F: "RIGHT_ARROW", 0x50: "LEFT_ARROW", 0x51: "DOWN_ARROW", 0x52: "UP_ARROW",
    0x53: "NUMPAD_NUM_LOCK", 0x54: "NUMPAD_SLASH", 0x55: "NUMPAD_ASTERISK", 0x56: "NUMPAD_DASH",
    0x57: "NUMPAD_PLUS", 0x58: "NUMPAD_ENTER",
    **{0x59 + i: f"NUMPAD_{i + 1}" for i in range(9)},            # keypad 1..9
    0x62: "NUMPAD_0", 0x63: "NUMPAD_PERIOD", 0x65: "APPLICATION",
    0xE0: "LEFT_CTRL", 0xE1: "LEFT_SHIFT", 0xE2: "LEFT_ALT", 0xE3: "LEFT_GUI",
    0xE4: "RIGHT_CTRL", 0xE5: "RIGHT_SHIFT", 0xE6: "RIGHT_ALT", 0xE7: "RIGHT_GUI",
}
