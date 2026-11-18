# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Things on Windows that take the keyboard away from this app (experimental, untested on a Windows PC).

Razer Synapse: while it runs it holds the keyboard (it rewrites the live profile, and two programs talking to the
same HID interface mix up each other's replies). So while one of its processes runs, nothing is sent to the keyboard
at all: huntsman_core.gate() refuses every write with SYNAPSE_MESSAGE (huntsman_core.SynapseRunning), the hidapi
transport (win_hid.py) refuses to open the keyboard or exchange a report, and the app and the lighting service let
go of an open handle; the window polls only this guard (app.Api.platform_status). The check is cached for CHECK_EVERY seconds, so a write after Synapse quits goes through again; a process list that
can't be read counts as "running" (as in easyrazer: writes while Synapse lives get overwritten anyway).
Processes: Synapse 4 (RazerAppEngine.exe), Synapse 3 ("Razer Synapse 3.exe", "Razer Synapse Service.exe",
"Razer Synapse Service Process.exe"), Synapse 2 (RzSynapse.exe). Razer Central and Cortex don't drive the keyboard.

Windows Dynamic Lighting: when HKCU\\Software\\Microsoft\\Lighting AmbientLightingEnabled is 1, Windows may drive
the keyboard's lights itself and this app's lighting commands may do nothing. The window shows how to turn it off
for this keyboard (notices()); the app never changes the setting.

Process listing: CreateToolhelp32Snapshot through ctypes, else `tasklist` without a console window. Off Windows
(tests that pretend to be Windows on a Mac) the list is empty. winreg and ctypes.windll are used only when called.
"""
import csv
import ctypes
import io
import os
import subprocess
import threading
import time
import traceback

SYNAPSE_PROCESSES = frozenset(n.lower() for n in (
    "RazerAppEngine.exe", "Razer Synapse 3.exe", "Razer Synapse Service.exe", "Razer Synapse Service Process.exe",
    "RzSynapse.exe"))
CHECK_EVERY = 5.0
SYNAPSE_MESSAGE = ("Razer Synapse is running, so Huntsman for Mac leaves the keyboard alone: it doesn't read or change "
                   "it (two programs talking to the keyboard at once mix up each other's replies, and Synapse would "
                   "overwrite any change). Quit Synapse, including its icon in the taskbar's notification area, and "
                   "the controls come back within a few seconds.")
LIGHTING_KEY = r"Software\Microsoft\Lighting"
DYNAMIC_LIGHTING_MESSAGE = (
    "Windows Dynamic Lighting is on, so Windows may control the keyboard's lights and lighting changes here may "
    "not show. To give the lights to this app, open Settings, Personalization, Dynamic Lighting, choose the Razer "
    "Huntsman and turn off Dynamic Lighting for it (or turn off \"Use Dynamic Lighting on my devices\" for all "
    "devices).")
CREATE_NO_WINDOW = 0x08000000


def synapse_process(names):
    """The first Synapse process name in names, or None."""
    return next((n for n in names if n and n.lower() in SYNAPSE_PROCESSES), None)


def parse_tasklist(text):
    """Image names from `tasklist /FO CSV /NH` output."""
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2 and row[0]:
            out.append(row[0])
    return out


def _toolhelp_names():
    from ctypes import wintypes as w

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                    ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD),
                    ("szExeFile", w.WCHAR * 260)]
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype, k.CreateToolhelp32Snapshot.argtypes = w.HANDLE, [w.DWORD, w.DWORD]
    k.Process32FirstW.restype = k.Process32NextW.restype = w.BOOL
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k.CloseHandle.restype, k.CloseHandle.argtypes = w.BOOL, [w.HANDLE]
    snap = k.CreateToolhelp32Snapshot(0x00000002, 0)   # TH32CS_SNAPPROCESS
    if not snap or snap == w.HANDLE(-1).value:
        raise OSError(f"CreateToolhelp32Snapshot failed ({ctypes.get_last_error()})")
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        names = []
        ok = k.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            names.append(entry.szExeFile)
            ok = k.Process32NextW(snap, ctypes.byref(entry))
        return names
    finally:
        k.CloseHandle(snap)


def _tasklist_names():
    r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10,
                       creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise OSError(f"tasklist failed: {r.stderr.strip()}")
    return parse_tasklist(r.stdout)


def list_processes():
    """Running programs' file names. Raises OSError when neither way works."""
    if os.name != "nt":
        return []
    try:
        return _toolhelp_names()
    except Exception:
        traceback.print_exc()
    return _tasklist_names()


class Guard:
    """reason(): SYNAPSE_MESSAGE while Synapse runs, else None; re-checked at most every `every` seconds."""

    def __init__(self, list_processes=list_processes, clock=time.monotonic, every=CHECK_EVERY):
        self._list, self._clock, self.every = list_processes, clock, every
        self._lock = threading.Lock()
        self._at = None
        self._reason = None

    def refresh(self):
        try:
            running = synapse_process(self._list()) is not None
        except Exception:
            traceback.print_exc()
            running = True
        self._reason = SYNAPSE_MESSAGE if running else None
        self._at = self._clock()
        return self._reason

    def reason(self):
        with self._lock:
            if self._at is None or self._clock() - self._at >= self.every:
                return self.refresh()
            return self._reason


_guard = Guard()


def write_block_reason():
    """Why writes are refused right now on Windows (Synapse), or None. Called by huntsman_core.gate()."""
    return _guard.reason()


def dynamic_lighting_on(winreg=None):
    if winreg is None:
        import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LIGHTING_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, "AmbientLightingEnabled")
    except OSError:
        return False
    return value == 1


def notices(winreg=None):
    """Messages for the window about Windows settings that get in the way (read only)."""
    try:
        return [DYNAMIC_LIGHTING_MESSAGE] if dynamic_lighting_on(winreg) else []
    except Exception:
        traceback.print_exc()
        return []
