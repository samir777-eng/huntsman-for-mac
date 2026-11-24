# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The Windows installer wizard (packaging/windows/huntsman.iss, Inno Setup), its build and smoke test in
.github/workflows/windows-build.yml, and the two commands the installer runs: `Huntsman.exe --quit-service` (asks a
running lighting service to quit over its IPC, so it restores the keyboard's lighting, and waits until it is gone)
and `Huntsman.exe --remove-autostart` (uninstall: removes the HKCU Run value when it starts this copy). Static checks
and fakes only: nothing here compiles the installer, opens the keyboard or touches the real registry. The real
compile and the silent install/uninstall run in the Windows build workflow."""
import os
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import huntsman_core as hc  # noqa: E402
import ipc  # noqa: E402
import service  # noqa: E402
from platforms import win_autostart  # noqa: E402
from test_win_autostart import RUN, FakeWinreg  # noqa: E402

ISS = ROOT / "packaging" / "windows" / "huntsman.iss"
WORKFLOW = ROOT / ".github" / "workflows" / "windows-build.yml"
WEBVIEW2_CLIENT = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
EXE = r"C:\Users\bob\AppData\Local\Programs\Huntsman for Mac\Huntsman.exe"
OURS = f'"{EXE}" --service'


# ---------- the .iss script ----------

def _iss():
    return ISS.read_text(encoding="utf-8")


def _sections(text):
    """{section name (lower case): [lines]} without comments and blank lines; [Code] kept whole."""
    out, name = {}, None
    for line in text.splitlines():
        m = re.match(r"^\[(\w+)\]\s*$", line.strip())
        if m:
            name = m.group(1).lower()
            out.setdefault(name, [])
            continue
        if name is None or (name != "code" and (not line.strip() or line.strip().startswith(";"))):
            continue
        out[name].append(line)
    return out


def _setup():
    d = {}
    for line in _sections(_iss())["setup"]:
        k, _, v = line.partition("=")
        d[k.strip().lower()] = v.strip()
    return d


def _code():
    return "\n".join(_sections(_iss())["code"])


def test_iss_exists_and_carries_the_licence_header():
    text = _iss()
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in text[:400]
    assert {"setup", "files", "icons", "run", "code"} <= set(_sections(text))


def test_iss_has_a_fixed_appid_guid():
    """Upgrades replace the same install only while AppId never changes: a literal GUID, not a define."""
    appid = _setup()["appid"]
    assert re.fullmatch(r"\{\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}", appid), appid


def test_iss_installs_per_user_without_admin():
    s = _setup()
    assert s["privilegesrequired"] == "lowest"
    assert "privilegesrequiredoverridesallowed" not in s      # no "install for all users" choice
    assert s["defaultdirname"] == r"{localappdata}\Programs\Huntsman for Mac"
    for line in _sections(_iss())["registry"] if "registry" in _sections(_iss()) else []:
        assert "HKLM" not in line


def test_iss_takes_the_version_from_the_build_and_refuses_to_compile_without_it():
    text = _iss()
    assert re.search(r"#ifndef AppVersion\s+#error", text)
    s = _setup()
    assert s["appversion"] == "{#AppVersion}"
    assert s["outputbasefilename"] == "Huntsman-for-Windows-{#AppVersion}-Setup"
    assert "{#AppVersion}" in s["versioninfoversion"]


def test_iss_is_x64_only_and_needs_windows_10():
    s = _setup()
    assert s["architecturesallowed"] == "x64compatible"
    assert s["architecturesinstallin64bitmode"] == "x64compatible"
    assert s["minversion"] == "10.0"


def test_iss_wizard_pages_welcome_license_folder_finish():
    s = _setup()
    assert s["licensefile"].replace("\\", "/").endswith("LICENSE")
    assert (ISS.parent / s["licensefile"].replace("\\", "/")).resolve() == (ROOT / "LICENSE")
    assert s["disablewelcomepage"] == "no"                     # Inno Setup 6 hides it by default
    assert s.get("disabledirpage", "auto") in ("auto", "no")
    assert s["wizardstyle"] == "modern"
    assert (ISS.parent / s["setupiconfile"]).resolve() == (ISS.parent / "icon.ico").resolve()


def test_iss_installs_the_whole_pyinstaller_folder():
    (files,) = [ln for ln in _sections(_iss())["files"] if "dist" in ln and "Huntsman" in ln]
    assert r"dist\Huntsman\*" in files and "recursesubdirs" in files and 'DestDir: "{app}"' in files


def test_iss_start_menu_shortcut_and_an_optional_desktop_icon_off_by_default():
    sec = _sections(_iss())
    (task,) = [ln for ln in sec["tasks"] if "desktopicon" in ln]
    assert "unchecked" in task
    icons = sec["icons"]
    assert any("{autoprograms}" in ln and r"{app}\Huntsman.exe" in ln for ln in icons)
    (desk,) = [ln for ln in icons if "{autodesktop}" in ln]
    assert "Tasks: desktopicon" in desk


def test_iss_finish_page_offers_to_open_the_app_but_not_when_silent():
    (run,) = [ln for ln in _sections(_iss())["run"] if r"{app}\Huntsman.exe" in ln]
    assert 'Description: "Open Huntsman for Mac"' in run
    assert "postinstall" in run and "skipifsilent" in run and "nowait" in run


def test_iss_bundles_the_webview2_bootstrapper_only_as_a_temporary_file():
    sec = _sections(_iss())
    (bootstrap,) = [ln for ln in sec["files"] if "MicrosoftEdgeWebview2Setup.exe" in ln or "WebView2Bootstrapper" in ln]
    assert "dontcopy" in bootstrap                             # extracted to {tmp} only when it is needed
    code = _code()
    assert "ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe')" in code
    assert "'/silent /install'" in code


def test_iss_checks_webview2_in_both_registry_places_before_running_the_bootstrapper():
    code = _code()
    assert code.count(WEBVIEW2_CLIENT) == 1                    # one constant, used for both hives
    assert re.search(r"HKLM\s*,\s*'SOFTWARE\\WOW6432Node\\'", code)
    assert re.search(r"HKCU\s*,\s*'Software\\'", code)
    assert "'pv'" in code and "'0.0.0.0'" in code
    install = re.search(r"procedure InstallWebView2;.*?\nend;", code, re.S).group(0)
    assert re.search(r"if WebView2Installed then\s+Exit;", install)


def test_iss_a_failed_webview2_install_does_not_fail_the_install():
    code = _code()
    install = re.search(r"procedure InstallWebView2;.*?\nend;", code, re.S).group(0)
    assert "RaiseException" not in install and "Abort" not in install
    assert "WebView2Failed := True" in install
    assert re.search(r"wpFinished.*WebView2Failed", code, re.S)   # the Finish page says how to get it


def test_iss_stops_the_running_copy_before_install_and_before_uninstall():
    code = _code()
    assert "'--quit-service'" in code
    prepare = re.search(r"function PrepareToInstall\(.*?\nend;", code, re.S).group(0)
    assert "StopHuntsman(" in prepare
    uninstall = re.search(r"procedure CurUninstallStepChanged\(.*?\nend;", code, re.S).group(0)
    assert "usUninstall" in uninstall and "StopHuntsman(" in uninstall
    stop = re.search(r"procedure StopHuntsman\(.*?\nend;", code, re.S).group(0)
    assert "CloseMainWindow" in stop and "Stop-Process" in stop   # then the window, then what is left
    assert "OrdinalIgnoreCase" in stop                             # only processes in this install's folder
    s = _setup()
    assert s["closeapplications"] == "yes" and s["restartapplications"] == "no"


def test_iss_uninstall_removes_the_run_value_and_keeps_the_settings():
    code = _code()
    assert f"'{win_autostart.VALUE_NAME}'" in code
    assert f"'{win_autostart.RUN_KEY}'" in code
    uninstall = re.search(r"procedure CurUninstallStepChanged\(.*?\nend;", code, re.S).group(0)
    assert "'--remove-autostart'" in uninstall
    assert re.search(r"RegDeleteValue\(HKCU,\s*RunKey,\s*RunValue\)", uninstall)
    text = _iss().lower()
    assert "{userappdata}" not in text and "{appdata}" not in text and "delaftreeroot" not in text
    sec = _sections(_iss())
    assert "uninstalldelete" not in sec
    assert any("ConfirmUninstall" in ln and "kept" in ln for ln in sec["messages"])


def test_iss_is_plain_ascii():
    """Inno Setup reads a script without a BOM as ANSI: keep it ASCII so no text is garbled."""
    _iss().encode("ascii")


# ---------- the workflow ----------

def _wf():
    yaml = pytest.importorskip("yaml")
    text = WORKFLOW.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    wf["on"] = wf.get("on", wf.get(True))
    return wf, text


def _steps():
    wf, _ = _wf()
    return wf["jobs"]["build"]["steps"]


def _step(pred):
    (st,) = [s for s in _steps() if pred(s)]
    return st


def _index(pred):
    (i,) = [i for i, s in enumerate(_steps()) if pred(s)]
    return i


def test_workflow_builds_on_github_hosted_runners_only():
    wf, text = _wf()
    for job in wf["jobs"].values():
        assert job["runs-on"] in ("windows-latest", "ubuntu-latest"), job["runs-on"]
    assert "self-hosted" not in text and "RUNNER_LABELS" not in text


def test_workflow_runs_when_the_installer_changes():
    wf, _ = _wf()
    paths = wf["on"]["push"]["paths"]
    assert "packaging/windows/**" in paths


def test_workflow_downloads_the_webview2_bootstrapper_and_never_commits_it():
    st = _step(lambda s: "MicrosoftEdgeWebview2Setup.exe" in s.get("run", ""))
    assert "https://go.microsoft.com/fwlink/p/?LinkId=2124703" in st["run"]
    assert not list(ROOT.rglob("MicrosoftEdgeWebview2Setup.exe"))
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "MicrosoftEdgeWebview2Setup.exe" in ignore
    # it is a Microsoft-signed file: the download is checked before it goes into the installer
    assert "Get-AuthenticodeSignature" in st["run"] and "Microsoft Corporation" in st["run"]


def test_workflow_compiles_with_a_pinned_inno_setup_after_the_zip():
    inno = _step(lambda s: "innosetup" in s.get("run", "").lower() and "choco" in s.get("run", ""))
    pin = re.search(r'\$pin = "(\d+\.\d+\.\d+)"', inno["run"])
    assert pin and "innosetup --version $pin" in inno["run"]
    assert "-like \"$pin*\"" in inno["run"]                     # the compiler used is the pinned one
    compile_ = _step(lambda s: "ISCC" in s.get("run", "") and "huntsman.iss" in s.get("run", ""))
    assert "/DAppVersion=" in compile_["run"]
    assert "VERSION" in compile_.get("env", {})
    assert _index(lambda s: "Compress-Archive" in s.get("run", "")) < _index(lambda s: s == compile_)
    assert _index(lambda s: "pyinstaller --noconfirm" in s.get("run", "")) < _index(lambda s: s == compile_)


def test_workflow_smoke_tests_a_silent_install_and_uninstall():
    st = _step(lambda s: "/VERYSILENT" in s.get("run", ""))
    run = st["run"]
    assert "/SUPPRESSMSGBOXES" in run and "/NORESTART" in run
    assert "--version" in run and "--self-test" in run
    assert r"Programs\Huntsman for Mac" in run
    assert "unins000.exe" in run
    assert "--service" in run and "(Ours).Count" in run          # a running service is stopped, not left behind
    assert win_autostart.VALUE_NAME in run                      # written as the app would, then gone after
    assert "APPDATA" in run                                     # the settings folder survives the uninstall
    assert "throw" in run


def test_workflow_keeps_the_zip_and_uploads_the_setup_exe():
    _wf_, text = _wf()
    assert "Compress-Archive -Path dist\\Huntsman -DestinationPath $zip" in text
    uploads = [s for s in _steps() if s.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(uploads) == 2
    assert any("-Setup" in u["with"]["name"] for u in uploads)


def test_release_attaches_the_setup_exe_next_to_the_zip_with_the_tag_check():
    wf, _ = _wf()
    release = wf["jobs"]["release"]
    assert release["runs-on"] == "ubuntu-latest"
    downloads = [s for s in release["steps"] if s.get("uses", "").startswith("actions/download-artifact@")]
    assert len(downloads) == 2
    (upload,) = [s for s in release["steps"] if "gh release upload" in s.get("run", "")]
    assert '"${TAG#v}" != "$VERSION"' in upload["run"]
    assert '"$ZIP"' in upload["run"] and '"$SETUP"' in upload["run"]
    assert upload["env"]["SETUP"] == "${{ needs.build.outputs.setup }}"
    assert wf["jobs"]["build"]["outputs"]["setup"]


# ---------- the lighting service's "quit" command ----------

def test_the_service_accepts_quit_over_ipc():
    assert service.SPECS["quit"] == {}


def test_quit_calls_the_tray_quit_and_answers_at_once_even_while_starting():
    s = service.LightingService()                 # never started: no START_WAIT for quit
    quits = []
    s.on_quit(lambda: quits.append(1))
    assert s.handle("quit", {}) == {"ok": True, "data": True}
    assert quits == [1]


def test_quit_without_a_quit_hook_says_so():
    s = service.LightingService()
    r = s.handle("quit", {})
    assert r["ok"] is False and "quit" in r["error"]


# ---------- Huntsman.exe --quit-service ----------

class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, dt):
        self.t += dt


def test_quit_service_asks_and_waits_until_the_service_is_gone():
    clock, asked = Clock(), []
    gone_after = iter([False, False, True])
    rc = app.stop_running_service(request=lambda: asked.append("quit") or {"ok": True, "data": True},
                                  stopped=lambda: next(gone_after), clock=clock, sleep=clock.sleep,
                                  out=lambda line: None)
    assert rc == 0 and asked == ["quit"]


def test_quit_service_when_nothing_is_running_is_a_success():
    def unavailable():
        raise ipc.ServiceUnavailable("no pipe")
    clock = Clock()
    assert app.stop_running_service(request=unavailable, stopped=lambda: True, clock=clock,
                                    sleep=clock.sleep, out=lambda line: None) == 0


@pytest.mark.parametrize("error", [ipc.ProtocolError("bad"), EOFError(), OSError("pipe closed")])
def test_quit_service_still_waits_when_the_reply_is_lost(error):
    """The service may close its server before the reply goes out: still wait for it to be gone."""
    def lost():
        raise error
    clock, checks = Clock(), []

    def stopped():
        checks.append(1)
        return len(checks) > 2
    assert app.stop_running_service(request=lost, stopped=stopped, clock=clock, sleep=clock.sleep,
                                    out=lambda line: None) == 0


def test_quit_service_gives_up_after_the_wait_and_says_so():
    clock, lines = Clock(), []
    rc = app.stop_running_service(request=lambda: {"ok": True, "data": True}, stopped=lambda: False,
                                  wait=3.0, clock=clock, sleep=clock.sleep, out=lines.append)
    assert rc == 1 and 3.0 <= clock.t < 3.5
    assert any("still running" in ln for ln in lines)


def test_quit_service_waits_longer_than_the_service_takes_to_restore_the_lighting():
    import depth_stream
    assert app.QUIT_WAIT > depth_stream.SHUTDOWN_LIMIT + ipc.TIMEOUT


def test_the_service_counts_as_stopped_once_its_instance_lock_is_free(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "lock_path", lambda: str(tmp_path / "service.lock"))
    assert app.service_stopped() is True                 # free: taken and given back at once
    assert app.service_stopped() is True
    fd = service.acquire_instance_lock(str(tmp_path / "service.lock"))   # as the running service holds it
    assert fd is not None
    try:
        assert app.service_stopped() is False
    finally:
        app.platforms.unlock_fd(fd)   # Windows may release a closed handle's lock late
        os.close(fd)
    assert app.service_stopped() is True


def test_service_stopped_with_no_data_folder_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "lock_path", lambda: str(tmp_path / "missing" / "service.lock"))
    assert app.service_stopped() is True
    assert not (tmp_path / "missing").exists()           # nothing created in %APPDATA% by asking


def test_entry_quit_service_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(app, "stop_running_service", lambda: calls.append("quit") or 0)
    monkeypatch.setattr(app, "main", lambda: pytest.fail("the window must not open"))
    import service as svc_mod
    monkeypatch.setattr(svc_mod, "main", lambda: pytest.fail("the service must not start"))
    assert app.entry(["Huntsman.exe", "--quit-service"]) == 0
    assert calls == ["quit"]


# ---------- Huntsman.exe --remove-autostart ----------

def test_remove_if_ours_deletes_only_a_value_that_starts_this_copy():
    reg = FakeWinreg({win_autostart.VALUE_NAME: (OURS, 1), "Other": ("x", 1)})
    assert win_autostart.remove_if_ours(OURS, winreg=reg) == "removed"
    assert win_autostart.VALUE_NAME not in reg.keys[RUN] and "Other" in reg.keys[RUN]
    assert win_autostart.remove_if_ours(OURS, winreg=reg) == "absent"


def test_remove_if_ours_ignores_case_in_the_path():
    reg = FakeWinreg({win_autostart.VALUE_NAME: (OURS.lower(), 1)})
    assert win_autostart.remove_if_ours(OURS, winreg=reg) == "removed"


def test_remove_if_ours_leaves_another_copy_alone():
    other = r'"D:\Portable\Huntsman\Huntsman.exe" --service'
    reg = FakeWinreg({win_autostart.VALUE_NAME: (other, 1)})
    assert win_autostart.remove_if_ours(OURS, winreg=reg) == "other"
    assert reg.keys[RUN][win_autostart.VALUE_NAME] == (other, 1)


@pytest.fixture
def windows_state(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(app, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(win_autostart, "command_line", lambda *a, **k: OURS)
    return tmp_path


def test_remove_autostart_removes_our_value_and_forgets_it_was_added(windows_state, monkeypatch):
    """So a later reinstall turns start at login on again, as a first run does."""
    monkeypatch.setattr(app.platforms, "lock_fd", lambda f, blocking=True: None)
    monkeypatch.setattr(app.platforms, "unlock_fd", lambda f: None)
    with app.update_state() as st:
        st["autostart_added"] = True
        st["experimental"] = True
    reg = FakeWinreg({win_autostart.VALUE_NAME: (OURS, 1)})
    assert app.remove_autostart(winreg=reg) == 0
    assert win_autostart.VALUE_NAME not in reg.keys[RUN]
    st = app.load_state()
    assert st["autostart_added"] is False and st["experimental"] is True   # the rest of the settings kept


def test_remove_autostart_leaves_another_copys_value_and_its_flag(windows_state, monkeypatch):
    monkeypatch.setattr(app.platforms, "lock_fd", lambda f, blocking=True: None)
    monkeypatch.setattr(app.platforms, "unlock_fd", lambda f: None)
    with app.update_state() as st:
        st["autostart_added"] = True
    other = r'"D:\Portable\Huntsman\Huntsman.exe" --service'
    reg = FakeWinreg({win_autostart.VALUE_NAME: (other, 1)})
    assert app.remove_autostart(winreg=reg) == 0
    assert reg.keys[RUN][win_autostart.VALUE_NAME] == (other, 1)
    assert app.load_state()["autostart_added"] is True


def test_remove_autostart_creates_no_settings_file(windows_state):
    reg = FakeWinreg({win_autostart.VALUE_NAME: (OURS, 1)})
    assert app.remove_autostart(winreg=reg) == 0
    assert not (windows_state / "state.json").exists()
    assert win_autostart.VALUE_NAME not in reg.keys[RUN]


def test_remove_autostart_does_nothing_on_the_mac(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(app.platforms, "current", lambda: app.platforms.MAC)
    reg = FakeWinreg({win_autostart.VALUE_NAME: (OURS, 1)})
    assert app.remove_autostart(winreg=reg) == 0
    assert win_autostart.VALUE_NAME in reg.keys[RUN]


def test_entry_remove_autostart_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(app, "remove_autostart", lambda: calls.append("remove") or 0)
    monkeypatch.setattr(app, "main", lambda: pytest.fail("the window must not open"))
    assert app.entry(["Huntsman.exe", "--remove-autostart"]) == 0
    assert calls == ["remove"]
