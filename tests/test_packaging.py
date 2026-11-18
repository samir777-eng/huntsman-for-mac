# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The Windows build (packaging/windows/huntsman.spec, platforms/bundle.py), its self-test flag, and the GitHub
Actions workflows (.github/workflows/). Nothing here builds, opens the keyboard or a window."""
import ast
import os
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import huntsman_core as hc  # noqa: E402
import models  # noqa: E402
from platforms import bundle  # noqa: E402

SPEC = ROOT / "packaging" / "windows" / "huntsman.spec"
WORKFLOWS = ROOT / ".github" / "workflows"


# ---------- the bundle manifest ----------

def test_every_data_entry_exists_and_covers_what_the_app_reads():
    for src, _dest in bundle.DATA:
        assert (ROOT / src).exists(), src
    sources = {src for src, _ in bundle.DATA}
    assert {"ui", "layouts", "layout.json", "keymap.json"} <= sources
    for m in models.MODELS.values():   # every model's layout is shipped
        assert m.layout in sources or m.layout.split("/")[0] in sources, m.layout
    for f in bundle.REQUIRED_FILES:
        assert (ROOT / f).is_file(), f


def _modules_on_disk(pkg):
    out = []
    for p in (ROOT / pkg).rglob("*.py"):
        parts = p.relative_to(ROOT).with_suffix("").parts
        out.append(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    return out


@pytest.mark.parametrize("pkg", ["lighting", "inputs", "platforms"])
def test_every_package_module_is_a_hidden_import(pkg):
    missing = sorted(set(_modules_on_disk(pkg)) - set(bundle.HIDDEN_IMPORTS))
    assert missing == [], "add these to platforms/bundle.py APP_MODULES"


def test_the_w2_hidden_imports_are_listed():
    need = {"service", "platforms.win_hid", "platforms.win_tray", "platforms.win_autostart", "platforms.win_keys",
            "platforms.win_smart", "platforms.win_guard", "platforms.win_window", "pystray._win32", "PIL.Image",
            "PIL.ImageDraw", "hid", "webview.platforms.edgechromium", "clr_loader", "sounddevice"}
    assert need <= set(bundle.HIDDEN_IMPORTS)
    assert bundle.WINDOWS_ONLY <= set(bundle.HIDDEN_IMPORTS)
    for name in bundle.APP_MODULES:   # our own modules are files in the repository
        rel = name.replace(".", "/")
        assert (ROOT / f"{rel}.py").is_file() or (ROOT / rel / "__init__.py").is_file(), name


def test_the_bundle_manifest_imports_nothing():
    tree = ast.parse((ROOT / "platforms" / "bundle.py").read_text(encoding="utf-8"))
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]


# ---------- the PyInstaller spec ----------

def _spec():
    return SPEC.read_text(encoding="utf-8")


def test_spec_is_python_and_builds_one_windowed_folder_named_huntsman():
    src = _spec()
    ast.parse(src)
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in src[:400]
    assert "COLLECT(" in src and "exclude_binaries=True" in src       # one-folder
    assert "console=False" in src and 'name="Huntsman"' in src
    assert "app.py" in src                                              # entry point app.entry
    assert "platforms/bundle.py" in src or '"platforms", "bundle.py"' in src
    assert "bundle.HIDDEN_IMPORTS" in src and "bundle.DATA" in src


def test_spec_has_a_version_resource_from_huntsman_core():
    src = _spec()
    assert "Huntsman for Mac (Windows build)" in src
    assert "VSVersionInfo" in src and "FileVersion" in src and "ProductName" in src
    assert "huntsman_core.py" in src and "__version__" in src


def test_spec_collects_what_webview2_and_pythonnet_need():
    src = _spec()
    for pkg in ("webview", "clr_loader", "pythonnet"):
        assert re.search(rf'collect_(all|data_files|dynamic_libs)\("{pkg}"', src), pkg


def test_spec_icon_exists():
    m = re.search(r'ICON\s*=\s*os\.path\.join\(ROOT,\s*"([^"]+)"(?:,\s*"([^"]+)")?(?:,\s*"([^"]+)")?\)', _spec())
    assert m, "the spec names its icon"
    assert (ROOT.joinpath(*[g for g in m.groups() if g])).is_file()


def test_spec_leaves_out_the_mac_only_libraries():
    src = _spec()
    for mod in ("usb", "objc", "AppKit", "Quartz", "WebKit"):
        assert f'"{mod}"' in src.split("excludes")[1].split("]")[0], mod


# ---------- Huntsman.exe --self-test / --version ----------

@pytest.fixture
def no_device(monkeypatch):
    """The self-test must never open the keyboard or a window."""
    def boom(*a, **kw):
        pytest.fail("the self-test opened the keyboard or a window")
    monkeypatch.setattr(hc, "open_transport", boom)
    monkeypatch.setattr(hc, "UsbTransport", boom)
    monkeypatch.setattr(hc, "Keyboard", boom)
    monkeypatch.setattr(app, "main", boom)
    import webview
    monkeypatch.setattr(webview, "create_window", boom)
    monkeypatch.setattr(webview, "start", boom)


def test_self_test_passes_here_and_skips_the_windows_only_modules(no_device, capsys):
    assert app.entry(["Huntsman.exe", "--self-test"]) == 0
    out = capsys.readouterr().out
    assert "self-test passed" in out
    assert "ok   ui/index.html" in out and "ok   layout 02A6" in out
    if sys.platform != "win32":
        assert "skip hid (Windows only)" in out


@pytest.mark.windows_host
def test_self_test_imports_the_windows_modules_on_windows(no_device, capsys):
    assert app.entry(["Huntsman.exe", "--self-test"]) == 0
    out = capsys.readouterr().out
    assert "skip " not in out and "ok   webview.platforms.edgechromium" in out and "ok   hid" in out


def test_self_test_fails_on_a_missing_module(no_device, monkeypatch, capsys):
    monkeypatch.setattr(bundle, "HIDDEN_IMPORTS", bundle.HIDDEN_IMPORTS + ["no_such_module_xyz"])
    assert app.entry(["Huntsman.exe", "--self-test"]) == 1
    out = capsys.readouterr().out
    assert "FAIL no_such_module_xyz" in out and "self-test FAILED" in out


def test_self_test_fails_on_a_missing_data_file(no_device, monkeypatch, capsys):
    monkeypatch.setattr(bundle, "REQUIRED_FILES", bundle.REQUIRED_FILES + ["ui/missing.js"])
    assert app.entry(["Huntsman.exe", "--self-test"]) == 1
    assert "FAIL ui/missing.js" in capsys.readouterr().out


def test_version_flag(no_device, capsys):
    assert app.entry(["Huntsman.exe", "--version"]) == 0
    assert capsys.readouterr().out.strip() == f"Huntsman for Mac {hc.__version__}"


# ---------- GitHub Actions ----------

def _workflow(name):
    yaml = pytest.importorskip("yaml")
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in text[:400]
    wf = yaml.safe_load(text)
    wf["on"] = wf.get("on", wf.get(True))   # YAML 1.1 reads a bare `on` key as True
    return wf, text


def _paths_in(text):
    """Repository paths a workflow names (requirements files, the spec, tests)."""
    return set(re.findall(r"(?<![\w./-])((?:requirements[\w-]*\.txt)|(?:packaging/[\w./-]+)|(?:tests)(?=[\s/]))",
                          text))


@pytest.mark.parametrize("name", ["ci.yml", "windows-build.yml"])
def test_workflow_paths_exist(name):
    _wf, text = _workflow(name)
    paths = _paths_in(text)
    assert paths
    for p in paths:
        assert (ROOT / p).exists(), p


def test_ci_runs_the_suite_on_macos_and_windows_with_python_313():
    wf, text = _workflow("ci.yml")
    assert "push" in wf["on"] and "pull_request" in wf["on"]
    runners = set()
    for job in wf["jobs"].values():
        os_ = job["runs-on"]
        if "${{" in str(os_):
            runners |= set(job["strategy"]["matrix"]["os"])
        else:
            runners.add(os_)
    assert {"macos-latest", "windows-latest"} <= runners
    assert "3.13" in text and "pytest" in text and "playwright install chromium" in text
    assert "requirements-win.txt" in text and "requirements.txt" in text and "requirements-dev.txt" in text


def test_windows_build_workflow():
    wf, text = _workflow("windows-build.yml")
    assert "workflow_dispatch" in wf["on"]
    assert wf["on"]["release"]["types"] == ["published"]
    assert wf["permissions"]["contents"] == "write"
    (job,) = wf["jobs"].values()
    assert job["runs-on"] == "windows-latest"
    assert "pyinstaller" in text.lower() and "packaging/windows/huntsman.spec" in text
    assert "--self-test" in text
    assert "Huntsman-for-Windows-" in text and "Compress-Archive" in text
    assert "actions/upload-artifact" in text
    assert "gh release upload" in text and "github.event_name == 'release'" in text
    assert "GITHUB_TOKEN" in text


def test_pyinstaller_is_pinned_in_the_build():
    _wf, text = _workflow("windows-build.yml")
    assert re.search(r"pyinstaller==\d+\.\d+", text.lower())
