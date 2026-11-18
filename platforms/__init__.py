# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The small platform layer: which OS this is (mac or windows), where settings and the log live, and file locks.

macOS paths and behaviour are the ones the app always had. Windows (experimental, untested on a Windows PC):
settings in %APPDATA%\\Huntsman for Mac, the log in %LOCALAPPDATA%\\Huntsman for Mac\\Logs, locks with
msvcrt.locking on byte 0 of the lock file. The platform is read from sys.platform at every call (not at import), and
nothing OS-only (fcntl, msvcrt) is imported at module level, so tests on the Mac can exercise the Windows paths.
Named "platforms" so it never shadows the standard library's platform module.

Windows-only pieces live next to this file: win_hid.py (the hidapi transport)."""
import contextlib
import os
import sys
import time

MAC, WINDOWS = "mac", "windows"
APP_NAME = "Huntsman for Mac"
_sleep = time.sleep      # tests replace it
LOCK_POLL = 0.01         # Windows: how often a blocking lock retries (msvcrt's own LK_LOCK gives up after 10 s)


def current():
    """MAC or WINDOWS. Anything that isn't Windows takes the Mac code paths (the only other platform supported)."""
    return WINDOWS if sys.platform == "win32" else MAC


def is_windows():
    return current() == WINDOWS


def is_mac():
    return current() == MAC


def info():
    """For the window: which platform, and whether the platform itself is experimental (Windows is)."""
    return {"platform": current(), "platform_experimental": is_windows()}


# ---------- folders ----------

def _win_folder(var, *fallback):
    return os.environ.get(var) or os.path.join(os.path.expanduser("~"), *fallback)


def data_dir():
    """Per-user settings folder (not created here: huntsman_core.data_dir does that)."""
    if is_windows():
        return os.path.join(_win_folder("APPDATA", "AppData", "Roaming"), APP_NAME)
    return os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_NAME)


def log_dir():
    if is_windows():
        return os.path.join(_win_folder("LOCALAPPDATA", "AppData", "Local"), APP_NAME, "Logs")
    return os.path.join(os.path.expanduser("~"), "Library", "Logs")


def log_path():
    return os.path.join(log_dir(), f"{APP_NAME}.log")


# ---------- locks ----------
# One exclusive lock per file, between processes: flock on the Mac, msvcrt.locking of byte 0 on Windows.

def _fd(f):
    return f if isinstance(f, int) else f.fileno()


def _win_try(fd):
    import msvcrt
    os.lseek(fd, 0, os.SEEK_SET)   # msvcrt locks from the current position; append mode starts at the end
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def lock_fd(f, blocking=True):
    """Take the exclusive lock on f (a file object or descriptor). Not blocking: BlockingIOError if it is held."""
    fd = _fd(f)
    if is_windows():
        while not _win_try(fd):
            if not blocking:
                raise BlockingIOError("the lock is held by another process")
            _sleep(LOCK_POLL)
        return
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))


def unlock_fd(f):
    fd = _fd(f)
    if is_windows():
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_UN)


def try_lock_fd(f):
    """True if the lock on f was taken now, False if another holder has it."""
    try:
        lock_fd(f, blocking=False)
        return True
    except OSError:   # BlockingIOError on both platforms
        return False


@contextlib.contextmanager
def file_lock(path):
    """Hold the exclusive lock on path (created if missing) for the body."""
    with open(path, "a") as f:
        lock_fd(f)
        try:
            yield f
        finally:
            try:
                unlock_fd(f)
            except OSError:
                pass   # closing the file releases it anyway
