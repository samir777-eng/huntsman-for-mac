# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Checks on the repository itself: generated files are current and every source file has its licence header."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache"}


def test_demo_layout_matches_layout_json():
    spec = importlib.util.spec_from_file_location("make_demo_layout", ROOT / "tools" / "make_demo_layout.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)  # importing must not write anything
    with open(ROOT / "ui" / "demo-layout.js") as f:
        assert f.read() == tool.render(tool.read_layout()), "ui/demo-layout.js is stale: run python tools/make_demo_layout.py"


def test_every_source_file_has_a_licence_header():
    sources = [p for p in ROOT.rglob("*") if p.suffix in (".py", ".js", ".sh", ".html", ".css")
               and not any(d in SKIP_DIRS or d.endswith("_env") for d in p.relative_to(ROOT).parts)]
    assert len(sources) >= 14
    missing = [str(p.relative_to(ROOT)) for p in sources
               if "SPDX-License-Identifier: GPL-3.0-or-later" not in p.read_text()[:400]]
    assert missing == []


def test_demo_studio_matches_the_effect_library():
    spec = importlib.util.spec_from_file_location("make_demo_studio", ROOT / "tools" / "make_demo_studio.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    with open(ROOT / "ui" / "demo-studio.js") as f:
        assert f.read() == tool.render(tool.read_studio()), "ui/demo-studio.js is stale: run python tools/make_demo_studio.py"


def _install_sh():
    return (ROOT / "install.sh").read_text()


LABEL = "io.github.huntsman-for-mac.lighting"


def _uninstall_sh():
    return (ROOT / "uninstall.sh").read_text()


def test_install_writes_and_bootstraps_the_lighting_service_agent():
    sh = _install_sh()
    assert LABEL in sh
    assert "<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>" in sh
    assert "<key>RunAtLoad</key><true/>" in sh
    assert 'launchctl bootstrap "gui/$(id -u)" "$AGENT"' in sh       # lighting works right away


def test_install_builds_the_nested_lighting_app():
    sh = _install_sh()
    assert "Contents/Library/LoginItems/Huntsman Lighting.app" in sh
    assert "packaging/Lighting-Info.plist" in sh and "service.py" in sh and "ipc.py" in sh
    assert "HuntsmanLighting" in sh
    # the nested app is signed by the outer --deep ad-hoc signature, which comes after it is built
    assert sh.index("HuntsmanLighting\"") < sh.index("codesign --force --deep")


def test_install_removes_the_old_login_item():
    sh = _install_sh()
    assert "io.github.huntsman-for-mac.apply-saved" in sh
    assert 'launchctl bootout "gui/$(id -u)" "$OLD_AGENT"' in sh and '/bin/rm -f "$OLD_AGENT"' in sh


def test_install_stops_the_service_before_replacing_files():
    sh = _install_sh()
    stop = sh.index('launchctl bootout "gui/$(id -u)" "$AGENT"')
    assert stop < sh.index('mv "$APP" "$STASH/"')
    line = next(ln for ln in sh.splitlines() if "is running" in ln)
    assert "Quit it" in line


def test_lighting_info_plist_is_a_menu_bar_agent_with_a_microphone_reason():
    import plistlib
    with open(ROOT / "packaging" / "Lighting-Info.plist", "rb") as f:
        p = plistlib.load(f)
    assert p["CFBundleIdentifier"] == LABEL and p["LSUIElement"] is True
    assert p["CFBundleName"] == "Huntsman Lighting" and p["CFBundleExecutable"] == "HuntsmanLighting"
    assert p["NSMicrophoneUsageDescription"] and p["NSInputMonitoringUsageDescription"]


def test_uninstall_removes_the_service_agent_and_the_old_one():
    sh = _uninstall_sh()
    assert LABEL in sh and "io.github.huntsman-for-mac.apply-saved" in sh
    assert sh.count("launchctl bootout") >= 2
