# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Key presses and releases from the Huntsman while typing normally, via IOKit input-value callbacks.

Only the Huntsman (VID 0x1532, PID 0x02A6) is matched; other keyboards are never read. The device is opened
without seizing it, so typing keeps working. Each press arrives once per HID interface that reports it, so
events are de-duplicated (same usage and state within 5 ms). The IOHIDManager keeps matching while running,
so a replugged keyboard is picked up again.
Needs macOS Input Monitoring for the app. Key events are passed on in memory only; nothing is stored here.
"""
import ctypes
import ctypes.util
import threading
import time
import traceback

from inputs.types import InputError, InputPermissionError, KeyEvent

VID, PID = 0x1532, 0x02A6
KEYBOARD_PAGE = 0x07
FIRST_KEY, LAST_KEY = 0x04, 0xE7  # 0x00-0x03 are "no event" and roll-over error codes; 0xE0-0xE7 modifiers
NOT_PERMITTED = 0xE00002E2  # kIOReturnNotPermitted
DEDUPE_WINDOW = 0.005
PERMISSION_MESSAGE = ("macOS blocked reading key presses. Allow Input Monitoring for Huntsman for Mac in "
                      "System Settings, Privacy & Security, Input Monitoring, then try again.")


def key_value(page, usage, value):
    """(usage, down) for a key on the keyboard page, else None."""
    if page != KEYBOARD_PAGE or not FIRST_KEY <= usage <= LAST_KEY:
        return None
    return usage, value != 0


def open_error(code):
    """A user-facing message for an IOReturn from opening the keyboard, or None when it succeeded."""
    code &= 0xFFFFFFFF
    if code == 0:
        return None
    if code == NOT_PERMITTED:
        return PERMISSION_MESSAGE
    return f"Couldn't read key presses from the keyboard (IOKit error 0x{code:08x})."


class Deduper:
    """Drops a (usage, state) seen again within `window` seconds: the same press from another interface."""

    def __init__(self, window=DEDUPE_WINDOW):
        self.window = window
        self._last = {}

    def accept(self, usage, down, t):
        key = (usage, down)
        prev = self._last.get(key)
        if prev is not None and t - prev < self.window:
            return False
        self._last[key] = t
        return True


class ValueHandler:
    """Turns raw HID values into de-duplicated KeyEvents for `callback`. Never raises."""

    def __init__(self, callback, clock=time.monotonic, window=DEDUPE_WINDOW):
        self.callback, self.clock = callback, clock
        self.dedupe = Deduper(window)

    def handle(self, page, usage, value):
        kv = key_value(page, usage, value)
        if kv is None:
            return
        t = self.clock()
        if not self.dedupe.accept(kv[0], kv[1], t):
            return
        try:
            self.callback(KeyEvent(kv[0], kv[1], t))
        except Exception:
            traceback.print_exc()  # a failing consumer must not stop the listener


class _HID:
    """The IOKit / CoreFoundation calls needed for input-value callbacks (patterns from depth_stream._IOKit)."""

    def __init__(self):
        self.io = ctypes.CDLL(ctypes.util.find_library("IOKit"))
        self.cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        cf, io, vp, c = self.cf, self.io, ctypes.c_void_p, ctypes
        cf.CFStringCreateWithCString.restype = vp
        cf.CFStringCreateWithCString.argtypes = [vp, c.c_char_p, c.c_uint32]
        cf.CFNumberCreate.restype = vp
        cf.CFNumberCreate.argtypes = [vp, c.c_int, vp]
        cf.CFDictionaryCreateMutable.restype = vp
        cf.CFDictionaryCreateMutable.argtypes = [vp, c.c_long, vp, vp]
        cf.CFDictionarySetValue.argtypes = [vp, vp, vp]
        cf.CFRunLoopGetCurrent.restype = vp
        cf.CFRunLoopRunInMode.argtypes = [vp, c.c_double, c.c_bool]
        cf.CFRelease.argtypes = [vp]
        io.IOHIDManagerCreate.restype = vp
        io.IOHIDManagerCreate.argtypes = [vp, c.c_uint32]
        io.IOHIDManagerSetDeviceMatching.argtypes = [vp, vp]
        io.IOHIDManagerOpen.argtypes = [vp, c.c_uint32]
        io.IOHIDManagerOpen.restype = c.c_int32
        io.IOHIDManagerClose.argtypes = [vp, c.c_uint32]
        io.IOHIDManagerClose.restype = c.c_int32
        io.IOHIDManagerScheduleWithRunLoop.argtypes = [vp, vp, vp]
        io.IOHIDManagerUnscheduleFromRunLoop.argtypes = [vp, vp, vp]
        # void (*IOHIDValueCallback)(void *context, IOReturn result, void *sender, IOHIDValueRef value)
        self.CB = c.CFUNCTYPE(None, vp, c.c_int32, vp, vp)
        io.IOHIDManagerRegisterInputValueCallback.argtypes = [vp, self.CB, vp]
        io.IOHIDValueGetElement.restype = vp
        io.IOHIDValueGetElement.argtypes = [vp]
        io.IOHIDValueGetIntegerValue.restype = c.c_long
        io.IOHIDValueGetIntegerValue.argtypes = [vp]
        io.IOHIDElementGetUsagePage.restype = c.c_uint32
        io.IOHIDElementGetUsagePage.argtypes = [vp]
        io.IOHIDElementGetUsage.restype = c.c_uint32
        io.IOHIDElementGetUsage.argtypes = [vp]
        io.IOHIDRequestAccess.argtypes = [c.c_uint32]
        io.IOHIDRequestAccess.restype = c.c_bool
        self.mode = self.s("kCFRunLoopDefaultMode")

    def s(self, text):
        return self.cf.CFStringCreateWithCString(None, text.encode(), 0x08000100)

    def num(self, v):
        b = ctypes.c_int32(v)
        return self.cf.CFNumberCreate(None, 3, ctypes.byref(b))  # kCFNumberSInt32Type

    def request_access(self):
        return bool(self.io.IOHIDRequestAccess(1))  # kIOHIDRequestTypeListenEvent: Input Monitoring

    def manager(self):
        mgr = self.io.IOHIDManagerCreate(None, 0)
        match = self.cf.CFDictionaryCreateMutable(None, 0, None, None)
        self.cf.CFDictionarySetValue(match, self.s("VendorID"), self.num(VID))
        self.cf.CFDictionarySetValue(match, self.s("ProductID"), self.num(PID))
        self.io.IOHIDManagerSetDeviceMatching(mgr, match)
        return mgr


class KeyListener:
    """Calls callback(KeyEvent) for each Huntsman key press/release, from its own CFRunLoop thread.

    start() raises InputPermissionError without Input Monitoring, InputError on other failures.
    stop() is safe to call more than once and from any thread.
    """

    def __init__(self, callback):
        self.handler = ValueHandler(callback)
        self._stop = threading.Event()
        self._thread = None
        self.running = False

    def start(self):
        if self.running:
            return
        io = _HID()
        if not io.request_access():
            raise InputPermissionError(PERMISSION_MESSAGE)
        self._stop.clear()
        ready, failure = threading.Event(), []
        self._thread = threading.Thread(target=self._run, args=(io, ready, failure), daemon=True,
                                        name="huntsman-keys")
        self._thread.start()
        if not ready.wait(5) or failure:
            self._stop.set()
            msg = failure[0] if failure else "The key listener didn't start."
            raise (InputPermissionError if msg == PERMISSION_MESSAGE else InputError)(msg)
        self.running = True

    def stop(self):
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(2)
        self.running = False

    def _run(self, io, ready, failure):
        def on_value(_ctx, _result, _sender, value):
            try:
                elem = io.io.IOHIDValueGetElement(value)
                if elem:
                    self.handler.handle(io.io.IOHIDElementGetUsagePage(elem), io.io.IOHIDElementGetUsage(elem),
                                        io.io.IOHIDValueGetIntegerValue(value))
            except Exception:
                traceback.print_exc()

        cb = io.CB(on_value)  # kept alive by this frame for as long as the loop runs
        loop = io.cf.CFRunLoopGetCurrent()
        mgr = io.manager()
        io.io.IOHIDManagerRegisterInputValueCallback(mgr, cb, None)
        io.io.IOHIDManagerScheduleWithRunLoop(mgr, loop, io.mode)
        err = open_error(io.io.IOHIDManagerOpen(mgr, 0))  # 0: shared, typing keeps working
        if err:
            failure.append(err)
        ready.set()
        try:
            while not failure and not self._stop.is_set():
                io.cf.CFRunLoopRunInMode(io.mode, 0.1, False)
        finally:
            io.io.IOHIDManagerUnscheduleFromRunLoop(mgr, loop, io.mode)
            if not err:
                io.io.IOHIDManagerClose(mgr, 0)
            io.cf.CFRelease(mgr)
            self.running = False
