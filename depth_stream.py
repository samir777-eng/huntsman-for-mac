# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Live key-travel stream (report 0x0B) from the Huntsman V3 Pro on macOS, via IOKit.

The keyboard only sends travel readings in "driver mode", where it stops typing by itself.
`DepthSession` switches it into driver mode, reads the stream on a background thread, and
always switches back to normal typing: on stop(), after a time limit, at interpreter exit and on
SIGTERM/SIGHUP (install_signal_stop, which then runs the app's add_shutdown_hook work). A SIGKILL or crash
can't be caught, so every (re)connect also calls recover_typing(), which switches a keyboard left in driver
mode back.
Reading the stream needs macOS Input Monitoring permission for the app.
"""
import atexit
import ctypes
import ctypes.util
import os
import signal
import sys
import threading
import time
import traceback

import huntsman_core as hc

REPORT_ID = 0x0B
UNITS_PER_MM = 16380.0
MODE_HARDWARE, MODE_DRIVER = 0x00, 0x03
NOT_PERMITTED = 0xE00002E2
_ACTIVE = set()  # running sessions, stopped by the signal handler
_SHUTDOWN = []   # app shutdown work (stop Studio, restore lighting, save heat counts) run before a signal exit
SHUTDOWN_LIMIT = 2.0


def recover_typing(kb):
    """If a crash or force-quit left the keyboard in driver mode (not typing), switch it back.
    Returns True if it had to. Never raises: a failed check must not block connecting."""
    try:
        if kb.cmd(0x00, 0x84, size=2)[0] == MODE_DRIVER:
            print("huntsman: keyboard was left in driver mode; switching back to normal typing", file=sys.stderr)
            kb.cmd(0x00, 0x04, [MODE_HARDWARE, 0], 2)
            return True
    except Exception:
        traceback.print_exc()
    return False


def add_shutdown_hook(fn):
    """fn() runs when SIGTERM/SIGHUP quits the app, after running key tests are switched back. All hooks
    together get SHUTDOWN_LIMIT seconds; the app exits even if one hangs."""
    _SHUTDOWN.append(fn)


def _run_shutdown_hooks():
    for fn in list(_SHUTDOWN):
        try:
            fn()
        except Exception:
            traceback.print_exc()


def _on_signal(signum):
    for s in list(_ACTIVE):
        s.stop("Testing stopped because the app was closed.")
    if _SHUTDOWN:
        t = threading.Thread(target=_run_shutdown_hooks, name="huntsman-shutdown", daemon=True)
        t.start()
        t.join(SHUTDOWN_LIMIT)
    os._exit(128 + signum)  # then quit, as the signal asked


def _watch_signals(fd):
    while True:
        data = os.read(fd, 16)
        for signum in data:
            if signum in (signal.SIGTERM, signal.SIGHUP):
                _on_signal(signum)


def install_signal_stop():
    """SIGTERM/SIGHUP (force quit, logout, closed terminal) switch any running test back, then quit.
    Must be called on the main thread. The work runs on a watcher thread woken by set_wakeup_fd:
    under the Cocoa run loop the main thread may not run Python signal handlers for a long time,
    and a handler that never runs would leave SIGTERM swallowed and the app hanging."""
    r, w = os.pipe()
    os.set_blocking(w, False)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: None)  # the C-level handler still writes the signal number to w
    signal.set_wakeup_fd(w)
    threading.Thread(target=_watch_signals, args=(r,), daemon=True).start()


def parse_depth_report(data):
    """Payload after the report id: entries of [key, depth u16 BE], ended by key 0.
    Returns [(key_id, mm)] for keys that are pressed."""
    out = []
    for i in range(0, len(data) - 2, 3):
        key = data[i]
        if key == 0:
            break
        raw = (data[i + 1] << 8) | data[i + 2]
        out.append((key, round(raw / UNITS_PER_MM, 2)))
    return out


class _IOKit:
    """The few IOKit / CoreFoundation calls needed to read HID input reports."""

    def __init__(self):
        self.iokit = ctypes.CDLL(ctypes.util.find_library("IOKit"))
        self.cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        cf, io = self.cf, self.iokit
        vp, c = ctypes.c_void_p, ctypes
        cf.CFStringCreateWithCString.restype = vp
        cf.CFStringCreateWithCString.argtypes = [vp, c.c_char_p, c.c_uint32]
        cf.CFNumberCreate.restype = vp
        cf.CFNumberCreate.argtypes = [vp, c.c_int, vp]
        cf.CFNumberGetValue.argtypes = [vp, c.c_int, vp]
        cf.CFDictionaryCreateMutable.restype = vp
        cf.CFDictionaryCreateMutable.argtypes = [vp, c.c_long, vp, vp]
        cf.CFDictionarySetValue.argtypes = [vp, vp, vp]
        cf.CFRunLoopGetCurrent.restype = vp
        cf.CFRunLoopRunInMode.argtypes = [vp, c.c_double, c.c_bool]
        cf.CFSetGetCount.restype = c.c_long
        cf.CFSetGetCount.argtypes = [vp]
        cf.CFSetGetValues.argtypes = [vp, vp]
        cf.CFRelease.argtypes = [vp]
        io.IOHIDManagerCreate.restype = vp
        io.IOHIDManagerCreate.argtypes = [vp, c.c_uint32]
        io.IOHIDManagerSetDeviceMatching.argtypes = [vp, vp]
        io.IOHIDManagerCopyDevices.restype = vp
        io.IOHIDManagerCopyDevices.argtypes = [vp]
        io.IOHIDDeviceOpen.argtypes = [vp, c.c_uint32]
        io.IOHIDDeviceOpen.restype = c.c_int32
        io.IOHIDDeviceClose.argtypes = [vp, c.c_uint32]
        io.IOHIDDeviceGetProperty.restype = vp
        io.IOHIDDeviceGetProperty.argtypes = [vp, vp]
        io.IOHIDDeviceScheduleWithRunLoop.argtypes = [vp, vp, vp]
        io.IOHIDDeviceUnscheduleFromRunLoop.argtypes = [vp, vp, vp]
        io.IOHIDRequestAccess.argtypes = [c.c_uint32]
        io.IOHIDRequestAccess.restype = c.c_bool
        self.CB = c.CFUNCTYPE(None, vp, c.c_int32, vp, c.c_int, c.c_uint32, c.POINTER(c.c_uint8), c.c_long)
        io.IOHIDDeviceRegisterInputReportCallback.argtypes = [vp, vp, c.c_long, self.CB, vp]
        self.mode = self.s("kCFRunLoopDefaultMode")

    def s(self, text):
        return self.cf.CFStringCreateWithCString(None, text.encode(), 0x08000100)

    def num(self, v):
        b = ctypes.c_int32(v)
        return self.cf.CFNumberCreate(None, 3, ctypes.byref(b))

    def prop(self, dev, key):
        r = self.iokit.IOHIDDeviceGetProperty(dev, self.s(key))
        if not r:
            return None
        v = ctypes.c_int32()
        self.cf.CFNumberGetValue(r, 3, ctypes.byref(v))
        return v.value

    def devices(self):
        mgr = self.iokit.IOHIDManagerCreate(None, 0)
        match = self.cf.CFDictionaryCreateMutable(None, 0, None, None)
        self.cf.CFDictionarySetValue(match, self.s("VendorID"), self.num(hc.VID))
        self.cf.CFDictionarySetValue(match, self.s("ProductID"), self.num(hc.PID))
        self.iokit.IOHIDManagerSetDeviceMatching(mgr, match)
        found = self.iokit.IOHIDManagerCopyDevices(mgr)
        if not found:
            return []
        n = self.cf.CFSetGetCount(found)
        arr = (ctypes.c_void_p * n)()
        self.cf.CFSetGetValues(found, arr)
        return list(arr)


class DepthSession:
    """One key-tester session. on_batch receives [(key_id, mm), ...] about 30 times a second."""

    def __init__(self, keyboard, on_batch, on_end, time_limit=60.0):
        # Device access is serialized by the transport itself, so stop() never waits on app-level locks
        # (stop() can run on the main thread while the window closes).
        self.kb, self.on_batch, self.on_end, self.limit = keyboard, on_batch, on_end, time_limit
        self._stop = threading.Event()
        self._thread = None
        self._latest = []
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._cancelled = False  # set by stop(), even before start() got as far as running
        self.running = False

    def start(self):
        """Returns True once streaming, False if stop() cancelled it first. Raises on failure."""
        io = _IOKit()
        if not io.iokit.IOHIDRequestAccess(1):  # kIOHIDRequestTypeListenEvent: Input Monitoring
            raise hc.DeviceError("Allow Input Monitoring for this app in System Settings, Privacy & Security, "
                                 "Input Monitoring, then try again.")
        ready, failure = threading.Event(), []
        self._thread = threading.Thread(target=self._run, args=(io, ready, failure), daemon=True)
        self._thread.start()
        ready.wait(5)
        if failure or not ready.is_set():
            self._stop.set()
            raise hc.DeviceError(failure[0] if failure else "The keyboard's travel stream didn't start.")
        # Mark running before switching, so any failure below (even a lost reply) still switches back.
        with self._state_lock:
            if self._cancelled:  # stop() came while we waited for the stream: never switch
                self._stop.set()
                return False
            self.running = True
        _ACTIVE.add(self)
        atexit.register(self.stop)
        try:
            self.kb.cmd(0x00, 0x04, [MODE_DRIVER, 0], 2)
        except Exception:
            self.stop()
            raise
        with self._state_lock:
            cancelled = self._cancelled
        if cancelled:  # stop() ran while the switch was in flight and may have finished first: switch back again
            if not self._to_hardware():
                raise hc.DeviceError(UNPLUG)
            return False
        return True

    def _run(self, io, ready, failure):
        bufs, opened = [], []

        def cb(_ctx, _result, _sender, _rtype, rid, report, length):
            if rid == REPORT_ID:
                with self._lock:
                    self._latest = parse_depth_report(bytes(report[1:length]) if report[0] == REPORT_ID else bytes(report[:length]))

        cbf = io.CB(cb)
        loop = io.cf.CFRunLoopGetCurrent()
        for dev in io.devices():
            size = io.prop(dev, "MaxInputReportSize") or 0
            if size < 32:  # the travel stream lives on the interface with large input reports
                continue
            r = io.iokit.IOHIDDeviceOpen(dev, 0) & 0xFFFFFFFF
            if r == NOT_PERMITTED:
                failure.append("macOS blocked reading the keyboard. Allow Input Monitoring for this app in "
                               "System Settings, Privacy & Security, Input Monitoring.")
                break
            if r != 0:
                continue
            buf = (ctypes.c_uint8 * size)()
            bufs.append(buf)
            io.iokit.IOHIDDeviceRegisterInputReportCallback(dev, buf, size, cbf, None)
            io.iokit.IOHIDDeviceScheduleWithRunLoop(dev, loop, io.mode)
            opened.append(dev)
        if not opened and not failure:
            failure.append("Couldn't find the keyboard's travel stream.")
        ready.set()
        reason = None
        try:
            if failure:
                return
            started, last_sent = time.monotonic(), None
            while not self._stop.is_set():
                io.cf.CFRunLoopRunInMode(io.mode, 0.033, False)
                with self._lock:
                    batch = list(self._latest)
                if batch != last_sent:
                    try:
                        self.on_batch(batch)
                    except Exception:
                        pass  # the window may be gone; the time limit and stop below still apply
                    last_sent = batch
                if time.monotonic() - started > self.limit:
                    reason = f"Testing stopped after {self.limit:g} seconds."
                    break
        finally:
            for dev in opened:
                io.iokit.IOHIDDeviceUnscheduleFromRunLoop(dev, loop, io.mode)
                io.iokit.IOHIDDeviceClose(dev, 0)
            if not self._stop.is_set():  # time limit or any unexpected exit: always switch back
                threading.Thread(target=self.stop, args=(reason or "Testing stopped.",), daemon=True).start()

    def stop(self, reason=None):
        """Back to normal typing. Safe to call more than once, from any thread. Returns True on success."""
        with self._state_lock:
            self._cancelled = True
            if not self.running:
                return True
            self.running = False
        self._stop.set()
        _ACTIVE.discard(self)
        atexit.unregister(self.stop)
        ok = self._to_hardware()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(1)
        if not ok:
            reason = UNPLUG
        try:
            self.on_end(reason, ok)
        except Exception:
            pass
        return ok

    def _to_hardware(self):
        """Switch back to normal typing and confirm it with a mode read; three tries."""
        for _ in range(3):
            try:
                self.kb.cmd(0x00, 0x04, [MODE_HARDWARE, 0], 2)
                if self.kb.cmd(0x00, 0x84, size=2)[0] == MODE_HARDWARE:
                    return True
            except Exception:
                time.sleep(0.15)
        return False


UNPLUG = ("The keyboard may still be in test mode and not typing. "
          "Unplug it and plug it back in to restore normal typing.")
