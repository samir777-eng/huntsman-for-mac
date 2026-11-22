# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
# PyInstaller spec for the Windows build (experimental, untested on a Windows PC): one folder, dist/Huntsman/,
# with one windowed Huntsman.exe (app.entry: the window; --service the lighting service; --self-test the smoke
# test; --version). Hidden imports and data files come from platforms/bundle.py, which the self-test also uses.
# Build on Windows, from the repository root:  pyinstaller --noconfirm packaging/windows/huntsman.spec
import os
import re
import runpy

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # noqa: F821  (SPECPATH is set by PyInstaller)
ICON = os.path.join(ROOT, "packaging", "windows", "icon.ico")


class _Bundle:
    def __init__(self, ns):
        self.__dict__.update(ns)


bundle = _Bundle(runpy.run_path(os.path.join(ROOT, "platforms", "bundle.py")))

with open(os.path.join(ROOT, "huntsman_core.py"), encoding="utf-8") as f:
    VERSION = re.search(r'^__version__ = "([0-9.]+)"', f.read(), re.M).group(1)
NUMS = tuple((list(map(int, VERSION.split("."))) + [0, 0, 0, 0])[:4])

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=NUMS, prodvers=NUMS),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Huntsman for Mac contributors"),
            StringStruct("FileDescription", "Huntsman for Mac (Windows build)"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "Huntsman"),
            StringStruct("LegalCopyright", "GPL-3.0-or-later"),
            StringStruct("OriginalFilename", "Huntsman.exe"),
            StringStruct("ProductName", "Huntsman for Mac (Windows build)"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

datas = [(os.path.join(ROOT, src), dest) for src, dest in bundle.DATA]
binaries = []
hiddenimports = list(bundle.HIDDEN_IMPORTS)

# pywebview's WebView2 / WinForms assemblies (webview/lib), pythonnet's Python.Runtime.dll, clr_loader's DLLs.
datas += collect_data_files("webview")
binaries += collect_dynamic_libs("webview")
for d, b, h in (collect_all("clr_loader"), collect_all("pythonnet")):
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "app.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["usb", "objc", "AppKit", "Foundation", "Quartz", "WebKit", "PyObjCTools",
              "webview.platforms.cocoa", "webview.platforms.gtk", "webview.platforms.qt", "pytest", "playwright"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Huntsman",
    console=False,
    icon=ICON,
    version=version_info,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Huntsman", upx=False)  # noqa: F821
