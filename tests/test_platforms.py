# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The platform layer (platforms/): mac vs Windows selection, data and log folders, and file locks (fcntl on the
Mac, msvcrt.locking on Windows, here with a fake msvcrt). Windows-only modules must import on macOS: nothing
Windows-only (msvcrt, winreg, ctypes.windll, hid) is imported at module level. Nothing here opens USB or HID."""
import ast
import errno
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import platforms  # noqa: E402


# ---------- selection ----------

@pytest.mark.mac_only   # the real Mac host / fcntl
def test_mac_is_the_platform_here():
    assert sys.platform == "darwin"
    assert platforms.current() == platforms.MAC == "mac"
    assert platforms.is_windows() is False and platforms.is_mac() is True
    assert platforms.info() == {"platform": "mac", "platform_experimental": False}


def test_windows_is_selected_on_win32(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert platforms.current() == platforms.WINDOWS == "windows"
    assert platforms.is_windows() is True and platforms.is_mac() is False
    assert platforms.info() == {"platform": "windows", "platform_experimental": True}


def test_the_package_does_not_shadow_the_stdlib_platform_module():
    import platform
    assert hasattr(platform, "system") and platforms.__name__ == "platforms"


# ---------- folders ----------

@pytest.mark.mac_only   # POSIX paths
def test_mac_folders_are_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert platforms.data_dir() == str(tmp_path / "Library" / "Application Support" / "Huntsman for Mac")
    assert platforms.log_dir() == str(tmp_path / "Library" / "Logs")
    assert platforms.log_path() == str(tmp_path / "Library" / "Logs" / "Huntsman for Mac.log")


def test_windows_folders_use_appdata_and_localappdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert platforms.data_dir() == os.path.join(str(tmp_path / "Roaming"), "Huntsman for Mac")
    assert platforms.log_dir() == os.path.join(str(tmp_path / "Local"), "Huntsman for Mac", "Logs")
    assert platforms.log_path() == os.path.join(platforms.log_dir(), "Huntsman for Mac.log")


def test_windows_folders_without_the_variables_fall_back_to_the_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert platforms.data_dir() == os.path.join(str(tmp_path), "AppData", "Roaming", "Huntsman for Mac")
    assert platforms.log_dir() == os.path.join(str(tmp_path), "AppData", "Local", "Huntsman for Mac", "Logs")


def test_core_data_dir_creates_the_platform_folder(monkeypatch, tmp_path):
    import huntsman_core as hc
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    d = hc.data_dir()
    assert d == os.path.join(str(tmp_path), "Huntsman for Mac") and os.path.isdir(d)


# ---------- locks ----------

@pytest.mark.mac_only   # the real Mac host / fcntl
def test_mac_file_lock_is_an_flock(tmp_path):
    import fcntl
    path = str(tmp_path / "x.lock")
    with platforms.file_lock(path):
        with open(path, "a") as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with open(path, "a") as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_mac_try_lock_fd(tmp_path):
    path = str(tmp_path / "service.lock")
    a = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    b = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        assert platforms.try_lock_fd(a) is True
        assert platforms.try_lock_fd(b) is False
    finally:
        os.close(a)
    try:
        assert platforms.try_lock_fd(b) is True
    finally:
        os.close(b)


class FakeMsvcrt(types.ModuleType):
    """msvcrt.locking for one byte at offset 0, shared across descriptors of the same file (like Windows)."""
    LK_UNLCK, LK_LOCK, LK_NBLCK, LK_RLCK, LK_NBRLCK = 0, 1, 2, 3, 4

    def __init__(self):
        super().__init__("msvcrt")
        self.held, self.calls = {}, []

    def locking(self, fd, mode, nbytes):
        pos = os.lseek(fd, 0, os.SEEK_CUR)
        self.calls.append((mode, nbytes, pos))
        key = os.fstat(fd).st_ino
        if mode == self.LK_UNLCK:
            if self.held.get(key) != fd:
                raise OSError(errno.EACCES, "not locked")
            del self.held[key]
            return
        if mode == self.LK_LOCK:
            raise AssertionError("LK_LOCK gives up after 10 s; the code must poll LK_NBLCK instead")
        if key in self.held:
            raise OSError(errno.EDEADLK, "Resource deadlock avoided")
        self.held[key] = fd


@pytest.fixture
def win(monkeypatch):
    fake = FakeMsvcrt()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.delitem(sys.modules, "fcntl", raising=False)
    return fake


def test_windows_file_lock_uses_msvcrt_on_byte_zero(win, tmp_path):
    path = str(tmp_path / "usb.lock")
    with open(path, "w") as f:
        f.write("some text so the position is not 0")
    with platforms.file_lock(path):
        assert len(win.held) == 1
        fd = os.open(path, os.O_RDWR)
        try:
            assert platforms.try_lock_fd(fd) is False
        finally:
            os.close(fd)
    assert win.held == {}
    assert all(pos == 0 and n == 1 for _, n, pos in win.calls)
    assert win.calls[0][0] == win.LK_NBLCK and win.calls[-1][0] == win.LK_UNLCK


def test_windows_file_lock_waits_for_the_holder(win, tmp_path, monkeypatch):
    path = str(tmp_path / "state.lock")
    other = os.open(path, os.O_RDWR | os.O_CREAT)
    assert platforms.try_lock_fd(other) is True
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        if len(sleeps) == 3:   # the other process lets go
            platforms.unlock_fd(other)
    monkeypatch.setattr(platforms, "_sleep", sleep)
    try:
        with platforms.file_lock(path):
            assert len(sleeps) == 3
    finally:
        os.close(other)


def test_windows_instance_lock_in_the_service(win, tmp_path):
    import service
    path = str(tmp_path / "service.lock")
    fd = service.acquire_instance_lock(path)
    assert fd is not None
    try:
        assert service.acquire_instance_lock(path) is None
    finally:
        os.close(fd)


def test_set_experimental_and_update_state_lock_through_the_platform_layer(win, tmp_path, monkeypatch):
    import app as appmod
    import huntsman_core as hc
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(appmod, "STATE_FILE", str(tmp_path / "state.json"))
    hc.set_experimental(True)
    with appmod.update_state() as st:
        st["ui"] = {"accent": "#6ad7ff"}
    assert hc.experimental_enabled() is True and appmod.load_state()["ui"] == {"accent": "#6ad7ff"}
    assert win.calls and win.held == {}
    with hc.usb_lock():
        assert len(win.held) == 1
    assert win.held == {}


# ---------- Windows-only modules import on macOS ----------

WINDOWS_ONLY = {"msvcrt", "winreg", "_winapi", "hid", "pystray", "win32api", "win32con", "pywintypes"}
POSIX_ONLY = {"fcntl"}


def _module_level_imports(path):
    tree = ast.parse(open(path).read())
    out = set()
    for node in tree.body:   # only the module body: imports inside functions are lazy
        stmts = [node]
        if isinstance(node, (ast.If, ast.Try)):
            stmts = list(ast.walk(node))
        for n in stmts:
            if isinstance(n, ast.Import):
                out |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                out.add(n.module.split(".")[0])
    return out


@pytest.mark.parametrize("rel", ["huntsman_core.py", "ipc.py", "app.py", "service.py", "studio.py",
                                 "platforms/__init__.py", "platforms/win_hid.py"])
def test_shared_modules_import_nothing_platform_only_at_module_level(rel):
    bad = _module_level_imports(os.path.join(ROOT, rel)) & (WINDOWS_ONLY | POSIX_ONLY)
    assert not bad, f"{rel} imports {sorted(bad)} at module level; import it inside the function that needs it"


def test_windows_hid_module_imports_on_macos():
    import platforms.win_hid as w
    assert hasattr(w, "HidTransport")
