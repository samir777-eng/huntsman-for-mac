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
