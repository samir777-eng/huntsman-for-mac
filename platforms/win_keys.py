# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Key presses and releases from the Huntsman on Windows (experimental, untested on a Windows PC), via Raw Input.

Same API as inputs/keys.KeyListener: start(), stop(), running, callback(KeyEvent) with HID page-7 usages, so the
lighting engine and the heatmap don't know the platform. A hidden message-only window registers for keyboards
(usage page 1, usage 6) with RIDEV_INPUTSINK, so presses arrive while other apps have the focus; nothing is
hooked or swallowed, typing is untouched, and no permission is needed.

Only the connected Huntsman is read: each Raw Input device's interface name (RIDI_DEVICENAME, e.g.
\\\\?\\HID#VID_1532&PID_02A6&MI_00#...) must carry VID_1532 and the active model's PID; other keyboards and
injected input (no device) are dropped. Raw Input reports set-1 scancodes (MakeCode plus the E0/E1 prefix flags);
SCANCODES maps them to page-7 usages (Microsoft's "USB HID to PS/2 scan code translation table"). Pause and Num
Lock share make code 0x45, so they go by their virtual key; the fake shifts Windows adds around Print Screen and
the arrow keys (virtual key 0xFF, E0 2A / E0 36) are ignored. A press reported by two interfaces of the keyboard
counts once (inputs/keys.Deduper). Key events stay in memory; nothing is stored here.
"""
import ctypes
import re
import threading
import time
import traceback

import huntsman_core as hc
from inputs.keys import ValueHandler, KEYBOARD_PAGE
from inputs.types import InputError

VID = 0x1532
RI_KEY_BREAK, RI_KEY_E0, RI_KEY_E1 = 0x01, 0x02, 0x04
VK_PAUSE, VK_NUMLOCK, VK_FAKE = 0x13, 0x90, 0xFF
WM_INPUT = 0x00FF
RID_INPUT, RIDI_DEVICENAME, RIM_TYPEKEYBOARD = 0x10000003, 0x20000007, 1
RIDEV_INPUTSINK, RIDEV_REMOVE = 0x00000100, 0x00000001
GENERIC_DESKTOP, KEYBOARD_USAGE = 0x01, 0x06

_PLAIN = {
    0x01: 0x29, 0x02: 0x1E, 0x03: 0x1F, 0x04: 0x20, 0x05: 0x21, 0x06: 0x22, 0x07: 0x23, 0x08: 0x24, 0x09: 0x25,
    0x0A: 0x26, 0x0B: 0x27, 0x0C: 0x2D, 0x0D: 0x2E, 0x0E: 0x2A, 0x0F: 0x2B,
    0x10: 0x14, 0x11: 0x1A, 0x12: 0x08, 0x13: 0x15, 0x14: 0x17, 0x15: 0x1C, 0x16: 0x18, 0x17: 0x0C, 0x18: 0x12,
    0x19: 0x13, 0x1A: 0x2F, 0x1B: 0x30, 0x1C: 0x28, 0x1D: 0xE0,
    0x1E: 0x04, 0x1F: 0x16, 0x20: 0x07, 0x21: 0x09, 0x22: 0x0A, 0x23: 0x0B, 0x24: 0x0D, 0x25: 0x0E, 0x26: 0x0F,
    0x27: 0x33, 0x28: 0x34, 0x29: 0x35, 0x2A: 0xE1, 0x2B: 0x31,
    0x2C: 0x1D, 0x2D: 0x1B, 0x2E: 0x06, 0x2F: 0x19, 0x30: 0x05, 0x31: 0x11, 0x32: 0x10, 0x33: 0x36, 0x34: 0x37,
    0x35: 0x38, 0x36: 0xE5, 0x37: 0x55, 0x38: 0xE2, 0x39: 0x2C, 0x3A: 0x39,
    0x3B: 0x3A, 0x3C: 0x3B, 0x3D: 0x3C, 0x3E: 0x3D, 0x3F: 0x3E, 0x40: 0x3F, 0x41: 0x40, 0x42: 0x41, 0x43: 0x42,
    0x44: 0x43, 0x45: 0x53, 0x46: 0x47,
    0x47: 0x5F, 0x48: 0x60, 0x49: 0x61, 0x4A: 0x56, 0x4B: 0x5C, 0x4C: 0x5D, 0x4D: 0x5E, 0x4E: 0x57, 0x4F: 0x59,
    0x50: 0x5A, 0x51: 0x5B, 0x52: 0x62, 0x53: 0x63,
    0x54: 0x46, 0x56: 0x64, 0x57: 0x44, 0x58: 0x45, 0x59: 0x67,
    0x64: 0x68, 0x65: 0x69, 0x66: 0x6A, 0x67: 0x6B, 0x68: 0x6C, 0x69: 0x6D, 0x6A: 0x6E, 0x6B: 0x6F, 0x6C: 0x70,
    0x6D: 0x71, 0x6E: 0x72, 0x76: 0x73,                                        # F13-F24
    0x70: 0x88, 0x73: 0x87, 0x79: 0x8A, 0x7B: 0x8B, 0x7D: 0x89, 0x7E: 0x85,    # international keys
}
_E0 = {
    0x1C: 0x58, 0x1D: 0xE4, 0x35: 0x54, 0x37: 0x46, 0x38: 0xE6, 0x45: 0x53, 0x46: 0x48,
    0x47: 0x4A, 0x48: 0x52, 0x49: 0x4B, 0x4B: 0x50, 0x4D: 0x4F, 0x4F: 0x4D, 0x50: 0x51, 0x51: 0x4E, 0x52: 0x49,
    0x53: 0x4C, 0x5B: 0xE3, 0x5C: 0xE7, 0x5D: 0x65, 0x5E: 0x66,
}
SCANCODES = {**{(c, False): v for c, v in _PLAIN.items()}, **{(c, True): v for c, v in _E0.items()}}
_FAKE_SHIFTS = {0x2A, 0x36}


def usage_for(make, flags, vkey):
    """The page-7 usage of one Raw Input keyboard event, or None for fake and unknown keys."""
    if vkey == VK_FAKE:
        return None
    if vkey == VK_PAUSE:
        return 0x48
    if vkey == VK_NUMLOCK:
        return 0x53
    e0 = bool(flags & RI_KEY_E0)
    if flags & RI_KEY_E1 or (e0 and make in _FAKE_SHIFTS):
        return None
    return SCANCODES.get((make, e0))


def product_id():
    return hc.active_model().pid


def device_matches(name, pid):
    """True for a Raw Input interface name of the Huntsman with this product id (any of its interfaces)."""
    if not name:
        return False
    return re.search(rf"VID_{VID:04X}&PID_{pid:04X}(?![0-9A-F])", name.upper()) is not None


class RawKeyHandler:
    """Raw Input keyboard events -> de-duplicated KeyEvents for callback, for the Huntsman only. Never raises.
    device_name(handle) looks the interface name up (cached per handle and model)."""

    def __init__(self, callback, device_name, pid=product_id, clock=time.monotonic):
        self.values = ValueHandler(callback, clock=clock)
        self.device_name, self.pid = device_name, pid
        self._match = {}

    def matches(self, handle):
        if not handle:
            return False
        key = (handle, self.pid())
        hit = self._match.get(key)
        if hit is None:
            try:
                name = self.device_name(handle)
            except Exception:
                traceback.print_exc()
                name = None
            hit = self._match[key] = device_matches(name, key[1])
        return hit

    def handle(self, device, make, flags, vkey):
        try:
            if not self.matches(device):
                return
            usage = usage_for(make, flags, vkey)
            if usage is not None:
                self.values.handle(KEYBOARD_PAGE, usage, 0 if flags & RI_KEY_BREAK else 1)
        except Exception:
            traceback.print_exc()


class _RawApi:
    def __init__(self):
        from ctypes import wintypes as w

        class RAWINPUTDEVICE(ctypes.Structure):
            _fields_ = [("usUsagePage", w.USHORT), ("usUsage", w.USHORT), ("dwFlags", w.DWORD),
                        ("hwndTarget", w.HWND)]

        class RAWINPUTHEADER(ctypes.Structure):
            _fields_ = [("dwType", w.DWORD), ("dwSize", w.DWORD), ("hDevice", w.HANDLE), ("wParam", w.WPARAM)]

        class RAWKEYBOARD(ctypes.Structure):
            _fields_ = [("MakeCode", w.USHORT), ("Flags", w.USHORT), ("Reserved", w.USHORT), ("VKey", w.USHORT),
                        ("Message", w.UINT), ("ExtraInformation", w.ULONG)]

        class RAWINPUT_KB(ctypes.Structure):
            _fields_ = [("header", RAWINPUTHEADER), ("keyboard", RAWKEYBOARD)]

        self.RAWINPUTDEVICE, self.RAWINPUTHEADER, self.RAWINPUT_KB = RAWINPUTDEVICE, RAWINPUTHEADER, RAWINPUT_KB
        u = self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        u.RegisterRawInputDevices.restype = w.BOOL
        u.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), w.UINT, w.UINT]
        u.GetRawInputData.restype = w.UINT
        u.GetRawInputData.argtypes = [w.HANDLE, w.UINT, w.LPVOID, ctypes.POINTER(w.UINT), w.UINT]
        u.GetRawInputDeviceInfoW.restype = w.UINT
        u.GetRawInputDeviceInfoW.argtypes = [w.HANDLE, w.UINT, w.LPVOID, ctypes.POINTER(w.UINT)]
        self.w = w

    def register(self, hwnd, remove=False):
        rid = self.RAWINPUTDEVICE(GENERIC_DESKTOP, KEYBOARD_USAGE, RIDEV_REMOVE if remove else RIDEV_INPUTSINK,
                                  None if remove else hwnd)
        return bool(self.user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid)))

    def read(self, lparam):
        """(device handle, make, flags, vkey) of a WM_INPUT keyboard event, or None."""
        w = self.w
        size = w.UINT(0)
        hdr = ctypes.sizeof(self.RAWINPUTHEADER)
        self.user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size), hdr)
        if not size.value or size.value > 4096:
            return None
        buf = ctypes.create_string_buffer(max(size.value, ctypes.sizeof(self.RAWINPUT_KB)))
        if self.user32.GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(size), hdr) in (0xFFFFFFFF, 0):
            return None
        ri = self.RAWINPUT_KB.from_buffer(buf)
        if ri.header.dwType != RIM_TYPEKEYBOARD:
            return None
        kb = ri.keyboard
        return ri.header.hDevice or 0, kb.MakeCode, kb.Flags, kb.VKey

    def device_name(self, handle):
        n = self.w.UINT(0)
        self.user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, None, ctypes.byref(n))
        if not n.value or n.value > 1024:
            return None
        buf = ctypes.create_unicode_buffer(n.value + 1)
        if self.user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, buf, ctypes.byref(n)) in (0xFFFFFFFF, 0):
            return None
        return buf.value


class RawKeyListener:
    """inputs.keys.KeyListener's API on Windows. start() raises InputError if Raw Input can't be registered;
    stop() is safe to call more than once and from any thread."""

    def __init__(self, callback):
        self.callback = callback
        self.running = False
        self._win = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self.running:
                return
            from platforms.win_window import MessageWindow
            try:
                raw = _RawApi()
            except Exception as e:
                raise InputError(f"Couldn't read key presses from the keyboard ({e}).") from e
            handler = RawKeyHandler(self.callback, device_name=raw.device_name)

            def on_input(_hwnd, _wparam, lparam):
                ev = raw.read(lparam)
                if ev is not None:
                    handler.handle(*ev)
                return None   # DefWindowProc cleans the input up

            def on_create(hwnd):
                if not raw.register(hwnd):
                    raise OSError(f"RegisterRawInputDevices failed ({ctypes.get_last_error()})")

            win = MessageWindow("keys", {WM_INPUT: on_input}, message_only=True, on_create=on_create,
                                on_destroy=lambda hwnd: raw.register(hwnd, remove=True))
            try:
                win.start()
            except OSError as e:
                raise InputError(f"Couldn't read key presses from the keyboard ({e}).") from e
            self._win, self.running = win, True

    def stop(self):
        with self._lock:
            win, self._win = self._win, None
            self.running = False
        if win is not None:
            win.stop()
