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
HELPER = ROOT / "packaging" / "windows" / "setup-helper.ps1"
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
    install = re.search(r"procedure InstallWebView2;.*?\nend;", code, re.S).group(0)
    assert "RunHelper('webview2'" in install                  # through the helper: it has a time limit
    wv2 = _ps_function(_helper(), "webview2")
    assert "'/silent', '/install'" in wv2
    assert re.search(r"WaitForExit\((\d+)\)", wv2) and int(re.search(r"WaitForExit\((\d+)\)", wv2).group(1)) >= 300000
    assert "Stop-Process" in wv2 and "exit 1460" in wv2      # timed out: ended, ERROR_TIMEOUT
    assert "$null = $p.Handle" in wv2                        # PowerShell only keeps ExitCode with the handle open


def test_iss_records_what_microsoft_says_about_a_non_elevated_bootstrapper():
    """learn.microsoft.com/microsoft-edge/webview2/concepts/distribution: not elevated -> a per-user install."""
    text = _iss()
    assert "per-user" in text and "learn.microsoft.com/microsoft-edge/webview2/concepts/distribution" in text


def test_iss_webview2_log_lines_tell_a_failed_start_from_an_exit_code():
    install = re.search(r"procedure InstallWebView2;.*?\nend;", _code(), re.S).group(0)
    assert "SysErrorMessage(ResultCode)" in install           # Exec failed: a Win32 error, not an exit code
    assert "bootstrapper exit code %d" in install
    assert "'WebView2 Runtime installed'" in install
    assert "'WebView2 Runtime found: '" in _code()


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
    prepare = re.search(r"function PrepareToInstall\(.*?\nend;", code, re.S).group(0)
    assert "StopHuntsman(" in prepare
    uninstall = re.search(r"procedure CurUninstallStepChanged\(.*?\nend;", code, re.S).group(0)
    assert "usUninstall" in uninstall and "StopHuntsman(" in uninstall
    stop = re.search(r"function StopHuntsman\(.*?\nend;", code, re.S).group(0)
    assert "RunHelper('stop'" in stop
    s = _setup()
    assert s["closeapplications"] == "yes" and s["restartapplications"] == "no"


def test_helper_closes_the_window_before_quitting_the_service_then_ends_the_rest():
    """An open window (the Studio tab polls) could start the service again after --quit-service: windows go
    first, then the service is asked to quit (it restores the lighting), then whatever is left is ended."""
    stop = _ps_function(_helper(), "stop")
    close, quit_, kill = stop.index("CloseMainWindow"), stop.index("'--quit-service'"), stop.rindex("Stop-Process")
    assert close < quit_ < kill


def test_helper_matches_only_this_exact_exe():
    helper = _helper()
    assert "$_.ExecutablePath -eq $exe" in helper            # -eq on strings ignores case in PowerShell
    assert "StartsWith" not in helper and "-like" not in helper


def test_helper_takes_paths_hex_encoded_so_nothing_needs_quoting():
    """Paths (any character, an apostrophe in a user name too) reach the helper as hex digits of their UTF-16
    code units: nothing to quote, and unlike environment variables they survive ExecAsOriginalUser (the
    helper then runs in the original, non-elevated Setup process)."""
    helper, code = _helper(), _code()
    assert "ValidatePattern('^([0-9A-Fa-f]{4})*$')" in helper and "FromHex" in helper
    assert "$env:HUNTSMAN" not in helper and "SetEnvironmentVariable" not in code
    hexer = re.search(r"function Hex\(.*?\nend;", code, re.S).group(0)
    assert "Format('%.4x', [Ord(S[I])])" in hexer
    assert "PowerShellQuote" not in code and "-Command" not in code
    assert "-File" in code


def test_the_hex_encoding_round_trips():
    """The same encoding in Python: what the Pascal side writes, the PowerShell side reads back."""
    path = "C:\\Users\\O\u2019Brien \u00e9\\AppData\\Local\\Programs\\Huntsman for Mac\\Huntsman.exe"
    hexed = "".join(f"{ord(c):04X}" for c in path)
    assert re.fullmatch(r"([0-9A-Fa-f]{4})*", hexed)
    assert "".join(chr(int(hexed[i:i + 4], 16)) for i in range(0, len(hexed), 4)) == path


def test_helper_gives_an_old_exe_no_unknown_flag_and_never_waits_forever():
    """An exe older than 0.6.0 would open its window on --quit-service: only 0.6.0+ is asked, with a limit."""
    stop = _ps_function(_helper(), "stop")
    assert "[version]'0.6.0'" in stop
    quit_ = stop[stop.index("'--quit-service'"):]
    assert re.search(r"WaitForExit\(\d+\)", quit_) and "Stop-Process" in quit_


def test_helper_reports_whether_the_service_was_running():
    stop = _ps_function(_helper(), "stop")
    assert "--service" in stop and "exit 10" in stop
    assert "'lighting service was running: '" in stop          # a marker line the installer reads back
    stop_fn = re.search(r"function StopHuntsman\(.*?\nend;", _code(), re.S).group(0)
    assert "'lighting service was running: yes'" in stop_fn and "'lighting service was running: no'" in stop_fn


def test_iss_falls_back_to_quit_service_when_powershell_is_blocked():
    """AllSigned policy, Constrained Language Mode, no powershell.exe: the helper fails or answers oddly. The
    service is then still asked to quit directly (0.6.0+ only), and counted as running (restarted after)."""
    stop_fn = re.search(r"function StopHuntsman\(.*?\nend;", _code(), re.S).group(0)
    assert re.search(r"\(ResultCode = 0\) or \(ResultCode = ServiceWasRunningCode\)", stop_fn)
    assert "QuitServiceDirectly(" in stop_fn
    direct = re.search(r"procedure QuitServiceDirectly\(.*?\nend;", _code(), re.S).group(0)
    assert "KnowsQuitService(" in direct and "'--quit-service'" in direct
    knows = re.search(r"function KnowsQuitService\(.*?\nend;", _code(), re.S).group(0)
    assert "GetVersionNumbers(" in knows and "shr 16" in knows and ">= 6" in knows
    assert re.search(r"Result := True;\s*\{ unknown", stop_fn)   # unknown counts as running


def test_iss_runs_the_helper_and_the_service_as_the_original_user():
    """Setup run as administrator: a service (or a --quit-service) started elevated would lock the normal window
    out of its pipe."""
    code = _code()
    run_as_user = re.search(r"function RunAsUser\(.*?\nend;", code, re.S).group(0)
    assert "ExecAsOriginalUser(" in run_as_user and "IsUninstaller" in run_as_user
    helper = re.search(r"function RunHelper\(.*?\nend;", code, re.S).group(0)
    assert "RunAsUser(" in helper
    start = re.search(r"procedure StartService;.*?\nend;", code, re.S).group(0)
    assert "ExecAsOriginalUser(ExpandConstant('{app}\\Huntsman.exe'), '--service', ExpandConstant('{app}')" in start
    assert "ewNoWait" in start


def test_iss_moves_a_zip_copys_service_over_to_the_installed_one():
    """The Run value starts another copy (an unzipped one): that copy is stopped and the installed service
    started; the installed service's ensure_autostart then points the Run value at itself."""
    code = _code()
    post = re.search(r"procedure CurStepChanged\(.*?\nend;", code, re.S).group(0)
    assert "OtherCopyInRunValue(" in post and "StartService" in post
    other = re.search(r"function OtherCopyInRunValue\(.*?\nend;", code, re.S).group(0)
    assert "RegQueryStringValue(HKCU, RunKey, RunValue" in other and "Huntsman.exe" in other
    src = (ROOT / "service.py").read_text(encoding="utf-8")
    body = src[src.index("def _main_windows"):]
    assert "ensure_autostart()" in body.split("menu.run(")[0]   # the service itself repoints the Run value


def test_iss_restarts_the_service_after_an_upgrade_only_if_it_was_running():
    code = _code()
    post = re.search(r"procedure CurStepChanged\(.*?\nend;", code, re.S).group(0)
    assert "ssPostInstall" in post and re.search(r"if ServiceWasRunning or Migrated then", post)
    assert "StartService" in post


def test_helper_cannot_hang_on_wmi():
    for line in _helper().splitlines():
        if "Get-CimInstance" in line:
            assert re.search(r"-OperationTimeoutSec \d+", line), line


def test_helper_is_ascii_and_licensed():
    text = _helper()
    text.encode("ascii")
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in text[:400]
    assert re.search(r"ValidateSet\('stop', 'webview2'\)", text)


def test_iss_installs_the_helper_and_extracts_it_for_an_upgrade():
    sec = _sections(_iss())
    (line,) = [ln for ln in sec["files"] if "setup-helper.ps1" in ln]
    assert 'DestDir: "{app}"' in line and "dontcopy" not in line   # the uninstaller uses the installed copy
    assert "ExtractTemporaryFile('setup-helper.ps1')" in _code()


def test_iss_uninstall_removes_the_run_value_and_keeps_the_settings():
    code = _code()
    assert f"'{win_autostart.VALUE_NAME}'" in code
    assert f"'{win_autostart.RUN_KEY}'" in code
    uninstall = re.search(r"procedure CurUninstallStepChanged\(.*?\nend;", code, re.S).group(0)
    assert "'--remove-autostart'" in uninstall
    assert re.search(r"RegDeleteValue\(HKCU,\s*RunKey,\s*RunValue\)", uninstall)
    # only a value that starts this exact exe: '"<app>\Huntsman.exe"' at the very start
    assert "'\"' + ExpandConstant('{app}\\Huntsman.exe') + '\"'" in uninstall
    assert re.search(r"Pos\(Lowercase\(Ours\), Lowercase\(Value\)\) = 1", uninstall)
    text = _iss().lower()
    assert "{userappdata}" not in text and "{appdata}" not in text and "delaftreeroot" not in text
    sec = _sections(_iss())
    assert "uninstalldelete" not in sec
    assert any("ConfirmUninstall" in ln and "kept" in ln for ln in sec["messages"])


def _helper():
    return HELPER.read_text(encoding="utf-8")


def _ps_function(text, name):
    """The body of a PowerShell `if ($Action -eq 'name')` block or function, up to the next top-level block."""
    m = re.search(rf"^if \(\$Action -eq '{name}'\) \{{\n(.*?)^\}}", text, re.S | re.M)
    assert m, name
    return m.group(1)


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
    for p in ("app.py", "service.py", "ipc.py", "platforms/**", "huntsman_core.py", "studio.py", "lighting/**",
              "models.py", "depth_stream.py", "ui/**", "tests/test_win_installer.py", "layouts/**", "layout.json",
              "keymap.json", "inputs/**", "menubar.py"):   # what goes into the build and what the installer runs
        assert p in paths, p
        assert (ROOT / p.split("/")[0]).exists(), p


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
    assert "choco list innosetup --exact" in inno["run"] and "$got -ne $pin" in inno["run"]   # the pinned one is used
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
    assert '"WebView2 Runtime (found|installed)' in run          # the exact log line, not just the words
    assert service.QUIT_LOG in run                              # the service logged the quit (restore)
    assert "autostart_added" in run                             # reset by --remove-autostart
    assert "function StartWindow" in run                        # an open window is stopped too
    assert "service didn't come up" in run and "::warning::the lighting service" not in run
    assert "restarted after the upgrade" in run and "not started by the install" in run
    assert "HuntsmanZip" in run and "zip copy's service is still running" in run   # moving from the zip
    assert "Run value doesn't start the installed copy" in run
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
