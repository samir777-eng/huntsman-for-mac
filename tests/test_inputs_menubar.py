# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Menu bar model and dispatch, without creating a Cocoa status item."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import menubar  # noqa: E402
from menubar import MenuItem, StatusMenu, build_menu  # noqa: E402


def titles(items):
    return [("-" if i.separator else i.title) for i in items]


def test_menu_layout():
    items = build_menu(True, ["Calm", "Gaming"], "Gaming")
    assert titles(items) == ["Lighting", "Presets", "-", "Open Huntsman for Mac", "-", "Quit Huntsman for Mac"]
    assert items[0].checked is True and items[0].action == "toggle"
    sub = items[1].children
    assert [(c.title, c.checked, c.action, c.payload) for c in sub] == [
        ("Calm", False, "preset", "Calm"), ("Gaming", True, "preset", "Gaming")]
    assert items[3].action == "open" and items[5].action == "quit"


def test_lighting_unchecked_when_off():
    assert build_menu(False, [], None)[0].checked is False


def test_no_presets_shows_a_disabled_placeholder():
    sub = build_menu(True, [], None)[1].children
    assert [(c.title, c.enabled, c.action) for c in sub] == [("No presets yet", False, None)]


def test_menu_item_defaults():
    m = MenuItem("x")
    assert (m.action, m.checked, m.enabled, m.children, m.separator, m.payload) == (None, False, True, (), False, None)


def make():
    log = []
    menu = StatusMenu(on_toggle=lambda on: log.append(("toggle", on)),
                      on_preset=lambda name: log.append(("preset", name)),
                      on_open=lambda: log.append(("open",)),
                      on_quit=lambda: log.append(("quit",)),
                      presets=["Calm", "Gaming"])
    return menu, log


def test_activate_calls_the_right_handler():
    menu, log = make()
    items = menu.model()
    menu.activate("toggle")
    menu.activate("preset", "Calm")
    menu.activate("open")
    menu.activate("quit")
    assert log == [("toggle", False), ("preset", "Calm"), ("open",), ("quit",)]
    assert items[0].checked is True  # started enabled


def test_set_state_updates_the_model():
    menu, log = make()
    menu.set_state(enabled=False, active="Gaming", presets=["Gaming", "Party"])
    items = menu.model()
    assert items[0].checked is False
    assert [(c.title, c.checked) for c in items[1].children] == [("Gaming", True), ("Party", False)]
    menu.activate("toggle")
    assert log == [("toggle", True)]


def test_a_failing_handler_does_not_raise_into_cocoa():
    def boom():
        raise RuntimeError("window gone")

    menu = StatusMenu(on_toggle=lambda on: None, on_preset=lambda n: None, on_open=boom, on_quit=lambda: None)
    menu.activate("open")  # must not raise
    menu.activate("unknown-action")


def test_set_state_before_install_does_not_touch_cocoa():
    menu, _ = make()
    menu.set_state(enabled=True)
    assert not menu.installed
    menu.remove()  # safe when never installed


def test_cocoa_is_not_imported_by_the_model():
    # The model is importable in tests without starting AppKit: the module itself defines no ObjC class.
    assert menubar._TARGET_CLASS is None
