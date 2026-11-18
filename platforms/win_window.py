# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""A hidden Win32 window with its own message loop on its own thread (experimental, untested on a Windows PC).

Raw Input key presses (WM_INPUT), power broadcasts (WM_POWERBROADCAST), session lock/unlock
(WM_WTSSESSION_CHANGE) and logoff/shutdown (WM_ENDSESSION) all arrive as window messages, so each listener runs
one of these. message_only=True makes an HWND_MESSAGE window (enough for Raw Input); broadcasts such as
WM_POWERBROADCAST and WM_ENDSESSION only reach top-level windows, so those use message_only=False (a top-level
window that is never shown).

handlers: {message: fn(hwnd, wparam, lparam)}; a handler returning an int answers the message with it, None lets
DefWindowProcW answer. on_create(hwnd) / on_destroy(hwnd) run on the window's thread (register and unregister
notifications there). ctypes.windll is only touched in start(), so this module imports on the Mac.
"""
import ctypes
import itertools
import threading
import traceback

HWND_MESSAGE = -3
WM_CLOSE, WM_QUIT = 0x0010, 0x0012
_ids = itertools.count(1)
_API = None


class _Api:
    """user32/kernel32 calls with 64-bit-safe signatures."""

    def __init__(self):
        from ctypes import wintypes as w
        self.w = w
        self.LRESULT = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(self.LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", w.UINT), ("lpfnWndProc", self.WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                        ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
                        ("lpszClassName", w.LPCWSTR)]
        self.WNDCLASSW = WNDCLASSW
        u = self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        k = self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetModuleHandleW.restype, k.GetModuleHandleW.argtypes = w.HMODULE, [w.LPCWSTR]
        k.GetCurrentThreadId.restype, k.GetCurrentThreadId.argtypes = w.DWORD, []
        u.RegisterClassW.restype, u.RegisterClassW.argtypes = w.ATOM, [ctypes.POINTER(WNDCLASSW)]
        u.UnregisterClassW.restype, u.UnregisterClassW.argtypes = w.BOOL, [w.LPCWSTR, w.HINSTANCE]
        u.CreateWindowExW.restype = w.HWND
        u.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
        u.DestroyWindow.restype, u.DestroyWindow.argtypes = w.BOOL, [w.HWND]
        u.DefWindowProcW.restype = self.LRESULT
        u.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        u.GetMessageW.restype, u.GetMessageW.argtypes = w.BOOL, [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
        u.TranslateMessage.restype, u.TranslateMessage.argtypes = w.BOOL, [ctypes.POINTER(w.MSG)]
        u.DispatchMessageW.restype, u.DispatchMessageW.argtypes = self.LRESULT, [ctypes.POINTER(w.MSG)]
        u.PostThreadMessageW.restype = w.BOOL
        u.PostThreadMessageW.argtypes = [w.DWORD, w.UINT, w.WPARAM, w.LPARAM]
        u.PostQuitMessage.restype, u.PostQuitMessage.argtypes = None, [ctypes.c_int]


def api():
    global _API
    if _API is None:
        _API = _Api()
    return _API


class MessageWindow:
    """See the module docstring. start() raises OSError if the window can't be made; stop() is safe any time."""

    def __init__(self, name, handlers, message_only=True, on_create=None, on_destroy=None):
        self.name, self.handlers, self.message_only = name, dict(handlers), message_only
        self.on_create, self.on_destroy = on_create, on_destroy
        self.hwnd = None
        self._tid = None
        self._thread = None
        self._stopping = threading.Event()

    def start(self, timeout=5.0):
        if self._thread is not None:
            return
        self._stopping.clear()
        ready, failure = threading.Event(), []
        self._thread = threading.Thread(target=self._run, args=(ready, failure), daemon=True,
                                        name=f"huntsman-{self.name}")
        self._thread.start()
        if not ready.wait(timeout) or failure:
            self.stop()
            raise OSError(failure[0] if failure else f"the {self.name} window didn't start")

    def stop(self, timeout=2.0):
        self._stopping.set()
        t, tid = self._thread, self._tid
        if tid is not None:
            try:
                api().user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            except Exception:
                traceback.print_exc()
        if t is not None and t is not threading.current_thread():
            t.join(timeout)
        self._thread = None

    def _proc(self, hwnd, msg, wparam, lparam):
        fn = self.handlers.get(msg)
        if fn is not None:
            try:
                r = fn(hwnd, wparam, lparam)
                if r is not None:
                    return r
            except Exception:
                traceback.print_exc()   # never let an exception cross into Windows
        return api().user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self, ready, failure):
        try:
            a = api()
        except Exception as e:   # not Windows, or user32 missing
            failure.append(f"Windows API unavailable: {e}")
            ready.set()
            return
        u, k, w = a.user32, a.kernel32, a.w
        hinst = k.GetModuleHandleW(None)
        cls = f"HuntsmanForMac.{self.name}.{next(_ids)}"
        wndproc = a.WNDPROC(self._proc)   # kept alive by this frame for the loop's lifetime
        wc = a.WNDCLASSW()
        wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = wndproc, hinst, cls
        if not u.RegisterClassW(ctypes.byref(wc)):
            failure.append(f"RegisterClassW failed ({ctypes.get_last_error()})")
            ready.set()
            return
        parent = w.HWND(HWND_MESSAGE) if self.message_only else None
        hwnd = u.CreateWindowExW(0, cls, f"Huntsman for Mac {self.name}", 0, 0, 0, 0, 0, parent, None, hinst, None)
        if not hwnd:
            failure.append(f"CreateWindowExW failed ({ctypes.get_last_error()})")
            u.UnregisterClassW(cls, hinst)
            ready.set()
            return
        self.hwnd, self._tid = hwnd, k.GetCurrentThreadId()
        try:
            if self.on_create is not None:
                self.on_create(hwnd)
        except Exception as e:
            failure.append(str(e) or type(e).__name__)
        ready.set()
        try:
            msg = w.MSG()
            while not failure and not self._stopping.is_set() and u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
        finally:
            try:
                if self.on_destroy is not None:
                    self.on_destroy(hwnd)
            except Exception:
                traceback.print_exc()
            u.DestroyWindow(hwnd)
            u.UnregisterClassW(cls, hinst)
            self.hwnd = self._tid = None
