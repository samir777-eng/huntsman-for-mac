# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The Studio tab in demo mode (headless Chromium): presets, layer stack, gallery, parameter forms, smart lighting
and sound panes. Every call to the Python side is recorded by the page fixture from test_ui."""
import pytest

from test_ui import IDS, browser, calls, cap, page, sync_api, wait_for_call  # noqa: F401  (fixtures)

expect = sync_api.expect


@pytest.fixture
def studio(page):  # noqa: F811
    page.click('.tabs button[data-view="studio"]')
    expect(page.locator('.pane[data-pane="studio"]')).to_be_visible()
    expect(page.locator("#stStack li").first).to_be_visible()
    return page


def last_layers(page):
    return calls(page, "update_layers")[-1][0]


def test_studio_lists_presets_and_shows_live_frames(studio):
    opts = studio.locator("#stPreset option")
    names = opts.all_inner_texts()
    assert "Aurora" in names and "Gaming WASD" in names
    expect(studio.locator("#stPreset")).to_have_value("Gaming WASD")
    expect(studio.locator("#stStack li")).to_have_count(3)
    # the top of the list is the top layer: the ripple reaction
    expect(studio.locator("#stStack li").first).to_contain_text("Ripple")
    expect(studio.locator("#stageNote")).to_contain_text("Studio is off")
    studio.check("#stOn")
    assert wait_for_call(studio, "studio_enable")[-1] == [True]
    expect(studio.locator("#stOnLabel")).to_have_text("On")
    # live frames from the (simulated) engine colour the legends
    studio.wait_for_function("() => window.__frames > 3")
    w = cap(studio, "W").evaluate("c => c.style.getPropertyValue('--legend')")
    assert w.startswith("#") and w != "#e9e9ee"
    assert studio.errors == []


def test_add_layer_from_gallery(studio):
    studio.click("#stAdd")
    expect(studio.locator("#gallery")).to_be_visible()
    expect(studio.locator("#gallery h3")).to_have_count(4)   # basic, ambient, sound, typing
    studio.click('#gallery button[data-effect="reactive_explosion"]')
    expect(studio.locator("#gallery")).to_be_hidden()
    expect(studio.locator("#stStack li")).to_have_count(4)
    expect(studio.locator("#stStack li").first).to_contain_text("Explosion")
    wait_for_call(studio, "update_layers")
    top = last_layers(studio)[-1]
    assert top["effect"] == "reactive_explosion" and top["blend"] == "add"
    expect(studio.locator("#stEdTitle")).to_have_text("Explosion")
    expect(studio.locator("#stDirty")).to_be_visible()
    assert studio.errors == []


def test_edit_a_parameter(studio):
    studio.locator("#stStack li").nth(2).locator(".layer-main").click()   # the solid base layer
    expect(studio.locator("#stEdTitle")).to_have_text("Solid colour")
    studio.locator('#stParams input[type="color"]').first.evaluate(
        "e => { e.value = '#00ff00'; e.dispatchEvent(new Event('input', {bubbles: true})); }")
    wait_for_call(studio, "update_layers")
    assert last_layers(studio)[0]["params"]["color"] == [0, 255, 0]
    # a slider parameter on another layer
    studio.locator("#stStack li").first.locator(".layer-main").click()
    studio.locator('#stParams input[type="range"]').first.evaluate(
        "e => { e.value = e.max; e.dispatchEvent(new Event('input', {bubbles: true})); }")
    studio.wait_for_function("() => window.__calls.filter(c => c[0] === 'update_layers').length >= 2")
    assert last_layers(studio)[-1]["params"]["speed"] == 40
    assert studio.errors == []


def test_reorder_hide_and_delete_layers(studio):
    first = studio.locator("#stStack li").first
    first.get_by_role("button", name="Move Ripple down").click()
    wait_for_call(studio, "update_layers")
    assert [x["effect"] for x in last_layers(studio)] == ["solid", "reactive_ripple", "solid"]
    expect(studio.locator("#stStack li").nth(1)).to_contain_text("Ripple")
    studio.locator("#stStack li").nth(1).get_by_role("button", name="Show Ripple").click()
    studio.wait_for_function("() => window.__calls.filter(c => c[0] === 'update_layers').length >= 2")
    assert last_layers(studio)[1]["enabled"] is False
    studio.locator("#stStack li").nth(1).get_by_role("button", name="Delete Ripple").click()
    expect(studio.locator("#stStack li")).to_have_count(2)
    studio.wait_for_function("() => window.__calls.filter(c => c[0] === 'update_layers').length >= 3")
    assert [x["effect"] for x in last_layers(studio)] == ["solid", "solid"]
    assert studio.errors == []


def test_save_as_creates_a_preset(studio):
    studio.click("#stSaveAs")
    expect(studio.locator("#nameDialog")).to_be_visible()
    studio.fill("#ndName", "Aurora")
    studio.click("#ndOk")
    expect(studio.locator("#ndErr")).to_contain_text("built in")
    studio.fill("#ndName", "My WASD")
    studio.click("#ndOk")
    expect(studio.locator("#nameDialog")).to_be_hidden()
    saved = wait_for_call(studio, "save_preset")[-1][0]
    assert saved["name"] == "My WASD" and len(saved["layers"]) == 3
    expect(studio.locator("#stPreset")).to_have_value("My WASD")
    expect(studio.locator('#stPreset optgroup[label="Yours"] option')).to_have_text(["My WASD"])
    assert studio.errors == []


def test_presets_menu_is_keyboard_operable(studio):
    studio.focus("#stMore")
    studio.keyboard.press("Enter")
    expect(studio.locator("#stMenu")).to_be_visible()
    expect(studio.locator('#stMenu [data-act="rename"]')).to_be_disabled()   # built-in preset
    expect(studio.locator('#stMenu [data-act="duplicate"]')).to_be_focused()
    studio.keyboard.press("ArrowDown")
    expect(studio.locator('#stMenu [data-act="export"]')).to_be_focused()
    studio.keyboard.press("Escape")
    expect(studio.locator("#stMenu")).to_be_hidden()
    expect(studio.locator("#stMore")).to_be_focused()


def test_smart_pane_saves_rules(studio):
    studio.click("#stTabSmart")
    expect(studio.locator("#stSmart")).to_be_visible()
    studio.check("#smIdle")
    studio.fill("#smMinutes", "5")
    studio.select_option("#smAction", "off")
    studio.wait_for_function("() => window.__calls.some(c => c[0] === 'set_smart' && c[1][0].idle.action === 'off')")
    cfg = calls(studio, "set_smart")[-1][0]
    assert cfg["idle"]["enabled"] is True and cfg["idle"]["minutes"] == 5
    studio.select_option("#smPick", "com.valvesoftware.steam")
    studio.click("#smAdd")
    expect(studio.locator("#smRules li")).to_have_count(1)
    studio.wait_for_function("() => window.__calls.some(c => c[0] === 'set_smart' && c[1][0].app_rules.length === 1)")
    rule = calls(studio, "set_smart")[-1][0]["app_rules"][0]
    assert rule == {"bundle_id": "com.valvesoftware.steam", "preset": "Gaming WASD"}
    assert studio.errors == []


def test_sound_device_select(studio):
    studio.click("#stTabSound")
    expect(studio.locator("#stDevice option")).to_have_count(3)
    studio.select_option("#stDevice", label="BlackHole 2ch (system audio)")
    assert wait_for_call(studio, "set_audio_device")[-1] == [2]
    studio.select_option("#stDevice", label="Default input")
    studio.wait_for_function("() => window.__calls.filter(c => c[0] === 'set_audio_device').length >= 2")
    assert calls(studio, "set_audio_device")[-1] == [None]
    assert studio.errors == []


def test_master_switch_and_permission_notice(studio):
    studio.check("#stOn")
    wait_for_call(studio, "studio_enable")
    expect(studio.locator("#stOnLabel")).to_have_text("On")
    expect(studio.locator("#stCloseHint")).to_be_visible()
    studio.uncheck("#stOn")
    studio.wait_for_function("() => window.__calls.filter(c => c[0] === 'studio_enable').length >= 2")
    assert calls(studio, "studio_enable")[-1] == [False]
    expect(studio.locator("#stageNote")).to_contain_text("Studio is off")
    studio.evaluate("window.onStudioStatus({errors: {keys: 'macOS blocked reading key presses. Allow Input Monitoring "
                    "in System Settings, Privacy & Security, Input Monitoring.', audio: null, presets: null}})")
    studio.click("#stTabTyping")
    expect(studio.locator("#stKeysErr")).to_contain_text("Privacy & Security, Input Monitoring")
    assert studio.errors == []
