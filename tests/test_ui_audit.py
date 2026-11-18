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
