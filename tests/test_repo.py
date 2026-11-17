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


def test_install_does_not_start_the_app_hidden():
    # A bootstrapped RunAtLoad agent would launch the app hidden right away (and block the next install);
    # the login item is picked up at the next login, and the app is opened normally with its window.
    sh = _install_sh()
    assert "launchctl bootstrap" not in sh
    assert 'open "$APP"' in sh.split("PLIST\n")[-1]


def test_install_tells_the_user_to_quit_from_the_menu_bar():
    sh = _install_sh()
    line = next(ln for ln in sh.splitlines() if "is running" in ln)
    assert "menu bar icon" in line and "Cmd-Q when Studio is off" not in line
