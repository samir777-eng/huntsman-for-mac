# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The Mac installer (packaging/mac: PyInstaller spec, Info.plists, the .pkg's distribution, resources and
scripts), tools/build_mac_pkg.sh and .github/workflows/mac-build.yml. Nothing here builds or installs anything:
the pkg scripts run against a temporary home folder, with launchctl, the console user and the user switch replaced
by shell functions that only record what they were asked."""
import ast
import os
import pathlib
import plistlib
import re
import runpy
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import huntsman_core as hc  # noqa: E402
from platforms import bundle  # noqa: E402

MAC = ROOT / "packaging" / "mac"
SPEC = MAC / "huntsman-mac.spec"
PKG = MAC / "pkg"
SCRIPTS = PKG / "scripts"
BUILD = ROOT / "tools" / "build_mac_pkg.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "mac-build.yml"
LABEL = "io.github.huntsman-for-mac.lighting"
LIGHT_EXE = ("/Applications/Huntsman for Mac.app/Contents/Library/LoginItems/Huntsman Lighting.app/Contents/MacOS/"
             "HuntsmanLighting")


# ---------- requirements ----------

def _pins(path):
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def test_mac_build_requirements_pin_pyinstaller_and_libusb_on_top_of_the_app():
    lines = _pins(ROOT / "requirements-mac-build.txt")
    assert "-r requirements.txt" in lines
    pins = {ln.split("==")[0].lower(): ln for ln in lines if not ln.startswith("-r")}
    assert all("==" in ln for ln in pins.values()), "pin every build dependency exactly"
    assert {"pyinstaller", "pyinstaller-hooks-contrib", "libusb-package"} <= set(pins)


def test_windows_build_and_source_install_dont_get_the_mac_build_tools():
    for name in ("requirements.txt", "requirements-win.txt"):
        text = (ROOT / name).read_text(encoding="utf-8").lower()
        assert "libusb-package" not in text and "pyinstaller" not in text, name


def test_mac_and_windows_builds_pin_the_same_pyinstaller():
    mac = (ROOT / "requirements-mac-build.txt").read_text(encoding="utf-8").lower()
    win = (ROOT / ".github" / "workflows" / "windows-build.yml").read_text(encoding="utf-8").lower()
    for pkg in ("pyinstaller", "pyinstaller-hooks-contrib"):
        assert re.search(rf"^{pkg}==([\d.]+)$", mac, re.M).group(1) == re.search(rf"{pkg}==([\d.]+)", win).group(1)


# ---------- the Info.plists ----------

def _plists():
    return runpy.run_path(str(MAC / "plists.py"))


@pytest.mark.parametrize("name,bid,exe", [("Info.plist", "io.github.huntsman-for-mac", "HuntsmanForMac"),
                                          ("Lighting-Info.plist", LABEL, "HuntsmanLighting")])
def test_mac_info_plists_need_macos_14_and_carry_the_app_version(name, bid, exe):
    info = _plists()["mac_info"](name, hc.__version__)
    assert info["LSMinimumSystemVersion"] == "14.0"
    assert info["CFBundleIdentifier"] == bid and info["CFBundleExecutable"] == exe
    assert info["CFBundleShortVersionString"] == hc.__version__
    assert info["CFBundleVersion"].isdigit()
    assert info["NSInputMonitoringUsageDescription"] and info["NSMicrophoneUsageDescription"]
    with open(ROOT / "packaging" / name, "rb") as f:   # the source install's plist is left as it is
        assert plistlib.load(f)["LSMinimumSystemVersion"] == "12.0"


def test_both_bundles_share_one_build_number():
    p = _plists()
    assert p["mac_info"]("Info.plist", hc.__version__)["CFBundleVersion"] == \
        p["mac_info"]("Lighting-Info.plist", hc.__version__)["CFBundleVersion"]


def test_a_version_the_plists_dont_carry_stops_the_build():
    with pytest.raises(ValueError, match="CFBundleShortVersionString"):
        _plists()["mac_info"]("Info.plist", "9.9.9")


def test_the_service_bundle_is_a_menu_bar_agent():
    assert _plists()["mac_info"]("Lighting-Info.plist", hc.__version__)["LSUIElement"] is True


# ---------- the PyInstaller spec ----------

def _spec():
    return SPEC.read_text(encoding="utf-8")


def test_spec_builds_two_windowed_one_folder_apps_from_the_manifest():
    src = _spec()
    ast.parse(src)
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in src[:400]
    assert src.count("BUNDLE(") >= 1 and "COLLECT(" in src and "exclude_binaries=True" in src
    assert "console=False" in src and "upx=False" in src
    assert '"HuntsmanForMac"' in src and '"HuntsmanLighting"' in src
    assert '"Huntsman for Mac.app"' in src and '"Huntsman Lighting.app"' in src
    assert "app.py" in src and "service_entry.py" in src
    assert "bundle.mac_modules()" in src and "bundle.DATA" in src
    assert "mac_info(" in src and "huntsman_core.py" in src and "__version__" in src


def test_spec_bundles_libusb_from_the_wheel():
    src = _spec()
    assert "libusb_package" in src and "get_library_path" in src


def test_spec_builds_for_apple_silicon_only():
    assert re.search(r'target_arch\s*=\s*"arm64"', _spec())


def test_spec_leaves_out_the_windows_and_test_libraries():
    excludes = _spec().split("EXCLUDES")[1].split("]")[0]
    for mod in ("webview.platforms.winforms", "webview.platforms.edgechromium", "pythonnet", "clr_loader",
                "pystray", "hid", "pytest", "playwright"):
        assert f'"{mod}"' in excludes, mod


def test_spec_icon_exists():
    assert re.search(r'ICON\s*=\s*os\.path\.join\(ROOT,\s*"packaging",\s*"icon\.icns"\)', _spec())
    assert (ROOT / "packaging" / "icon.icns").is_file()


def test_the_service_entry_runs_the_service_or_the_smoke_test():
    src = (MAC / "service_entry.py").read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in src[:400]
    ns = runpy.run_path(str(MAC / "service_entry.py"), run_name="not_main")
    argv = ns["service_argv"]
    assert argv(["HuntsmanLighting"]) == ["HuntsmanLighting", "--service"]
    assert argv(["HuntsmanLighting", "-psn_0_1234"]) == ["HuntsmanLighting", "--service"]
    assert argv(["HuntsmanLighting", "--self-test"]) == ["HuntsmanLighting", "--self-test"]
    assert argv(["HuntsmanLighting", "--version"]) == ["HuntsmanLighting", "--version"]


# ---------- the .pkg: distribution and resources ----------

def _distribution():
    import xml.etree.ElementTree as ET
    return ET.parse(PKG / "distribution.xml").getroot()


def test_distribution_is_a_wizard_with_welcome_license_and_conclusion():
    d = _distribution()
    assert d.tag == "installer-gui-script"
    assert d.find("title").text == "Huntsman for Mac"
    assert d.find("welcome").get("file") == "welcome.html"
    assert d.find("license").get("file") == "LICENSE.txt"
    assert d.find("conclusion").get("file") == "conclusion.html"
    for f in ("welcome.html", "conclusion.html"):
        assert (PKG / "resources" / f).is_file()


def test_distribution_installs_for_apple_silicon_on_macos_14_into_the_system_volume():
    d = _distribution()
    opts = d.find("options")
    assert opts.get("hostArchitectures") == "arm64" and opts.get("customize") == "never"
    assert opts.get("rootVolumeOnly") == "true"
    dom = d.find("domains")
    assert dom.get("enable_localSystem") == "true"
    assert dom.get("enable_currentUserHome") == "false" and dom.get("enable_anywhere") == "false"
    assert d.find("volume-check/allowed-os-versions/os-version").get("min") == "14.0"
    ref = [r for r in d.iter("pkg-ref") if r.text]
    assert ref and ref[0].get("id") == "io.github.huntsman-for-mac.pkg" and ref[0].get("version") == "@VERSION@"


def test_licence_shown_is_the_repositorys_gpl_copied_at_build_time():
    assert not (PKG / "resources" / "LICENSE.txt").exists()     # never a stale copy in the repository
    sh = BUILD.read_text(encoding="utf-8")
    assert re.search(r'cp "\$ROOT/LICENSE" "[^"]*/LICENSE\.txt"', sh)
    assert "GNU GENERAL PUBLIC LICENSE" in (ROOT / "LICENSE").read_text(encoding="utf-8")[:200]


def test_welcome_and_conclusion_say_what_happens_in_plain_words():
    welcome = (PKG / "resources" / "welcome.html").read_text(encoding="utf-8")
    done = (PKG / "resources" / "conclusion.html").read_text(encoding="utf-8")
    assert "Applications" in welcome and "Not affiliated with" in welcome
    # the installed app isn't quarantined (it opened without a prompt on hardware, 2026-11-24): no Open Anyway here
    assert "Open Anyway" not in done and "Input Monitoring" in done and "Microphone" in done
    assert "Trash" in done                  # an install.sh copy is moved there
    assert "settings" in done.lower()


# ---------- the .pkg: scripts ----------

def _bash():
    return shutil.which("bash") or "/bin/bash"


HARNESS = r'''
set -u
source "$SCRIPT"
LOG="$WORK/calls.log"
console_user() { printf '%s\n' "${FAKE_USER-tester}"; }
user_uid() { printf '501\n'; }
user_home() { printf '%s\n' "$WORK/home"; }
_launchctl() { printf 'launchctl %s\n' "$*" >> "$LOG"; return "${FAKE_LAUNCHCTL_RC:-0}"; }
as_user() {
  printf 'as_user %s\n' "$*" >> "$LOG"
  # FAKE_TRASH_FAIL: moving into ~/.Trash is refused (as macOS privacy protection may do)
  if [ -n "${FAKE_TRASH_FAIL:-}" ] && [ "$1" = /bin/mv ] && [[ "$3" == */.Trash/* ]]; then return 1; fi
  "$@"
}
SYSTEM_APPS="$WORK/system-Applications"
_pkill() { printf 'pkill %s\n' "$*" >> "$LOG"; return 1; }
_pgrep() { return 1; }
_sleep() { :; }
_date() { printf '12.00.00\n'; }
main "$@"
'''


def _run_script(name, tmp_path, env=None):
    work = tmp_path
    (work / "home").mkdir(exist_ok=True)
    e = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "SCRIPT": str(SCRIPTS / name), "WORK": str(work), **(env or {})}
    r = subprocess.run([_bash(), "-c", HARNESS, "harness", str(tmp_path / "pkg"), "/", "/"], env=e,
                       capture_output=True, text=True, timeout=30)
    calls = (work / "calls.log").read_text().splitlines() if (work / "calls.log").exists() else []
    return r, calls


@pytest.mark.mac_only
@pytest.mark.parametrize("name", ["preinstall", "postinstall"])
def test_scripts_are_executable_bash_with_the_licence_header(name):
    p = SCRIPTS / name
    text = p.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/bash\n") and "SPDX-License-Identifier: GPL-3.0-or-later" in text[:400]
    assert os.access(p, os.X_OK)
    assert 'BASH_SOURCE[0]' in text   # main runs only when executed, so the tests can source it


@pytest.mark.mac_only
@pytest.mark.parametrize("name", ["preinstall", "postinstall", "../../../../tools/build_mac_pkg.sh"])
def test_shellcheck(name):
    sc = shutil.which("shellcheck")
    if not sc:
        pytest.skip("shellcheck isn't installed")
    r = subprocess.run([sc, "-x", str((SCRIPTS / name).resolve())], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


@pytest.mark.mac_only
def test_preinstall_stops_the_service_and_the_window_of_the_console_user(tmp_path):
    r, calls = _run_script("preinstall", tmp_path)
    assert r.returncode == 0, r.stderr
    assert calls[0] == f"launchctl bootout gui/501/{LABEL}"
    assert any(c.startswith("pkill -TERM -u 501 -x HuntsmanForMac") for c in calls)
    assert any(c.startswith("pkill -TERM -u 501 -f Contents/Resources/code/app.py") for c in calls)


@pytest.mark.mac_only
@pytest.mark.parametrize("user", ["", "root", "loginwindow"])
def test_preinstall_without_a_logged_in_user_does_nothing(tmp_path, user):
    r, calls = _run_script("preinstall", tmp_path, {"FAKE_USER": user})
    assert r.returncode == 0 and calls == []


@pytest.mark.mac_only
def test_preinstall_never_fails_the_install(tmp_path):
    r, _ = _run_script("preinstall", tmp_path, {"FAKE_LAUNCHCTL_RC": "3"})
    assert r.returncode == 0


def _old_copy(tmp_path):
    old = tmp_path / "home" / "Applications" / "Huntsman for Mac.app" / "Contents"
    old.mkdir(parents=True)
    (old / "Info.plist").write_text("old")
    return old.parent


@pytest.mark.mac_only
def test_postinstall_moves_the_install_sh_copy_to_the_users_trash(tmp_path):
    (tmp_path / "home").mkdir()
    old = _old_copy(tmp_path)
    r, calls = _run_script("postinstall", tmp_path)
    assert r.returncode == 0, r.stderr
    moved = tmp_path / "home" / ".Trash" / "Huntsman for Mac.app"
    assert not old.exists() and (moved / "Contents" / "Info.plist").read_text() == "old"
    assert any(c.startswith("as_user") for c in calls)     # moved as that user: the Trash item stays theirs
    assert moved.stat().st_uid == os.getuid()


@pytest.mark.mac_only
def test_postinstall_never_overwrites_something_already_in_the_trash(tmp_path):
    (tmp_path / "home").mkdir()
    _old_copy(tmp_path)
    trash = tmp_path / "home" / ".Trash"
    (trash / "Huntsman for Mac.app").mkdir(parents=True)
    (trash / "Huntsman for Mac.app" / "keep").write_text("earlier")
    r, _ = _run_script("postinstall", tmp_path)
    assert r.returncode == 0, r.stderr
    assert (trash / "Huntsman for Mac.app" / "keep").read_text() == "earlier"
    assert (trash / "Huntsman for Mac 12.00.00.app" / "Contents" / "Info.plist").read_text() == "old"


@pytest.mark.mac_only
def test_postinstall_leaves_a_symlink_in_applications_alone(tmp_path):
    (tmp_path / "home" / "Applications").mkdir(parents=True)
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "home" / "Applications" / "Huntsman for Mac.app"
    link.symlink_to(target)
    r, _ = _run_script("postinstall", tmp_path)
    assert r.returncode == 0 and link.is_symlink() and target.is_dir()


def _agent(tmp_path, args):
    a = tmp_path / "home" / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    a.parent.mkdir(parents=True)
    with open(a, "wb") as f:
        plistlib.dump({"Label": LABEL, "ProgramArguments": args, "RunAtLoad": True}, f)
    return a


@pytest.mark.mac_only
def test_postinstall_repoints_an_existing_agent_and_starts_it_again(tmp_path):
    (tmp_path / "home").mkdir()
    a = _agent(tmp_path, [str(tmp_path / "home/Applications/Huntsman for Mac.app/Contents/Library/LoginItems/"
                                         "Huntsman Lighting.app/Contents/MacOS/HuntsmanLighting")])
    r, calls = _run_script("postinstall", tmp_path)
    assert r.returncode == 0, r.stderr
    with open(a, "rb") as f:
        p = plistlib.load(f)
    assert p["ProgramArguments"] == [LIGHT_EXE]
    assert p["AssociatedBundleIdentifiers"] == ["io.github.huntsman-for-mac"]
    assert p["RunAtLoad"] is True and p["Label"] == LABEL                 # the rest is kept
    assert calls[-1] == f"launchctl bootstrap gui/501 {a}"


@pytest.mark.mac_only
def test_postinstall_on_a_fresh_mac_changes_nothing(tmp_path):
    (tmp_path / "home").mkdir()
    r, calls = _run_script("postinstall", tmp_path)
    assert r.returncode == 0, r.stderr
    assert calls == []
    assert not (tmp_path / "home" / "Library").exists() and not (tmp_path / "home" / ".Trash").exists()


@pytest.mark.mac_only
@pytest.mark.parametrize("user", ["", "root", "loginwindow"])
def test_postinstall_without_a_logged_in_user_does_nothing(tmp_path, user):
    (tmp_path / "home").mkdir()
    _old_copy(tmp_path)
    r, calls = _run_script("postinstall", tmp_path, {"FAKE_USER": user})
    assert r.returncode == 0 and calls == []
    assert (tmp_path / "home" / "Applications" / "Huntsman for Mac.app").is_dir()


@pytest.mark.mac_only
def test_postinstall_never_fails_the_install(tmp_path):
    (tmp_path / "home").mkdir()
    _agent(tmp_path, ["/old"])
    r, _ = _run_script("postinstall", tmp_path, {"FAKE_LAUNCHCTL_RC": "5"})
    assert r.returncode == 0


# ---------- tools/build_mac_pkg.sh ----------

def _build():
    return BUILD.read_text(encoding="utf-8")


def test_build_script_is_strict_bash_with_the_licence_header():
    sh = _build()
    assert sh.startswith("#!/bin/bash\n") and "SPDX-License-Identifier: GPL-3.0-or-later" in sh[:400]
    assert "set -euo pipefail" in sh
    assert os.access(BUILD, os.X_OK)


def test_build_script_nests_the_service_as_a_full_copy():
    sh = _build()
    assert "Contents/Library/LoginItems" in sh and "ditto" in sh
    assert "ln -s" not in sh                       # symlinked Frameworks break strict verification


def test_build_script_signs_inner_first_with_the_identity_or_ad_hoc():
    sh = _build()
    assert '"${HUNTSMAN_SIGN_IDENTITY:--}"' in sh
    inner, outer = sh.index('sign_bundle "$LIGHT"'), sh.index('sign_bundle "$APP"')
    assert inner < outer
    assert "codesign --verify --deep --strict" in sh


def test_build_script_smoke_tests_both_executables_before_packaging():
    sh = _build()
    st = sh.index("--self-test")
    assert "HuntsmanForMac" in sh and "HuntsmanLighting" in sh and sh.count("--self-test") >= 2
    assert st < sh.index("productbuild")
    assert "self-test passed" in sh


def test_build_script_makes_a_non_relocatable_versioned_pkg_in_dist():
    sh = _build()
    assert "pkgbuild --analyze" in sh and "BundleIsRelocatable bool false" in sh
    assert "--identifier io.github.huntsman-for-mac.pkg" in sh and "--install-location /" in sh
    assert '--scripts "$ROOT/packaging/mac/pkg/scripts"' in sh
    assert 'Huntsman-for-Mac-$VERSION.pkg' in sh and '$ROOT/dist' in sh
    assert "@VERSION@" in sh


def test_build_script_refuses_intel():
    assert 'uname -m' in _build() and "arm64" in _build()


# ---------- .github/workflows/mac-build.yml ----------

def _workflow():
    yaml = pytest.importorskip("yaml")
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in text[:400]
    wf = yaml.safe_load(text)
    wf["on"] = wf.get("on", wf.get(True))
    return wf, text


def test_mac_build_runs_on_a_github_hosted_arm64_runner_only():
    wf, text = _workflow()
    build = wf["jobs"]["build"]
    assert build["runs-on"] == "macos-15"
    assert "self-hosted" not in text and "RUNNER_LABELS" not in text
    assert "permissions" not in build and wf["permissions"] == {"contents": "read"}


def test_mac_build_triggers_like_the_windows_build():
    wf, _ = _workflow()
    on = wf["on"]
    assert "workflow_dispatch" in on and on["release"]["types"] == ["published"]
    paths = on["push"]["paths"]
    for p in ("packaging/mac/**", "platforms/**", "requirements*.txt", "tools/build_mac_pkg.sh",
              ".github/workflows/mac-build.yml", "app.py", "huntsman_core.py", "service.py", "depth_stream.py",
              "studio.py", "menubar.py", "ui/**"):
        assert p in paths, p
    assert "pull_request" not in on and "pull_request_target" not in on


def test_mac_build_installs_the_pinned_build_requirements_and_builds_with_the_script():
    _, text = _workflow()
    assert "requirements-mac-build.txt" in text and "tools/build_mac_pkg.sh" in text
    assert "3.13" in text


def test_mac_build_signs_with_the_secret_certificate_in_a_temporary_keychain_or_ad_hoc():
    wf, text = _workflow()
    steps = wf["jobs"]["build"]["steps"]
    (imp,) = [s for s in steps if "security import" in s.get("run", "")]
    assert imp["env"]["P12"] == "${{ secrets.MAC_SIGN_P12 }}"
    assert imp["env"]["P12_PASSWORD"] == "${{ secrets.MAC_SIGN_P12_PASSWORD }}"
    run = imp["run"]
    assert "security create-keychain" in run and "RUNNER_TEMP" in run
    assert 'if [ -z "$P12" ]' in run                          # no secret (forks): ad hoc
    assert "HUNTSMAN_SIGN_IDENTITY" in run and "GITHUB_ENV" in run
    cleanup = [s for s in steps if "security delete-keychain" in s.get("run", "")]
    assert cleanup and cleanup[0]["if"] == "always()"


def test_mac_build_installs_the_pkg_on_the_runner_and_self_tests_from_applications():
    wf, _ = _workflow()
    steps = wf["jobs"]["build"]["steps"]
    (inst,) = [s for s in steps if "sudo installer -pkg" in s.get("run", "")]
    run = inst["run"]
    assert "-target /" in run
    assert "/Applications/Huntsman for Mac.app/Contents/MacOS/HuntsmanForMac" in run
    assert "Huntsman Lighting.app/Contents/MacOS/HuntsmanLighting" in run
    assert run.count("--self-test") >= 2 and "self-test passed" in run
    names = [s.get("name", "") for s in steps]
    assert any(s.get("uses", "").startswith("actions/upload-artifact@") for s in steps)
    assert names.index(inst["name"]) < [i for i, s in enumerate(steps)
                                        if s.get("uses", "").startswith("actions/upload-artifact@")][0]


def test_mac_build_release_job_checks_the_tag_and_attaches_the_pkg():
    wf, _ = _workflow()
    release = wf["jobs"]["release"]
    assert release["needs"] == "build" and release["if"] == "github.event_name == 'release'"
    assert release["permissions"] == {"contents": "write"} and release["runs-on"] == "ubuntu-latest"
    (upload,) = [s for s in release["steps"] if "gh release upload" in s.get("run", "")]
    assert '"${TAG#v}" != "$VERSION"' in upload["run"] and "exit 1" in upload["run"]
    assert upload["env"]["TAG"] == "${{ github.event.release.tag_name }}"
    assert "gh release upload" not in str(wf["jobs"]["build"])


def test_mac_build_scripts_take_values_through_env_only():
    wf, _ = _workflow()
    for job in wf["jobs"].values():
        for st in job["steps"]:
            assert "${{" not in st.get("run", ""), st.get("name")


def test_mac_build_paths_exist():
    _, text = _workflow()
    for p in set(re.findall(r"(?<![\w./-])((?:requirements[\w-]*\.txt)|(?:packaging/[\w./-]+?)|(?:tools/[\w./-]+))"
                            r"(?=[\s\"'*]|$)", text)):
        p = p.rstrip("/")
        assert (ROOT / p).exists(), p


def test_the_manifest_still_imports_nothing():
    tree = ast.parse((ROOT / "platforms" / "bundle.py").read_text(encoding="utf-8"))
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert callable(bundle.mac_modules)


# ---------- uninstall.sh also removes the installed app ----------

def test_uninstall_sh_removes_the_pkg_install_too():
    sh = (ROOT / "uninstall.sh").read_text(encoding="utf-8")
    assert 'PKG_APP="/Applications/Huntsman for Mac.app"' in sh
    assert 'sudo /bin/rm -rf "$PKG_APP"' in sh
    assert "sudo /usr/sbin/pkgutil --forget io.github.huntsman-for-mac.pkg" in sh
    assert "pgrep -u \"$(id -u)\" -x HuntsmanForMac" in sh      # the installed app's window counts as running
    # the service is stopped before any app is removed
    assert sh.index("launchctl bootout") < sh.index('sudo /bin/rm -rf "$PKG_APP"')


@pytest.mark.mac_only
def test_postinstall_never_trashes_the_new_app_through_a_symlinked_applications_folder(tmp_path):
    """~/Applications -> /Applications: the "old copy" is the app just installed."""
    (tmp_path / "home").mkdir()
    system = tmp_path / "system-Applications"
    (system / "Huntsman for Mac.app" / "Contents").mkdir(parents=True)
    (tmp_path / "home" / "Applications").symlink_to(system)
    r, calls = _run_script("postinstall", tmp_path)
    assert r.returncode == 0, r.stderr
    assert (system / "Huntsman for Mac.app" / "Contents").is_dir()
    assert not (tmp_path / "home" / ".Trash").exists()
    assert not any("/bin/mv" in c for c in calls)


@pytest.mark.mac_only
def test_postinstall_never_trashes_the_new_app_when_it_is_the_same_file(tmp_path):
    """The copy in ~/Applications is the installed one by another route (-ef), without a symlinked folder."""
    (tmp_path / "home" / "Applications").mkdir(parents=True)
    system = tmp_path / "system-Applications"
    (system / "Huntsman for Mac.app" / "Contents").mkdir(parents=True)
    (tmp_path / "home" / "Applications" / "Huntsman for Mac.app").symlink_to(system / "Huntsman for Mac.app")
    r, calls = _run_script("postinstall", tmp_path)
    assert r.returncode == 0 and (system / "Huntsman for Mac.app" / "Contents").is_dir()
    assert not any("/bin/mv" in c for c in calls)


@pytest.mark.mac_only
def test_postinstall_renames_the_old_copy_when_the_trash_refuses_it(tmp_path):
    (tmp_path / "home").mkdir()
    old = _old_copy(tmp_path)
    r, calls = _run_script("postinstall", tmp_path, {"FAKE_TRASH_FAIL": "1"})
    assert r.returncode == 0, r.stderr
    renamed = tmp_path / "home" / "Applications" / "Huntsman for Mac (old).app"
    assert not old.exists() and (renamed / "Contents" / "Info.plist").read_text() == "old"
    moves = [c for c in calls if "/bin/mv" in c]
    assert len(moves) == 2 and "/.Trash/" in moves[0] and moves[1].endswith("Huntsman for Mac (old).app")


@pytest.mark.mac_only
def test_postinstall_rename_fallback_never_overwrites_an_earlier_old_copy(tmp_path):
    (tmp_path / "home").mkdir()
    _old_copy(tmp_path)
    earlier = tmp_path / "home" / "Applications" / "Huntsman for Mac (old).app"
    earlier.mkdir()
    (earlier / "keep").write_text("earlier")
    r, _ = _run_script("postinstall", tmp_path, {"FAKE_TRASH_FAIL": "1"})
    assert r.returncode == 0, r.stderr
    assert (earlier / "keep").read_text() == "earlier"
    second = tmp_path / "home" / "Applications" / "Huntsman for Mac (old) 12.00.00.app"
    assert (second / "Contents" / "Info.plist").read_text() == "old"
    assert not (tmp_path / "home" / "Applications" / "Huntsman for Mac.app").exists()


@pytest.mark.mac_only
def test_postinstall_moves_to_the_trash_when_it_can(tmp_path):
    (tmp_path / "home").mkdir()
    _old_copy(tmp_path)
    r, calls = _run_script("postinstall", tmp_path)
    assert r.returncode == 0
    assert [c for c in calls if "/bin/mv" in c][0].count("/.Trash/") == 1
    assert not (tmp_path / "home" / "Applications" / "Huntsman for Mac (old).app").exists()


# ---------- review: secrets only where signing happens ----------

def _steps():
    wf, _ = _workflow()
    return wf["jobs"]["build"]["steps"]


def _index(steps, pred):
    return next(i for i, s in enumerate(steps) if pred(s))


def test_mac_build_builds_with_no_secrets_then_signs_and_packages_in_a_later_step():
    steps = _steps()
    build = _index(steps, lambda s: "tools/build_mac_pkg.sh build" in s.get("run", ""))
    imp = _index(steps, lambda s: "security import" in s.get("run", ""))
    pkg = _index(steps, lambda s: "tools/build_mac_pkg.sh package" in s.get("run", ""))
    install = _index(steps, lambda s: "pip install" in s.get("run", ""))
    assert install < build < imp < pkg
    for st in steps[:imp]:          # pip install and PyInstaller never see the key
        assert "secrets." not in str(st.get("env", {})) and "secrets." not in str(st.get("with", {})), st.get("name")


def test_build_script_has_separate_build_and_package_phases():
    sh = _build()
    assert re.search(r"^\s*build\)", sh, re.M) and re.search(r"^\s*package\)", sh, re.M)
    body = sh.split("do_build()")[1].split("do_package()")[0]
    assert "PyInstaller" in body and "codesign" not in body and "HUNTSMAN_SIGN_IDENTITY" not in body


def test_a_release_without_the_signing_secret_fails_instead_of_shipping_ad_hoc():
    steps = _steps()
    (imp,) = [s for s in steps if "security import" in s.get("run", "")]
    assert imp["env"]["EVENT"] == "${{ github.event_name }}"
    run = imp["run"]
    no_secret = run.split('if [ -z "$P12" ]; then')[1].split("fi\n", 1)[0] + "fi"
    assert '"$EVENT" = "release"' in no_secret and "exit 1" in no_secret


def test_signing_keychain_is_cleaned_up_whatever_fails():
    (imp,) = [s for s in _steps() if "security import" in s.get("run", "")]
    run = imp["run"]
    created = run.index("security create-keychain")
    exported = run.index('echo "HUNTSMAN_SIGN_KEYCHAIN=$KC" >> "$GITHUB_ENV"')
    assert created < exported < run.index("security import")      # cleanup finds it even if the import fails
    assert re.search(r"trap 'rm -f[^']*sign\.p12[^']*' EXIT", run)
    assert "$(security list-keychains" not in run.replace('"$(security list-keychains', "")   # never unquoted
