# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The Windows tray icon (platforms/win_tray.py) renders the same menu model as the Mac menu bar (menubar.py):
same items, same handlers, same state updates. A fake `pystray` module stands in for the real one."""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import menubar  # noqa: E402
from menubar import MenuState, StatusMenu, build_menu  # noqa: E402
from platforms import win_tray  # noqa: E402


class FakeItem:
    def __init__(self, text, action=None, checked=None, enabled=True, radio=False, **kw):
        self.text, self.action, self.checked, self.enabled, self.radio = text, action, checked, enabled, radio
        self.submenu = action if isinstance(action, FakeMenu) else None


class FakeMenu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = list(items)


class FakeIcon:
    def __init__(self, name, icon=None, title=None, menu=None):
        self.name, self.icon, self.title, self.menu = name, icon, title, menu
        self.updates = self.stopped = self.ran = 0

    def update_menu(self):
        self.updates += 1

    def run(self, setup=None):
        self.ran += 1
        if setup:
            setup(self)

    def stop(self):
        self.stopped += 1


def fake_pystray():
    return types.SimpleNamespace(Menu=FakeMenu, MenuItem=FakeItem, Icon=FakeIcon)


def handlers(log):
    return dict(on_toggle=lambda on: log.append(("toggle", on)), on_preset=lambda n: log.append(("preset", n)),
                on_open=lambda: log.append(("open",)), on_quit=lambda: log.append(("quit",)))


def flat(menu):
    out = []
    for it in menu.items:
        if it is FakeMenu.SEPARATOR:
            out.append("-")
        elif it.submenu is not None:
            out.append((it.text, flat(it.submenu)))
        else:
            out.append((it.text, bool(it.checked(it) if callable(it.checked) else it.checked), it.enabled))
    return out


def test_both_front_ends_share_one_menu_model():
    log = []
    mac = StatusMenu(presets=["Calm", "Gaming"], active="Calm", quit_title="Quit lighting service", **handlers(log))
    win = win_tray.TrayMenu(presets=["Calm", "Gaming"], active="Calm", quit_title="Quit lighting service",
                            pystray=fake_pystray(), image=object(), **handlers(log))
    assert isinstance(mac, MenuState) and isinstance(win, MenuState)
    assert mac.model() == win.model() == build_menu(True, ["Calm", "Gaming"], "Calm", "Quit lighting service")


def test_the_tray_renders_every_item_of_the_model():
    log = []
    tray = win_tray.TrayMenu(presets=["Calm", "Gaming"], active="Gaming", quit_title="Quit lighting service",
                             pystray=fake_pystray(), image=object(), **handlers(log))
    menu = tray.pystray_menu()
    assert flat(menu) == [("Lighting", True, True), ("Presets", [("Calm", False, True), ("Gaming", True, True)]), "-",
                          ("Open Huntsman for Mac", False, True), "-", ("Quit lighting service", False, True)]


def test_clicking_a_tray_item_runs_the_shared_handler():
    log = []
    tray = win_tray.TrayMenu(presets=["Calm"], pystray=fake_pystray(), image=object(), **handlers(log))
    menu = tray.pystray_menu()
    menu.items[0].action(None, menu.items[0])
    menu.items[1].submenu.items[0].action(None, menu.items[1].submenu.items[0])
    menu.items[3].action(None, menu.items[3])
    menu.items[5].action(None, menu.items[5])
    assert log == [("toggle", False), ("preset", "Calm"), ("open",), ("quit",)]


def test_set_state_rebuilds_the_installed_tray_menu():
    tray = win_tray.TrayMenu(presets=["Calm"], pystray=fake_pystray(), image=object(), **handlers([]))
    tray.set_state(enabled=False)   # before install: nothing to update
    tray.install()
    icon = tray.icon
    assert icon.title == "Huntsman for Mac" and flat(icon.menu)[0] == ("Lighting", False, True)
    tray.set_state(enabled=True, presets=["Calm", "Party"], active="Party")
    assert flat(icon.menu)[1] == ("Presets", [("Calm", False, True), ("Party", True, True)])
    assert icon.updates >= 1
    tray.remove()
    assert icon.stopped == 1 and not tray.installed


def test_a_notice_shows_as_a_disabled_first_item_in_both_menus():
    items = build_menu(True, [], None, notice="Paused: Razer Synapse is running")
    assert (items[0].title, items[0].enabled, items[0].action) == ("Paused: Razer Synapse is running", False, None)
    assert items[1].separator and items[2].title == "Lighting"
    tray = win_tray.TrayMenu(pystray=fake_pystray(), image=object(), **handlers([]))
    tray.set_state(notice="Paused: Razer Synapse is running")
    assert flat(tray.pystray_menu())[0] == ("Paused: Razer Synapse is running", False, False)
    tray.set_state(notice=None)
    assert flat(tray.pystray_menu())[0][0] == "Lighting"


def test_the_mac_menu_has_no_notice_by_default():
    assert [i.title for i in build_menu(True, [], None)][0] == "Lighting"


def test_the_tray_icon_image_is_drawn_without_asset_files():
    pil = pytest.importorskip("PIL.Image")
    img = win_tray.icon_image()
    assert isinstance(img, pil.Image) and img.size == (64, 64)


def test_importing_the_tray_needs_no_pystray():
    assert "pystray" not in sys.modules or sys.modules["pystray"] is not None
    assert menubar._TARGET_CLASS is None   # and no Cocoa either


def test_run_after_remove_returns_at_once():
    """A quit can remove the tray before its loop starts (the service quit during start): run() must not then
    block forever in a loop nobody will stop."""
    tray = win_tray.TrayMenu(presets=["Calm"], pystray=fake_pystray(), image=object(), **handlers([]))
    tray.remove()
    ready = []
    tray.run(on_ready=lambda: ready.append(1))
    assert tray.icon is None and ready == []


def test_remove_after_install_still_stops_the_icon():
    tray = win_tray.TrayMenu(presets=["Calm"], pystray=fake_pystray(), image=object(), **handlers([]))
    tray.install()
    icon = tray.icon
    tray.remove()
    assert icon.stopped == 1
    tray.run()
    assert icon.ran == 0 and tray.icon is None
