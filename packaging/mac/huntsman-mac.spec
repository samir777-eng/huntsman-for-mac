# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
# PyInstaller spec for the Mac installer build (Apple silicon, macOS 14.0 or later): two self-contained one-folder
# apps, "Huntsman for Mac.app" (HuntsmanForMac: the window, app.entry) and "Huntsman Lighting.app"
# (HuntsmanLighting: the lighting service, packaging/mac/service_entry.py), each with its own bundle id so macOS names
# them apart. tools/build_mac_pkg.sh nests a full copy of the second into the first's Contents/Library/LoginItems,
# signs both and makes the .pkg. Hidden imports and data files come from platforms/bundle.py (mac_modules()), which
# the --self-test of both executables also uses; libusb comes from the libusb-package wheel.
# Build from the repository root (requirements-mac-build.txt):
#   pyinstaller --noconfirm --clean packaging/mac/huntsman-mac.spec
import os
import re
import runpy

import libusb_package

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # noqa: F821  (SPECPATH is set by PyInstaller)
ICON = os.path.join(ROOT, "packaging", "icon.icns")


class _Bundle:
    def __init__(self, ns):
        self.__dict__.update(ns)


bundle = _Bundle(runpy.run_path(os.path.join(ROOT, "platforms", "bundle.py")))
mac_info = runpy.run_path(os.path.join(ROOT, "packaging", "mac", "plists.py"))["mac_info"]

with open(os.path.join(ROOT, "huntsman_core.py"), encoding="utf-8") as f:
    VERSION = re.search(r'^__version__ = "([0-9.]+)"', f.read(), re.M).group(1)

datas = [(os.path.join(ROOT, src), dest) for src, dest in bundle.DATA]
binaries = [(str(libusb_package.get_library_path()), ".")]   # Contents/Frameworks/libusb-1.0.dylib
hiddenimports = bundle.mac_modules()
EXCLUDES = ["webview.platforms.winforms", "webview.platforms.edgechromium", "webview.platforms.gtk",
            "webview.platforms.qt", "webview.platforms.android", "clr_loader", "pythonnet", "pystray", "PIL", "hid",
            "tkinter", "pytest", "playwright"]


def app(script, exe_name, bundle_name, plist):
    info = mac_info(plist, VERSION)
    a = Analysis([os.path.join(ROOT, script)], pathex=[ROOT], binaries=binaries, datas=datas,  # noqa: F821
                 hiddenimports=hiddenimports, excludes=EXCLUDES, noarchive=False)
    pyz = PYZ(a.pure)  # noqa: F821
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=exe_name, console=False,  # noqa: F821
              target_arch="arm64", upx=False, argv_emulation=False)
    coll = COLLECT(exe, a.binaries, a.datas, name=exe_name, upx=False)  # noqa: F821
    return BUNDLE(coll, name=bundle_name, icon=ICON, bundle_identifier=info["CFBundleIdentifier"],  # noqa: F821
                  version=VERSION, info_plist=info)


app("app.py", "HuntsmanForMac", "Huntsman for Mac.app", "Info.plist")
app(os.path.join("packaging", "mac", "service_entry.py"), "HuntsmanLighting", "Huntsman Lighting.app",
    "Lighting-Info.plist")
