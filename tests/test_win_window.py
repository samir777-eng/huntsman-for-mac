# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The hidden message window's thread (platforms/win_window.py) against a fake user32/kernel32: a window that
starts too late is given up for good (no on_create, destroyed, its thread ends) even when start() is called again,
and stop() ends the message loop. No Windows API is touched."""
import os
import queue
import sys
import threading
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from platforms import win_window as ww  # noqa: E402


class FakeApi:
    def __init__(self):
        self.create_gate = threading.Event()
        self.create_gate.set()
        self.created, self.destroyed, self.next_hwnd = [], [], 100
        self.msgs = {}
        self.lock = threading.Lock()
        self.w = types.SimpleNamespace(HWND=lambda v: v, MSG=lambda: object())
        self.WNDPROC = lambda f: f
        self.WNDCLASSW = lambda: types.SimpleNamespace()
        api = self
        self.kernel32 = types.SimpleNamespace(GetModuleHandleW=lambda n: 1,
                                              GetCurrentThreadId=lambda: threading.get_ident())

        def create(*a):
            api.create_gate.wait()
            with api.lock:
                api.next_hwnd += 1
                h = api.next_hwnd
                api.created.append(h)
                api.msgs[threading.get_ident()] = queue.Queue()
            return h

        def get_message(msg, hwnd, a, b):
            q = api.msgs[threading.get_ident()]
            return 0 if q.get() == ww.WM_QUIT else 1

        def post(tid, msg, wp, lp):
            api.msgs[tid].put(msg)
            return True
        self.user32 = types.SimpleNamespace(
            RegisterClassW=lambda wc: 1, UnregisterClassW=lambda cls, h: True, CreateWindowExW=create,
            DestroyWindow=lambda h: api.destroyed.append(h) or True, DefWindowProcW=lambda *a: 0,
            GetMessageW=get_message, TranslateMessage=lambda m: True, DispatchMessageW=lambda m: 0,
            PostThreadMessageW=post)


@pytest.fixture
def fake(monkeypatch):
    a = FakeApi()
    monkeypatch.setattr(ww, "_API", a)
    monkeypatch.setattr(ww, "ctypes", types.SimpleNamespace(byref=lambda x: x, get_last_error=lambda: 0))
    return a


def test_start_and_stop(fake):
    made = []
    win = ww.MessageWindow("t", {}, on_create=made.append)
    win.start()
    t = win._thread
    assert made == fake.created and win.hwnd == fake.created[0]
    win.stop()
    t.join(2)
    assert not t.is_alive() and fake.destroyed == fake.created


def test_a_window_that_starts_too_late_is_given_up_even_after_a_new_start(fake):
    made = []
    win = ww.MessageWindow("t", {}, on_create=made.append)
    fake.create_gate.clear()
    with pytest.raises(OSError, match="didn't start"):
        win.start(timeout=0.05)
    late = [t for t in threading.enumerate() if t.name == "huntsman-t"]
    assert late
    fake.create_gate.set()       # the first window now gets made, after start() gave up on it ...
    win.start()                  # ... and a second start must not revive it
    for t in late:
        t.join(2)
        assert not t.is_alive()  # the late thread ended instead of running a loop no one can stop
    assert len(fake.created) == 2 and made == [win.hwnd]   # on_create ran for the live window only
    late_hwnds = [h for h in fake.created if h != win.hwnd]
    assert late_hwnds and all(h in fake.destroyed for h in late_hwnds)
    t = win._thread
    win.stop()
    t.join(2)
    assert not t.is_alive()
