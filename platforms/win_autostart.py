# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Start the lighting service at login on Windows (experimental, untested on a Windows PC), and start it now.

The Mac uses a LaunchAgent (RunAtLoad, KeepAlive only after a crash): "Quit lighting service" exits cleanly and the
service stays off until the next login or until the app's window opens. Windows has no KeepAlive, so the same
behaviour is: the per-user value HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run "Huntsman for Mac lighting"
starts it at login (no admin rights), the service and the app write that value when they run (ensure(): the first
time, and again when Huntsman.exe moved), quitting leaves it in place, and the app starts the service itself when it
isn't answering (spawn). If the user deletes the value after it was added, it stays deleted (state.json remembers it
was added) until Studio is turned on from the app. disable() is for an uninstall; the user may also switch it off in Task Manager, Startup apps,
which Windows records elsewhere and this module leaves alone.

Command line: the packaged build runs "<Huntsman.exe>" --service; from source it is "<pythonw.exe>" "<service.py>"
(pythonw next to the interpreter when there is one, so no console window opens at login).
winreg is imported only when used; tests pass a fake module.
"""
import ntpath
import os
import subprocess
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Huntsman for Mac lighting"
SERVICE_ARG = "--service"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Process creation flags (winbase.h); subprocess only defines them on Windows.
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def default_script(name="service.py"):
    return os.path.join(HERE, name)


def _frozen():
    return bool(getattr(sys, "frozen", False))


def _interpreter(executable, exists):
    """pythonw.exe next to python.exe when it exists (no console window), else the interpreter itself."""
    folder, base = ntpath.split(executable)   # Windows paths (ntpath: also when tests run on the Mac)
    if base.lower() == "python.exe":
        w = ntpath.join(folder, "pythonw.exe")
        if exists(w):
            return w
    return executable


def _argv(extra, script, frozen, executable, exists):
    frozen = _frozen() if frozen is None else frozen
    executable = executable or sys.executable
    if frozen:
        return [executable] + extra
    return [_interpreter(executable, exists or os.path.exists), script]


def service_argv(frozen=None, executable=None, script=None, exists=None):
    """The command that runs the lighting service, as a list for subprocess."""
    return _argv([SERVICE_ARG], script or default_script(), frozen, executable, exists)


def app_argv(frozen=None, executable=None, script=None, exists=None):
    """The command that opens the window app."""
    return _argv([], script or default_script("app.py"), frozen, executable, exists)


def command_line(frozen=None, executable=None, script=None, exists=None):
    """The Run value: each part quoted (paths may contain spaces), arguments after the program."""
    argv = service_argv(frozen, executable, script, exists)
    return " ".join(a if a.startswith("--") else f'"{a}"' for a in argv)


def _reg(winreg):
    if winreg is None:
        import winreg as real
        return real
    return winreg


def current(winreg=None):
    """The Run value's command line, or None when there isn't one."""
    w = _reg(winreg)
    try:
        with w.OpenKey(w.HKEY_CURRENT_USER, RUN_KEY, 0, w.KEY_READ) as key:
            value, _kind = w.QueryValueEx(key, VALUE_NAME)
    except OSError:   # FileNotFoundError: no key or no value
        return None
    return value if isinstance(value, str) else None


def enabled(winreg=None):
    return current(winreg) is not None


def enable(winreg=None, command=None):
    """Write the Run value (only when it is missing or points elsewhere). True when something was written."""
    w = _reg(winreg)
    command = command or command_line()
    if current(w) == command:
        return False
    with w.CreateKeyEx(w.HKEY_CURRENT_USER, RUN_KEY, 0, w.KEY_SET_VALUE) as key:
        w.SetValueEx(key, VALUE_NAME, 0, w.REG_SZ, command)
    return True


def disable(winreg=None):
    """Remove the Run value. True when there was one."""
    w = _reg(winreg)
    try:
        with w.OpenKey(w.HKEY_CURRENT_USER, RUN_KEY, 0, w.KEY_SET_VALUE) as key:
            w.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True


def remove_if_ours(command=None, winreg=None):
    """For an uninstall (Huntsman.exe --remove-autostart): remove the Run value only when it starts this copy
    (compared without case: Windows paths aren't case sensitive). Returns "removed", "absent" (there was none) or
    "other" (it starts another copy, e.g. an unzipped one, which is left alone)."""
    w = _reg(winreg)
    command = command or command_line()
    value = current(w)
    if value is None:
        return "absent"
    if ntpath.normcase(value.strip()) != ntpath.normcase(command):
        return "other"
    disable(w)
    return "removed"


def spawn(argv, popen=None):
    """Start argv detached from this process, without a console window, output discarded."""
    (popen or subprocess.Popen)(argv, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
                                close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)


def ensure(added, force=False, winreg=None, command=None):
    """Start at login, without fighting the user. added: this app wrote the value before (state.json
    "autostart_added"). The value is written when it is missing and was never added (first run), or points elsewhere
    (a moved Huntsman.exe). Missing after it was added means the user removed it: left alone unless force (Studio
    turned on from the app). Returns (added, wrote)."""
    if current(winreg=winreg) is None and added and not force:
        return True, False
    return True, enable(winreg=winreg, command=command or command_line())
