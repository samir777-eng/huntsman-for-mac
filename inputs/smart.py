# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Smart lighting: dim or switch off when idle, off while the Mac sleeps or the screen is locked, and a
preset per frontmost app.

decide(config, inputs) is the pure rule set. SmartLighting gathers the inputs from platform adapters (polling
idle time and the frontmost app, plus sleep/wake and lock/unlock notifications) and calls on_change(action)
whenever the resulting action changes. Actions are {"brightness": 0..1, "off": bool, "preset": name | None}:
brightness multiplies the user's own brightness, preset None means "the preset the user picked".
MacAdapters is the only part that touches macOS; on Windows default_adapters() picks platforms/win_smart.WinAdapters
(experimental), where the frontmost app is a program name ("steam.exe") in place of a bundle id. Tests pass fake
adapters.
"""
import copy
import ctypes
import ctypes.util
import re
import subprocess
import threading
import traceback
from dataclasses import dataclass

DEFAULT_CONFIG = {
    "idle": {"enabled": False, "minutes": 10, "action": "dim", "dim_to": 0.2},
    "sleep_off": True,
    "lock_off": True,
    "app_rules": [],
}
IDLE_ACTIONS = ("dim", "off")
EVENTS = {"sleep": ("sleeping", True), "wake": ("sleeping", False),
          "lock": ("locked", True), "unlock": ("locked", False)}


def _number(v, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{what} must be a number")
    return v


def _flag(v, what):
    if not isinstance(v, bool):
        raise ValueError(f"{what} must be true or false")
    return v


def normalise_config(config):
    """A complete, validated copy of config (missing fields take defaults). Raises ValueError."""
    if not isinstance(config, dict):
        raise ValueError("smart lighting settings must be an object")
    out = copy.deepcopy(DEFAULT_CONFIG)
    idle = config.get("idle", {})
    if not isinstance(idle, dict):
        raise ValueError("idle must be an object")
    out["idle"].update(idle)
    i = out["idle"]
    _flag(i["enabled"], "idle.enabled")
    if _number(i["minutes"], "idle.minutes") <= 0:
        raise ValueError("idle.minutes must be more than 0")
    if i["action"] not in IDLE_ACTIONS:
        raise ValueError(f"idle.action must be one of {', '.join(IDLE_ACTIONS)}")
    if not 0 <= _number(i["dim_to"], "idle.dim_to") <= 1:
        raise ValueError("idle.dim_to must be between 0 and 1")
    for k in ("sleep_off", "lock_off"):
        out[k] = _flag(config.get(k, out[k]), k)
    rules = config.get("app_rules", [])
    if not isinstance(rules, list):
        raise ValueError("app_rules must be a list")
    out["app_rules"] = []
    for r in rules:
        if not isinstance(r, dict) or not isinstance(r.get("bundle_id"), str) or not r["bundle_id"].strip() \
                or not isinstance(r.get("preset"), str) or not r["preset"]:
            raise ValueError("each app rule needs a bundle_id and a preset")
        out["app_rules"].append({"bundle_id": r["bundle_id"].strip(), "preset": r["preset"]})
    return out


@dataclass(frozen=True)
class SmartInputs:
    idle_seconds: float = 0.0
    sleeping: bool = False
    locked: bool = False
    frontmost: str | None = None


def decide(config, inputs):
    """The action for a normalised config and the current inputs."""
    idle = config["idle"]
    idle_hit = idle["enabled"] and inputs.idle_seconds >= idle["minutes"] * 60
    off = ((config["sleep_off"] and inputs.sleeping) or (config["lock_off"] and inputs.locked)
           or (idle_hit and idle["action"] == "off"))
    if off:
        return {"brightness": 0.0, "off": True, "preset": None}
    preset = next((r["preset"] for r in config["app_rules"] if r["bundle_id"] == inputs.frontmost), None)
    return {"brightness": float(idle["dim_to"]) if idle_hit else 1.0, "off": False, "preset": preset}


class SmartLighting:
    """Runs the rules. start() registers observers and (poll=True) polls every `interval` seconds on a thread.

    on_change is called from the polling thread or the main thread (notifications); it must be quick and
    thread-safe (hand the action to the engine). tick() evaluates once, now.
    """

    def __init__(self, config, on_change, adapters=None):
        self.config = normalise_config(config)
        self.on_change = on_change
        self.adapters = adapters if adapters is not None else default_adapters()
        self.sleeping = self.locked = False
        self.action = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None

    def set_config(self, config):
        cfg = normalise_config(config)
        with self._lock:
            self.config = cfg
        self.tick()

    def _read(self, fn, fallback):
        try:
            return fn()
        except Exception:
            traceback.print_exc()
            return fallback

    def tick(self):
        idle = self._read(self.adapters.idle_seconds, 0.0)
        front = self._read(self.adapters.frontmost_bundle_id, None)
        with self._lock:
            act = decide(self.config, SmartInputs(idle or 0.0, self.sleeping, self.locked, front))
            if act == self.action:
                return
            self.action = act
            try:
                self.on_change(dict(act))
            except Exception:
                traceback.print_exc()

    def _on_event(self, name):
        if name not in EVENTS:
            return
        attr, value = EVENTS[name]
        with self._lock:
            setattr(self, attr, value)
        self.tick()

    def start(self, poll=True, interval=1.0):
        self._stop.clear()
        self.adapters.start_observers(self._on_event)
        self.tick()
        if poll:
            self._thread = threading.Thread(target=self._poll, args=(interval,), daemon=True, name="huntsman-smart")
            self._thread.start()

    def _poll(self, interval):
        while not self._stop.wait(interval):
            self.tick()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(2)
        self._thread = None
        self._read(self.adapters.stop_observers, None)


def default_adapters():
    """This platform's sources: MacAdapters, or WinAdapters on Windows."""
    import platforms
    if platforms.is_windows():
        from platforms.win_smart import WinAdapters
        return WinAdapters()
    return MacAdapters()


def parse_ioreg_idle(text):
    """Seconds from the "HIDIdleTime" = <nanoseconds> line of `ioreg -c IOHIDSystem` output, or None."""
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', text)
    return int(m.group(1)) / 1e9 if m else None


class _IdleIOKit:
    """HIDIdleTime (nanoseconds since the last keyboard/mouse/trackpad input) from the IOHIDSystem entry."""

    def __init__(self):
        io = ctypes.CDLL(ctypes.util.find_library("IOKit"))
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        vp, c = ctypes.c_void_p, ctypes
        io.IOServiceMatching.restype = vp
        io.IOServiceMatching.argtypes = [c.c_char_p]
        io.IOServiceGetMatchingService.restype = c.c_uint32
        io.IOServiceGetMatchingService.argtypes = [c.c_uint32, vp]
        io.IORegistryEntryCreateCFProperty.restype = vp
        io.IORegistryEntryCreateCFProperty.argtypes = [c.c_uint32, vp, vp, c.c_uint32]
        io.IOObjectRelease.argtypes = [c.c_uint32]
        cf.CFStringCreateWithCString.restype = vp
        cf.CFStringCreateWithCString.argtypes = [vp, c.c_char_p, c.c_uint32]
        cf.CFNumberGetValue.restype = c.c_bool
        cf.CFNumberGetValue.argtypes = [vp, c.c_int, vp]
        cf.CFGetTypeID.restype = c.c_ulong
        cf.CFGetTypeID.argtypes = [vp]
        cf.CFNumberGetTypeID.restype = c.c_ulong
        cf.CFRelease.argtypes = [vp]
        self.io, self.cf = io, cf
        self.key = cf.CFStringCreateWithCString(None, b"HIDIdleTime", 0x08000100)

    def seconds(self):
        svc = self.io.IOServiceGetMatchingService(0, self.io.IOServiceMatching(b"IOHIDSystem"))  # consumes the dict
        if not svc:
            return None
        try:
            ref = self.io.IORegistryEntryCreateCFProperty(svc, self.key, None, 0)
            if not ref:
                return None
            try:
                if self.cf.CFGetTypeID(ref) != self.cf.CFNumberGetTypeID():
                    return None
                ns = ctypes.c_int64()
                if not self.cf.CFNumberGetValue(ref, 4, ctypes.byref(ns)):  # kCFNumberSInt64Type
                    return None
                return ns.value / 1e9
            finally:
                self.cf.CFRelease(ref)
        finally:
            self.io.IOObjectRelease(svc)


class MacAdapters:
    """macOS sources for SmartLighting. Observers need the main (Cocoa) run loop running, as under pywebview."""

    WORKSPACE_EVENTS = {
        "NSWorkspaceWillSleepNotification": "sleep",
        "NSWorkspaceDidWakeNotification": "wake",
        "NSWorkspaceScreensDidSleepNotification": "sleep",
        "NSWorkspaceScreensDidWakeNotification": "wake",
    }
    DISTRIBUTED_EVENTS = {"com.apple.screenIsLocked": "lock", "com.apple.screenIsUnlocked": "unlock"}

    def __init__(self):
        self._idle = None
        self._tokens = []  # (center, token)

    def idle_seconds(self):
        try:
            if self._idle is None:
                self._idle = _IdleIOKit()
            s = self._idle.seconds()
            if s is not None:
                return s
        except OSError:
            traceback.print_exc()
        out = subprocess.run(["/usr/sbin/ioreg", "-c", "IOHIDSystem", "-d", "4"], capture_output=True,
                             text=True, timeout=5).stdout
        s = parse_ioreg_idle(out)
        return 0.0 if s is None else s

    def frontmost_bundle_id(self):
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return str(app.bundleIdentifier()) if app is not None and app.bundleIdentifier() else None

    def start_observers(self, on_event):
        import AppKit
        from Foundation import NSDistributedNotificationCenter, NSOperationQueue
        queue = NSOperationQueue.mainQueue()
        ws = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        dist = NSDistributedNotificationCenter.defaultCenter()

        def observe(center, name, event):
            def block(_note):
                try:
                    on_event(event)
                except Exception:
                    traceback.print_exc()
            self._tokens.append((center, center.addObserverForName_object_queue_usingBlock_(name, None, queue, block)))

        for const, event in self.WORKSPACE_EVENTS.items():
            observe(ws, getattr(AppKit, const), event)
        for name, event in self.DISTRIBUTED_EVENTS.items():
            observe(dist, name, event)

    def stop_observers(self):
        tokens, self._tokens = self._tokens, []
        for center, token in tokens:
            center.removeObserver_(token)
