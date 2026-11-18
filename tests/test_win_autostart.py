# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Start at login on Windows (platforms/win_autostart.py): the per-user HKCU Run value, written through a fake
winreg, and how the app starts the lighting service when it isn't running (no KeepAlive on Windows)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from platforms import win_autostart as wa  # noqa: E402

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


class FakeKey:
    def __init__(self, reg, path):
        self.reg, self.path = reg, path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.reg.closed += 1


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ, KEY_SET_VALUE, KEY_QUERY_VALUE = 0x20019, 0x0002, 0x0001
    REG_SZ, REG_DWORD = 1, 4

    def __init__(self, values=None):
        self.keys = {RUN: dict(values or {})}
        self.writes, self.closed = [], 0

    def OpenKey(self, root, path, reserved=0, access=0x20019):
        assert root == "HKCU"
        if path not in self.keys:
            raise FileNotFoundError(path)
        return FakeKey(self, path)

    def CreateKeyEx(self, root, path, reserved=0, access=0x20019):
        assert root == "HKCU"
        self.keys.setdefault(path, {})
        return FakeKey(self, path)

    def QueryValueEx(self, key, name):
        try:
            return self.keys[key.path][name]
        except KeyError:
            raise FileNotFoundError(name) from None

    def SetValueEx(self, key, name, reserved, kind, value):
        self.writes.append((key.path, name, kind, value))
        self.keys[key.path][name] = (value, kind)

    def DeleteValue(self, key, name):
        if name not in self.keys[key.path]:
            raise FileNotFoundError(name)
        del self.keys[key.path][name]


FROZEN = r"C:\Users\bob\Huntsman\Huntsman.exe"


def test_the_value_name_and_key():
    assert wa.RUN_KEY == RUN and wa.VALUE_NAME == "Huntsman for Mac lighting"


def test_the_frozen_command_line_quotes_the_exe_and_asks_for_the_service():
    assert wa.command_line(frozen=True, executable=FROZEN) == f'"{FROZEN}" --service'
    assert wa.service_argv(frozen=True, executable=FROZEN) == [FROZEN, "--service"]


def test_the_dev_command_line_runs_service_py_without_a_console_when_it_can():
    py, pyw = r"C:\Py\python.exe", r"C:\Py\pythonw.exe"
    script = r"C:\src\huntsman\service.py"
    assert wa.command_line(frozen=False, executable=py, script=script, exists=lambda p: p == pyw) \
        == f'"{pyw}" "{script}"'
    assert wa.command_line(frozen=False, executable=py, script=script, exists=lambda p: False) \
        == f'"{py}" "{script}"'
    assert wa.service_argv(frozen=False, executable=py, script=script, exists=lambda p: False) == [py, script]


def test_the_default_script_is_service_py_next_to_the_code():
    assert wa.default_script().endswith("service.py")
    assert os.path.exists(wa.default_script())


def test_enable_writes_the_run_value_once():
    reg = FakeWinreg()
    assert wa.enabled(winreg=reg) is False
    assert wa.enable(winreg=reg, command=f'"{FROZEN}" --service') is True
    assert reg.keys[RUN][wa.VALUE_NAME] == (f'"{FROZEN}" --service', reg.REG_SZ)
    assert wa.enabled(winreg=reg) is True
    assert wa.enable(winreg=reg, command=f'"{FROZEN}" --service') is False   # unchanged: nothing written
    assert len(reg.writes) == 1


def test_enable_rewrites_a_value_that_points_somewhere_else():
    reg = FakeWinreg({wa.VALUE_NAME: (r'"D:\old\Huntsman.exe" --service', 1)})
    assert wa.enable(winreg=reg, command=f'"{FROZEN}" --service') is True
    assert reg.keys[RUN][wa.VALUE_NAME][0] == f'"{FROZEN}" --service'


def test_other_run_values_are_left_alone():
    reg = FakeWinreg({"OneDrive": ("x", 1)})
    wa.enable(winreg=reg, command="c")
    wa.disable(winreg=reg)
    assert reg.keys[RUN] == {"OneDrive": ("x", 1)}


def test_disable_removes_the_value_and_is_safe_twice():
    reg = FakeWinreg({wa.VALUE_NAME: ("c", 1)})
    assert wa.disable(winreg=reg) is True
    assert wa.disable(winreg=reg) is False
    assert wa.enabled(winreg=reg) is False


def test_a_missing_run_key_is_created():
    reg = FakeWinreg()
    del reg.keys[RUN]
    assert wa.enabled(winreg=reg) is False
    wa.enable(winreg=reg, command="c")
    assert reg.keys[RUN][wa.VALUE_NAME] == ("c", 1)


def test_start_service_turns_start_at_login_on_and_starts_it_detached():
    reg, started = FakeWinreg(), []

    def popen(argv, **kw):
        started.append((argv, kw))
    wa.start_service(winreg=reg, popen=popen, frozen=True, executable=FROZEN)
    assert reg.keys[RUN][wa.VALUE_NAME][0] == f'"{FROZEN}" --service'
    (argv, kw), = started
    assert argv == [FROZEN, "--service"]
    flags = kw["creationflags"]
    assert flags & wa.CREATE_NO_WINDOW and flags & wa.DETACHED_PROCESS and flags & wa.CREATE_NEW_PROCESS_GROUP
    assert kw["close_fds"] is True and kw["stdin"] == kw["stdout"] == kw["stderr"] == wa.subprocess.DEVNULL


def test_start_service_still_starts_it_when_the_registry_refuses():
    class Refusing(FakeWinreg):
        def CreateKeyEx(self, *a, **kw):
            raise PermissionError("policy")
    started = []
    wa.start_service(winreg=Refusing(), popen=lambda argv, **kw: started.append(argv), frozen=True,
                     executable=FROZEN)
    assert started == [[FROZEN, "--service"]]


def test_the_app_opens_itself_the_same_way():
    assert wa.app_argv(frozen=True, executable=FROZEN) == [FROZEN]
    assert wa.app_argv(frozen=False, executable=r"C:\Py\python.exe", script=r"C:\src\app.py",
                       exists=lambda p: False) == [r"C:\Py\python.exe", r"C:\src\app.py"]


def test_the_module_imports_without_winreg():
    assert "winreg" not in sys.modules or sys.platform == "win32"
