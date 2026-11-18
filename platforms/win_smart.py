# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Smart lighting's Windows sources (experimental, untested on a Windows PC): the adapter interface of
inputs/smart.MacAdapters (idle_seconds, frontmost_bundle_id, start_observers(on_event), stop_observers).

- idle time: GetLastInputInfo against GetTickCount (both 32-bit milliseconds, so the 49-day wrap is handled);
- sleep/wake: WM_POWERBROADCAST (suspend, resume) and the console display turning off/on
  (RegisterPowerSettingNotification GUID_CONSOLE_DISPLAY_STATE), like the Mac's system and screen sleep;
- lock/unlock: WTSRegisterSessionNotification (WM_WTSSESSION_CHANGE, lock and unlock);
- frontmost app: the program of the foreground window, as its file name in lower case ("steam.exe"). It takes the
  place of the Mac's bundle id in app rules (the settings keep the field name "bundle_id"; the window says "app").

The observers run on a hidden top-level window (platforms/win_window.py): power broadcasts don't reach
message-only windows. Win32 calls go through _SmartApi, made only when used; tests pass fakes.
"""
import ctypes
import ntpath
import struct
import sys
import traceback

WM_POWERBROADCAST, WM_WTSSESSION_CHANGE = 0x0218, 0x02B1
PBT_APMSUSPEND, PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC, PBT_POWERSETTINGCHANGE = 0x4, 0x7, 0x12, 0x8013
WTS_SESSION_LOCK, WTS_SESSION_UNLOCK = 0x7, 0x8
NOTIFY_FOR_THIS_SESSION, DEVICE_NOTIFY_WINDOW_HANDLE = 0, 0
# GUID_CONSOLE_DISPLAY_STATE {6FE69556-704A-47A0-8F24-C28D936FDA47}, as its 16 bytes in memory
DISPLAY_STATE_GUID = struct.pack("<IHH8B", 0x6FE69556, 0x704A, 0x47A0, 0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def idle_from_ticks(now, last):
    return ((now - last) & 0xFFFFFFFF) / 1000.0


def session_event(wparam):
    return {WTS_SESSION_LOCK: "lock", WTS_SESSION_UNLOCK: "unlock"}.get(wparam)


def power_event(wparam, display=None):
    """"sleep" / "wake" / None for a WM_POWERBROADCAST; display is the console display state of a power-setting
    change (0 off, 1 on, 2 dimmed)."""
    if wparam == PBT_APMSUSPEND:
        return "sleep"
    if wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
        return "wake"
    if wparam == PBT_POWERSETTINGCHANGE:
        return {0: "sleep", 1: "wake"}.get(display)
    return None


def parse_power_setting(raw):
    """The display state from the bytes of a POWERBROADCAST_SETTING (GUID, DWORD length, data), or None when it
    is another setting."""
    if len(raw) < 24 or raw[:16] != DISPLAY_STATE_GUID:
        return None
    length = struct.unpack_from("<I", raw, 16)[0]
    return struct.unpack_from("<I", raw, 20)[0] if length >= 4 else None


def exe_name(path):
    return (ntpath.basename(path).lower() or None) if path else None


def app_list(paths):
    """[{"name", "bundle_id"}] for running apps, one row per program, sorted by name."""
    names = sorted({n for n in (exe_name(p) for p in paths) if n})
    return [{"name": n, "bundle_id": n} for n in names]


class _SmartApi:
    def __init__(self):
        from ctypes import wintypes as w

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", w.UINT), ("dwTime", w.DWORD)]
        self.w, self.LASTINPUTINFO = w, LASTINPUTINFO
        u = self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        k = self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
        u.GetLastInputInfo.restype, u.GetLastInputInfo.argtypes = w.BOOL, [ctypes.POINTER(LASTINPUTINFO)]
        k.GetTickCount.restype, k.GetTickCount.argtypes = w.DWORD, []
        u.GetForegroundWindow.restype, u.GetForegroundWindow.argtypes = w.HWND, []
        u.GetWindowThreadProcessId.restype = w.DWORD
        u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        k.OpenProcess.restype, k.OpenProcess.argtypes = w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]
        k.QueryFullProcessImageNameW.restype = w.BOOL
        k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        k.CloseHandle.restype, k.CloseHandle.argtypes = w.BOOL, [w.HANDLE]
        self.WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        u.EnumWindows.restype, u.EnumWindows.argtypes = w.BOOL, [self.WNDENUMPROC, w.LPARAM]
        u.IsWindowVisible.restype, u.IsWindowVisible.argtypes = w.BOOL, [w.HWND]
        u.GetWindow.restype, u.GetWindow.argtypes = w.HWND, [w.HWND, w.UINT]
        u.GetWindowTextLengthW.restype, u.GetWindowTextLengthW.argtypes = ctypes.c_int, [w.HWND]
        self.wts.WTSRegisterSessionNotification.restype = w.BOOL
        self.wts.WTSRegisterSessionNotification.argtypes = [w.HWND, w.DWORD]
        self.wts.WTSUnRegisterSessionNotification.restype = w.BOOL
        self.wts.WTSUnRegisterSessionNotification.argtypes = [w.HWND]
        u.RegisterPowerSettingNotification.restype = w.HANDLE
        u.RegisterPowerSettingNotification.argtypes = [w.HANDLE, ctypes.c_char_p, w.DWORD]
        u.UnregisterPowerSettingNotification.restype = w.BOOL
        u.UnregisterPowerSettingNotification.argtypes = [w.HANDLE]

    def tick_count(self):
        return self.kernel32.GetTickCount()

    def last_input_tick(self):
        info = self.LASTINPUTINFO(ctypes.sizeof(self.LASTINPUTINFO), 0)
        if not self.user32.GetLastInputInfo(ctypes.byref(info)):
            raise OSError(f"GetLastInputInfo failed ({ctypes.get_last_error()})")
        return info.dwTime

    def process_path(self, pid):
        h = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = self.w.DWORD(len(buf))
            return buf.value if self.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else None
        finally:
            self.kernel32.CloseHandle(h)

    def window_pid(self, hwnd):
        pid = self.w.DWORD(0)
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def foreground_exe(self):
        hwnd = self.user32.GetForegroundWindow()
        pid = self.window_pid(hwnd) if hwnd else 0
        return self.process_path(pid) if pid else None

    def app_window_paths(self):
        """Programs of visible, unowned, titled top-level windows (what the taskbar shows, roughly)."""
        pids = set()

        def each(hwnd, _l):
            u = self.user32
            if u.IsWindowVisible(hwnd) and not u.GetWindow(hwnd, 4) and u.GetWindowTextLengthW(hwnd) > 0:  # GW_OWNER
                pids.add(self.window_pid(hwnd))
            return True
        self.user32.EnumWindows(self.WNDENUMPROC(each), 0)
        return [self.process_path(p) for p in pids if p]

    def watch(self, hwnd):
        """Register the window for lock/unlock and display on/off; returns what unwatch() needs."""
        if not self.wts.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION):
            print(f"huntsman: no lock/unlock notifications ({ctypes.get_last_error()})", file=sys.stderr)
        return self.user32.RegisterPowerSettingNotification(hwnd, DISPLAY_STATE_GUID, DEVICE_NOTIFY_WINDOW_HANDLE)

    def unwatch(self, hwnd, power_handle):
        self.wts.WTSUnRegisterSessionNotification(hwnd)
        if power_handle:
            self.user32.UnregisterPowerSettingNotification(power_handle)


def _display_state(lparam):
    if not lparam:
        return None
    return parse_power_setting(ctypes.string_at(lparam, 24))


def list_running_apps():
    """Open apps for per-app rules, by program name."""
    return app_list(_SmartApi().app_window_paths())


class WinAdapters:
    """Windows sources for inputs.smart.SmartLighting (see the module docstring)."""

    def __init__(self, api=None, window_cls=None, display_state=None):
        self._api = api
        self._window_cls = window_cls
        self._display_state = display_state or _display_state
        self._win = None

    @property
    def api(self):
        if self._api is None:
            self._api = _SmartApi()
        return self._api

    def idle_seconds(self):
        a = self.api
        return idle_from_ticks(a.tick_count(), a.last_input_tick())

    def frontmost_bundle_id(self):
        return exe_name(self.api.foreground_exe())

    def start_observers(self, on_event):
        if self._win is not None:
            return

        def emit(event):
            if event is None:
                return
            try:
                on_event(event)
            except Exception:
                traceback.print_exc()

        def power(_hwnd, wparam, lparam):
            display = self._display_state(lparam) if wparam == PBT_POWERSETTINGCHANGE else None
            emit(power_event(wparam, display))
            return 1   # TRUE: handled

        def session(_hwnd, wparam, _lparam):
            emit(session_event(wparam))
            return 0

        registered = {}

        def on_create(hwnd):
            registered["power"] = self.api.watch(hwnd)

        def on_destroy(hwnd):
            self.api.unwatch(hwnd, registered.get("power"))

        if self._window_cls is None:
            from platforms.win_window import MessageWindow
            self._window_cls = MessageWindow
        win = self._window_cls("smart", {WM_POWERBROADCAST: power, WM_WTSSESSION_CHANGE: session},
                               message_only=False, on_create=on_create, on_destroy=on_destroy)
        try:
            win.start()
        except OSError as e:   # idle time and app rules still work by polling
            print(f"huntsman: no sleep/lock notifications: {e}", file=sys.stderr)
            return
        self._win = win

    def stop_observers(self):
        win, self._win = self._win, None
        if win is not None:
            win.stop()
