# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Fixes from the 0.4.0 UX audit (docs/plans/2026-11-18-ux-audit-fixes.md), in demo mode (headless Chromium):
the no-keyboard state, mixed depths, small windows, the sticky Apply, the Studio preview while Studio is off,
built-in presets, the live readout and stale toasts. Every call to the Python side is recorded (test_ui's RECORDER)."""
import re

import pytest

from test_ui import IDS, RECORDER, URL, browser, calls, cap, page, sync_api, wait_for_call  # noqa: F401  (fixtures)
from test_ui_models import unplugged  # noqa: F401  (fixture)

expect = sync_api.expect
SHOWN = re.compile(r"\bshow\b")
ERR = re.compile(r"\berr\b")


def open_at(browser, w, h):  # noqa: F811
    pg = browser.new_page(viewport={"width": w, "height": h})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.add_init_script(RECORDER)
    pg.goto(URL)
    expect(pg.locator("#conn")).to_have_text("Connected, firmware 1.03")
    return pg


@pytest.fixture
def small(browser):  # noqa: F811
    pg = open_at(browser, 1024, 700)
    yield pg
    pg.close()


def set_depth(page, v):
    page.locator("#depth").evaluate("(e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})); }", v)


# ---------- 1. no keyboard ----------

def test_no_keyboard_shows_a_plug_in_state_instead_of_a_dead_panel(unplugged):  # noqa: F811
    page = unplugged()
    expect(page.locator("#noKb")).to_be_visible()
    expect(page.locator("#noKb h2")).to_have_text("Plug in your Huntsman by USB")
    expect(page.locator("#emptyReconnect")).to_have_text("Reconnect")
    expect(page.locator("#emptyReconnect")).to_have_class(re.compile(r"\bprimary\b"))
    expect(page.locator("#kbWrap")).to_be_hidden()
    expect(page.locator(".device-name")).to_have_text("No keyboard")          # not a stale model name
    assert page.locator('.pane[data-pane="lighting"]').evaluate("p => p.inert")
    expect(page.locator("#toast")).not_to_have_class(SHOWN)                    # the stage says it; no red toast
    assert page.errors == []


def test_no_keyboard_hides_the_studio_is_lighting_note(unplugged):  # noqa: F811
    """With nothing plugged in, "Studio is lighting the keyboard now" would be false even if Studio is on."""
    page = unplugged()
    page.goto(page.url + "&studio")                       # Studio on, as the owner's service had it
    expect(page.locator("#conn")).to_have_text("Not connected")
    page.click('#sources button[data-view="lighting"]')
    expect(page.locator("#studioOnNote")).to_be_hidden()


def test_reconnect_from_the_empty_state_clears_errors_and_says_connected(unplugged):  # noqa: F811
    page = unplugged()
    page.evaluate("toast('No reply', true)")
    page.click("#emptyReconnect")
    expect(page.locator("#conn")).to_have_text("Connected, firmware 1.03")
    expect(page.locator("#noKb")).to_be_hidden()
    expect(page.locator("#kbWrap")).to_be_visible()
    expect(page.locator("#toast")).to_have_text("Connected to Huntsman V3 Pro")
    expect(page.locator("#toast")).not_to_have_class(ERR)
    expect(page.locator(".device-name")).to_have_text("Huntsman V3 Pro")
    assert not page.locator('.pane[data-pane="lighting"]').evaluate("p => p.inert")
    assert page.errors == []


# ---------- 2. mixed depths ----------

def test_mixed_depths_read_mixed_and_nothing_is_dirty_until_an_edit(page):  # noqa: F811
    expect(page.locator("#depthNum")).to_have_text("Mixed")
    expect(page.locator(".readout")).to_contain_text("1.0–2.0 mm")
    expect(page.locator("#actDirty")).to_be_hidden()
    page.click('#selectTools [data-sel="wasd"]')
    expect(page.locator("#depthNum")).to_have_text("1.0")                      # the selection's own depth
    expect(page.locator("#actDirty")).to_be_hidden()
    page.click('#selectTools [data-sel="none"]')
    expect(page.locator("#depthNum")).to_have_text("Mixed")
    set_depth(page, "1.2")
    expect(page.locator("#depthNum")).to_have_text("1.2")
    expect(page.locator("#actDirty")).to_be_visible()
    assert page.errors == []


def test_apply_over_keys_with_other_depths_asks_first(page):  # noqa: F811
    expect(page.locator("#applyDepth")).to_have_text("Apply to all keys")
    page.click("#applyDepth")
    dlg = page.locator("#confirmApply")
    expect(dlg).to_be_visible()
    expect(dlg).to_contain_text("W, A, S, D")
    dlg.locator('button[value="cancel"]').click()
    expect(dlg).to_be_hidden()
    assert calls(page, "set_depth") == []
    page.click("#applyDepth")
    dlg.locator('button[value="apply"]').click()
    (args,) = wait_for_call(page, "set_depth")
    assert args[0] == [] and args[1] == 2.0
    expect(page.locator("#depthNum")).to_have_text("2.0")
    assert page.errors == []


def test_apply_to_keys_at_one_depth_does_not_ask(page):  # noqa: F811
    page.click('#selectTools [data-sel="wasd"]')
    set_depth(page, "1.5")
    page.click("#applyDepth")
    (args,) = wait_for_call(page, "set_depth")
    assert sorted(args[0]) == sorted(IDS[n] for n in "WASD") and args[1] == 1.5
    expect(page.locator("#confirmApply")).to_be_hidden()


# ---------- 3. small windows ----------

def rect(loc):
    return loc.evaluate("e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }")


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def test_depth_labels_fit_beside_the_legends_in_a_normal_window(page):  # noqa: F811
    q = cap(page, "Q")
    expect(q.locator(".front")).to_have_css("opacity", "1")
    assert not overlap(rect(q.locator(".legend")), rect(q.locator(".front")))


def test_small_window_shows_depths_on_hover_instead_of_over_the_legends(small):
    q = cap(small, "Q")
    expect(q.locator(".front")).to_have_css("opacity", "0")
    expect(q.locator(".legend")).to_have_css("opacity", "1")
    expect(small.locator("#stageNote")).to_contain_text("point at")
    q.hover()
    expect(q.locator(".front")).to_have_css("opacity", "1")
    expect(q.locator(".legend")).to_have_css("opacity", "0")                 # the number takes the legend's place
    small.mouse.move(5, 5)
    q.focus()
    expect(q.locator(".front")).to_have_css("opacity", "1")
    assert small.errors == []


def test_small_window_legends_scale_with_the_keys(small):
    size = cap(small, "Q").locator(".legend").evaluate(
        "e => parseFloat(getComputedStyle(e).fontSize) * parseFloat(document.querySelector('#kb').style.zoom)")
    cap_h = rect(cap(small, "Q"))
    assert size < (cap_h[3] - cap_h[1]) * 0.38   # was 10.5 px on a 25 px key


# ---------- 4. readings only while testing; Apply stays in view ----------

def test_readings_show_only_while_testing(page):  # noqa: F811
    expect(page.locator("#actReadings")).to_be_hidden()
    page.click("#actTest")
    wait_for_call(page, "start_test")
    expect(page.locator("#actReadings")).to_be_visible()
    page.click("#bannerStop")
    wait_for_call(page, "stop_test")
    expect(page.locator("#actReadings")).to_be_hidden()


def test_primary_actions_stay_in_view_in_a_short_window(small):
    expect(small.locator("#applyDepth")).to_be_in_viewport()
    small.click("#actTest")
    wait_for_call(small, "start_test")
    expect(small.locator("#applyDepth")).to_be_in_viewport()                 # readings and warning shown too
    small.click("#bannerStop")
    for tab, btn in [("rapid", "#applyRt"), ("snap", "#applySnap")]:
        small.click(f'.tabs button[data-view="{tab}"]')
        expect(small.locator(btn)).to_be_in_viewport()
    small.click('.tabs button[data-view="lighting"]')
    small.click("#tabEffect")
    expect(small.locator("#applyFx")).to_be_in_viewport()
    assert small.errors == []


# ---------- 5. Studio previews while it is off ----------

@pytest.fixture
def studio(page):  # noqa: F811
    page.click('.tabs button[data-view="studio"]')
    expect(page.locator("#stStack li").first).to_be_visible()
    return page


def test_studio_off_previews_on_the_board_with_a_chip(studio):
    chip = studio.locator("#stPreview")
    expect(chip).to_be_visible()
    expect(chip).to_contain_text("Preview, Studio off")
    assert wait_for_call(studio, "studio_preview")[-1][0] > 0
    studio.wait_for_function("() => window.__frames > 3")
    w = IDS["W"]
    studio.wait_for_function(
        f"() => document.querySelector('.cap[data-id=\"{w}\"]').style.getPropertyValue('--legend') === studioColour({w})")
    assert calls(studio, "studio_enable") == []                                 # nothing reaches the keys
    studio.click("#stPreviewOn")
    assert wait_for_call(studio, "studio_enable")[-1] == [True]
    expect(chip).to_be_hidden()
    assert studio.errors == []


def test_leaving_studio_ends_the_preview(studio):
    wait_for_call(studio, "studio_preview")
    studio.click('.tabs button[data-view="lighting"]')
    studio.wait_for_function("() => window.__calls.some(c => c[0] === 'studio_preview' && c[1][0] === 0)")
    expect(cap(studio, "W")).to_have_attribute("style", re.compile(r"--legend: #ff3b30"))   # the keyboard's own red
    expect(studio.locator("#stPreview")).to_be_hidden()


# ---------- 6. built-in presets ----------

def test_built_in_preset_offers_save_as_with_a_hint(studio):
    expect(studio.locator("#stSave")).to_be_hidden()
    expect(studio.locator("#stSaveAs")).to_have_class(re.compile(r"\bprimary\b"))
    expect(studio.locator("#stBuiltinHint")).to_have_text("Built-in preset: save a copy to keep your changes.")
    studio.click("#stSaveAs")
    studio.fill("#ndName", "Mine")
    studio.click("#ndOk")
    expect(studio.locator("#stPreset")).to_have_value("Mine")
    expect(studio.locator("#stSave")).to_be_visible()
    expect(studio.locator("#stSaveAs")).not_to_have_class(re.compile(r"\bprimary\b"))
    expect(studio.locator("#stBuiltinHint")).to_be_hidden()


# ---------- quick wins ----------

def test_live_readout_is_announced(page):  # noqa: F811
    assert page.locator("#mHit").get_attribute("aria-live") == "polite"


def test_switching_tabs_drops_the_last_toast(page):  # noqa: F811
    page.evaluate("toast('No reply', true)")
    expect(page.locator("#toast")).to_have_class(SHOWN)
    page.click('.tabs button[data-view="rapid"]')
    expect(page.locator("#toast")).not_to_have_class(SHOWN)


# ---------- batch B: 7. the Keyboard button and the key tester ----------

def open_url(browser, query):  # noqa: F811
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.add_init_script(RECORDER)
    pg.goto(URL + query)
    return pg


def test_the_gear_is_labelled_keyboard(page):  # noqa: F811
    gear = page.locator("header .gear")
    expect(gear).to_have_text("Keyboard")                                      # a visible label, not only an icon
    expect(gear).to_have_accessible_name("Keyboard")                          # what the lock notes call it
    gear.click()
    expect(page.locator('.pane[data-pane="device"] h2')).to_have_text("Keyboard")


@pytest.mark.parametrize("query, reason", [
    ("&model=02B0", "Key tester isn't available on experimental models."),
    ("&model=0266", "Key tester isn't available on the Huntsman V2 family."),
    ("&windows=dynamic", "Key tester isn't available on Windows yet."),
])
def test_key_tester_shows_disabled_with_the_reason(browser, query, reason):  # noqa: F811
    pg = open_url(browser, query)
    try:
        expect(pg.locator("#conn")).to_have_text("Connected, firmware 1.03")
        btn = pg.locator("#actTest")
        expect(btn).to_be_visible()
        expect(btn).to_be_disabled()
        why = pg.locator("#actTestWhy")
        expect(why).to_have_text(reason)
        assert why.get_attribute("id") in btn.get_attribute("aria-describedby")
        assert calls(pg, "start_test") == []
        assert pg.errors == []
    finally:
        pg.close()


def test_key_tester_has_no_reason_where_it_works(page):  # noqa: F811
    expect(page.locator("#actTest")).to_be_enabled()
    expect(page.locator("#actTestWhy")).to_be_hidden()


# ---------- 8. Windows notices ----------

def test_while_synapse_runs_one_short_notice_with_details(browser):  # noqa: F811
    pg = open_url(browser, "&windows=synapse,dynamic")
    try:
        expect(pg.locator("#conn")).to_have_text("Paused: Razer Synapse is running")
        box = pg.locator("#platformNotice")
        expect(box.locator("strong").first).to_have_text("Quit Razer Synapse to use these controls")
        why = box.locator("details").first
        assert why.evaluate("d => d.open") is False                           # the long reason is folded away
        expect(why).to_contain_text("two programs talking to the keyboard")
        assert "Huntsman for Mac" not in box.text_content()                    # "this app" on Windows
        expect(box.locator("details")).to_have_count(2)                        # Dynamic Lighting folded too
        assert box.bounding_box()["height"] < 120                               # was ~10 lines
        expect(pg.locator(".lock-note:visible")).to_have_count(0)               # turning on Experimental won't help
        pg.click('#sources button[data-view="lighting"]')
        expect(pg.locator(".lock-note:visible")).to_have_count(0)
        why.locator("summary").click()
        expect(why).to_contain_text("Quit Synapse, including its icon")
        assert pg.errors == []
    finally:
        pg.close()


def test_windows_without_synapse_keeps_the_lock_note_and_a_compact_dynamic_lighting_notice(browser):  # noqa: F811
    pg = open_url(browser, "&windows=dynamic")
    try:
        expect(pg.locator("#conn")).to_have_text("Connected, firmware 1.03")
        box = pg.locator("#platformNotice")
        expect(box).to_contain_text("Windows Dynamic Lighting is on")
        expect(box.locator("details")).to_have_count(1)
        assert box.bounding_box()["height"] < 90
        expect(pg.locator('.pane[data-pane="actuation"] .lock-note')).to_be_visible()   # the switch does help here
        assert pg.errors == []
    finally:
        pg.close()


# ---------- 9. selection scope ----------

def test_selection_from_another_tab_is_named_with_a_clear(page):  # noqa: F811
    page.click('#selectTools [data-sel="wasd"]')
    page.click('.tabs button[data-view="rapid"]')
    scope = page.locator("#rtScope")
    expect(scope).to_contain_text("Applying to 4 selected keys")
    scope.get_by_role("button", name="Clear selection").click()
    expect(scope).to_have_text("All keys")
    expect(page.locator(".cap.sel")).to_have_count(0)
    page.check("#rtOn")
    expect(page.locator("#applyRt")).to_have_text("Apply to all keys")
    page.click('.tabs button[data-view="actuation"]')
    page.click('#selectTools [data-sel="letters"]')
    expect(page.locator("#actScope")).to_contain_text("Applying to 26 selected keys")
    assert page.errors == []


def test_select_bar_hides_where_selection_does_nothing(page):  # noqa: F811
    page.click('#selectTools [data-sel="wasd"]')
    page.click('.tabs button[data-view="lighting"]')
    expect(page.locator("#selectTools")).to_be_visible()                       # Per key paints the selection
    page.click("#tabEffect")
    page.select_option("#effect", "spectrum")
    expect(page.locator("#selectTools")).to_be_hidden()                        # effects light every key
    expect(page.locator(".cap.sel")).to_have_count(0)
    page.select_option("#effect", "static")                                   # Static colours the selection
    expect(page.locator("#selectTools")).to_be_visible()
    page.click('.tabs button[data-view="studio"]')
    expect(page.locator("#selectTools")).to_be_visible()                       # layers can use the selection
    for tab in ["#stTabSound", "#stTabTyping", "#stTabSmart"]:
        page.click(tab)
        expect(page.locator("#selectTools")).to_be_hidden()
        expect(page.locator(".cap.sel")).to_have_count(0)
    page.click("#stTabLayers")
    expect(page.locator("#selectTools")).to_be_visible()
    expect(page.locator(".cap.sel")).to_have_count(4)                          # the selection was kept
    assert page.errors == []


# ---------- 10. Snap Tap ----------

def test_snap_tap_switch_apply_and_state(page):  # noqa: F811
    page.click('.tabs button[data-view="snap"]')
    on, btn, dirty = page.locator("#snapOn"), page.locator("#applySnap"), page.locator("#snapDirty")
    expect(on).not_to_be_checked()
    expect(btn).to_have_text("Apply")                                          # the status line says it's off
    expect(page.locator("#snapState")).to_have_text("Off")
    expect(btn).to_be_disabled()
    expect(dirty).to_be_hidden()
    page.check("#snapOn")
    expect(dirty).to_have_text("Not applied yet")
    expect(btn).to_have_text("Apply to A and D")
    btn.click()
    assert wait_for_call(page, "set_snap")[-1] == [[IDS["A"], IDS["D"]]]       # the same call as before
    expect(page.locator("#snapState")).to_have_text("On for A and D")
    expect(dirty).to_be_hidden()
    expect(btn).to_be_disabled()                                               # nothing left to apply
    expect(page.locator("#offSnap")).to_have_count(0)                          # the switch turns it off
    page.uncheck("#snapOn")
    expect(dirty).to_be_visible()
    expect(btn).to_have_text("Turn off Snap Tap")
    btn.click()
    page.wait_for_function("() => window.__calls.filter(c => c[0] === 'set_snap').length === 2")
    assert calls(page, "set_snap")[-1] == [None]
    expect(page.locator("#snapState")).to_have_text("Off")
    expect(dirty).to_be_hidden()
    assert page.errors == []


def test_snap_tap_keys_are_picked_on_the_board(page):  # noqa: F811
    page.click('.tabs button[data-view="snap"]')
    expect(page.locator("#stageNote")).to_contain_text("first key")
    cap(page, "Q").click()
    expect(page.locator("#snapA")).to_have_value(str(IDS["Q"]))
    expect(page.locator("#stageNote")).to_contain_text("second key")
    cap(page, "E").click()
    expect(page.locator("#snapB")).to_have_value(str(IDS["E"]))
    expect(page.locator("#snapOn")).to_be_checked()                            # picking keys means turning it on
    expect(cap(page, "Q")).to_have_class(re.compile(r"\bpair\b"))
    expect(cap(page, "E")).to_have_class(re.compile(r"\bpair\b"))
    expect(page.locator("#snapDirty")).to_be_visible()
    expect(page.locator("#applySnap")).to_have_text("Apply to Q and E")
    cap(page, "W").focus()                                                     # and from the keyboard
    page.keyboard.press("Enter")
    expect(page.locator("#snapA")).to_have_value(str(IDS["W"]))
    page.select_option("#snapB", str(IDS["S"]))                               # the lists still work
    expect(cap(page, "S")).to_have_class(re.compile(r"\bpair\b"))
    page.click("#applySnap")
    assert wait_for_call(page, "set_snap")[-1] == [[IDS["W"], IDS["S"]]]
    assert page.errors == []


# ---------- quick wins, batch B ----------

def test_layer_reorder_buttons_are_big_enough(studio):
    box = studio.locator("#stStack li").first.locator(".layer-tools .down").bounding_box()
    assert box["width"] >= 32 and box["height"] >= 32


def test_a_solid_colour_added_on_top_mixes_in_at_half(studio):
    studio.click("#stAdd")
    studio.click('#gallery button[data-effect="solid"]')
    wait_for_call(studio, "update_layers")
    top = calls(studio, "update_layers")[-1][0][-1]
    assert top["effect"] == "solid" and top["blend"] == "normal" and top["opacity"] == 0.5
    expect(studio.locator("#stOpacity")).to_have_value("50")


def test_a_solid_colour_on_an_empty_stack_covers_the_keys(studio):
    studio.select_option("#stPreset", "Rainbow wave")
    expect(studio.locator("#stStack li")).to_have_count(1)
    studio.locator("#stStack li").first.get_by_role("button", name="Delete Rainbow").click()
    expect(studio.locator("#stStack li.layer")).to_have_count(0)
    studio.click("#stAdd")
    studio.click('#gallery button[data-effect="solid"]')
    studio.wait_for_function("() => window.__calls.some(c => c[0] === 'update_layers' && c[1][0].length === 1"
                             " && c[1][0][0].effect === 'solid')")
    (top,) = calls(studio, "update_layers")[-1][0]
    assert top["blend"] == "normal" and top["opacity"] == 1


def test_device_info_says_onboard_profile(page):  # noqa: F811
    page.locator("header .gear").click()
    expect(page.locator("#devInfo")).to_contain_text("Onboard profile")
    expect(page.locator("#devInfo")).not_to_contain_text("Stored profile")


# ---------- review fixes ----------

def test_apply_to_the_minority_depth_names_the_keys_that_change(page):  # noqa: F811
    set_depth(page, "1.0")                                                     # WASD are at 1.0, the rest at 2.0
    page.click("#applyDepth")
    body = page.locator("#caBody")
    expect(page.locator("#confirmApply")).to_be_visible()
    expect(body).to_contain_text("99 keys will change from 2.0 mm to 1.0 mm")
    expect(body).to_contain_text("W, A, S, D already type at 1.0 mm")
    expect(body).not_to_contain_text("are at 1.0 mm now")
    page.locator('#confirmApply button[value="apply"]').click()
    (args,) = wait_for_call(page, "set_depth")
    assert args[0] == [] and args[1] == 1.0
    assert page.errors == []


def test_apply_to_the_majority_depth_names_the_few_keys_that_change(page):  # noqa: F811
    page.click("#applyDepth")                                                  # untouched: 2.0, the most keys
    body = page.locator("#caBody")
    expect(body).to_contain_text("W, A, S, D will change from 1.0 mm to 2.0 mm")
    expect(body).to_contain_text("The other 99 keys already type at 2.0 mm")
    page.locator('#confirmApply button[value="cancel"]').click()
    assert calls(page, "set_depth") == []


def test_apply_does_not_ask_once_every_key_shares_the_depth_shown(page):  # noqa: F811
    page.click("#applyDepth")
    page.locator('#confirmApply button[value="apply"]').click()
    wait_for_call(page, "set_depth")
    expect(page.locator("#depthNum")).to_have_text("2.0")                      # one depth now
    set_depth(page, "1.0")
    page.click("#applyDepth")
    page.wait_for_function("() => window.__calls.filter(c => c[0] === 'set_depth').length === 2")
    expect(page.locator("#confirmApply")).to_be_hidden()
    assert calls(page, "set_depth")[-1][1] == 1.0


def test_no_depth_preset_is_pressed_while_the_readout_says_mixed(page):  # noqa: F811
    expect(page.locator("#depthNum")).to_have_text("Mixed")
    expect(page.locator('#presets button[aria-pressed="true"]')).to_have_count(0)
    page.click('#selectTools [data-sel="wasd"]')                               # WASD alone: 1.0, Gaming
    expect(page.locator('#presets button[aria-pressed="true"]')).to_have_count(1)
    expect(page.locator('#presets button[aria-pressed="true"]')).to_have_attribute("data-v", "1")


def test_snap_tap_pick_order_starts_over_after_leaving_the_tab_or_reconnecting(page):  # noqa: F811
    page.click('.tabs button[data-view="snap"]')
    cap(page, "Q").click()
    expect(page.locator("#stageNote")).to_contain_text("second key")
    page.click('.tabs button[data-view="lighting"]')
    page.click('.tabs button[data-view="snap"]')
    expect(page.locator("#stageNote")).not_to_contain_text("Now click the second key")
    cap(page, "E").click()
    expect(page.locator("#snapA")).to_have_value(str(IDS["E"]))               # the first key again
    page.evaluate('reconnect($("#reload"))')
    expect(page.locator("#toast")).to_have_text("Connected to Huntsman V3 Pro")
    expect(page.locator("#stageNote")).not_to_contain_text("Now click the second key")
    cap(page, "R").click()
    expect(page.locator("#snapA")).to_have_value(str(IDS["R"]))
    assert page.errors == []


def test_focus_moves_to_reconnect_when_the_keyboard_goes_away(page):  # noqa: F811
    page.locator("#applyDepth").focus()                                        # in the Actuation pane
    expect(page.locator("#applyDepth")).to_be_focused()
    page.evaluate("model = null; noKbUi()")
    expect(page.locator("#emptyReconnect")).to_be_focused()
    assert page.errors == []


def test_focus_stays_put_when_it_was_outside_the_panes(page):  # noqa: F811
    page.locator('.tabs button[data-view="lighting"]').focus()
    page.evaluate("model = null; noKbUi()")
    expect(page.locator('.tabs button[data-view="lighting"]')).to_be_focused()


def test_apply_with_a_custom_reset_names_keys_that_only_get_a_new_reset_point(page):  # noqa: F811
    page.select_option("#relMode", "custom")
    set_depth(page, "1.0")
    page.locator("#rel").evaluate("e => { e.value = 0.5; e.dispatchEvent(new Event('input', {bubbles: true})); }")
    page.click("#applyDepth")
    body = page.locator("#caBody")
    expect(body).to_contain_text("99 keys will change from 2.0 mm to 1.0 mm, resetting at 0.5 mm.")
    expect(body).to_contain_text("W, A, S, D keep 1.0 mm and get a new reset point at 0.5 mm.")
    expect(body).not_to_contain_text("already")
    page.locator('#confirmApply button[value="cancel"]').click()


def test_focus_on_the_board_moves_to_reconnect_when_the_keyboard_goes_away(page):  # noqa: F811
    cap(page, "W").focus()
    page.evaluate("model = null; noKbUi()")
    expect(page.locator("#emptyReconnect")).to_be_focused()
