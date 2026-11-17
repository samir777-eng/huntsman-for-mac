# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Other Huntsman models in the window (demo mode, headless Chromium): the model name and Experimental badge,
the Experimental support switch, tabs hidden for features a model lacks, write controls locked until the switch
is on, the LED check, and the on-screen keyboard following the model's layout. Every call to the Python side is
recorded (test_ui's RECORDER)."""
import json

import pytest

from test_ui import RECORDER, ROOT, browser, calls, sync_api, wait_for_call  # noqa: F401  (fixtures)

expect = sync_api.expect
BASE = (ROOT / "ui" / "index.html").as_uri() + "?demo"
TABS = ["actuation", "rapid", "snap", "lighting", "studio", "tester"]


def layout_of(pid):
    path = ROOT / ("layout.json" if pid == "02A6" else f"layouts/{pid}.json")
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def open_model(browser):  # noqa: F811
    pages = []

    def go(pid=None):
        pg = browser.new_page(viewport={"width": 1280, "height": 900})
        pg.errors = []
        pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.add_init_script(RECORDER)
        pg.goto(BASE + (f"&model={pid}" if pid else ""))
        expect(pg.locator("#conn")).to_have_text("Connected, firmware 1.03")
        pages.append(pg)
        return pg
    yield go
    for pg in pages:
        pg.close()


def visible_tabs(page):
    return [t for t in TABS if page.locator(f'#sources button[data-view="{t}"]').is_visible()]


def test_the_v3_pro_looks_as_before(open_model):
    page = open_model()
    expect(page.locator(".device-name")).to_have_text("Huntsman V3 Pro")
    expect(page.locator("#expBadge")).to_be_hidden()
    assert visible_tabs(page) == TABS
    page.click('button[data-view="device"]')
    expect(page.locator("#expBox")).to_be_hidden()
    expect(page.locator("#devInfo")).to_contain_text("1532:02A6")
    expect(page.locator(".lock-note:visible")).to_have_count(0)
    assert page.locator(".cap").count() == 104 and page.errors == []


def test_experimental_model_shows_its_name_and_badge(open_model):
    page = open_model("02A7")
    expect(page.locator(".device-name")).to_have_text("Huntsman V3 Pro TKL")
    expect(page.locator("#expBadge")).to_be_visible()
    expect(page.locator("#expBadge")).to_have_text("Experimental")
    assert visible_tabs(page) == ["actuation", "rapid", "snap", "lighting", "studio"]   # never the key tester
    expect(page.locator("#actTest")).to_be_hidden()
    page.click('button[data-view="device"]')
    expect(page.locator("#devInfo")).to_contain_text("1532:02A7")
    assert page.errors == []


def test_v2_hides_the_analog_tabs_and_opens_on_lighting(open_model):
    page = open_model("026C")
    assert visible_tabs(page) == ["lighting", "studio"]
    expect(page.locator('.pane[data-pane="lighting"]')).to_be_visible()
    page.click('button[data-view="device"]')
    expect(page.locator("#restore")).to_be_hidden()   # no depth to restore
    assert page.errors == []


def test_mini_layout_renders(open_model):
    page = open_model("02B0")
    keys = layout_of("02B0")
    assert page.locator(".cap").count() == len(keys) == 61
    ids = {int(i) for i in page.locator(".cap").evaluate_all("cs => cs.map(c => c.dataset.id)")}
    assert ids == {k["id"] for k in keys}
    expect(page.locator(".kb-extras")).to_be_hidden()   # no media keys or dial on the Mini
    width = float(page.locator("#board").evaluate("b => parseFloat(b.style.width)"))
    assert width < 16 * 46
    page.click('#selectTools button[data-sel="arrows"]')   # the Mini has no arrow keys: selects nothing
    expect(page.locator(".cap.sel")).to_have_count(0)
    assert page.errors == []


def test_locked_until_the_switch_is_on(open_model):
    page = open_model("02B0")
    note = page.locator('.pane[data-pane="actuation"] .lock-note')
    expect(note).to_be_visible()
    expect(note).to_contain_text("Experimental support")
    expect(page.locator("#applyDepth")).to_be_disabled()
    page.click('button[data-view="lighting"]')
    page.locator(".cap").nth(20).click()
    expect(page.locator("#paintSel")).to_be_disabled()
    expect(page.locator("#bright")).to_be_disabled()
    page.click('button[data-view="studio"]')
    expect(page.locator("#stOn")).to_be_disabled()
    # the note's link opens the Keyboard pane with the switch
    page.locator('.pane[data-pane="studio"] .lock-note button').click()
    expect(page.locator("#expBox")).to_be_visible()
    expect(page.locator("#expWarn")).to_contain_text("hasn't been tested")
    expect(page.locator("#expWarn")).to_contain_text("key tester stays off")
    expect(page.locator("#ledBox")).to_be_hidden()
    page.check("#expOn")
    assert wait_for_call(page, "set_experimental")[-1] == [True]
    expect(page.locator("#ledBox")).to_be_visible()
    page.click('button[data-view="lighting"]')
    expect(page.locator(".lock-note:visible")).to_have_count(0)
    expect(page.locator("#paintSel")).to_be_enabled()
    page.click("#paintSel")
    wait_for_call(page, "set_custom")
    page.click('button[data-view="device"]')
    page.uncheck("#expOn")
    page.wait_for_function("() => window.__calls.filter(c => c[0] === 'set_experimental').length === 2")
    assert calls(page, "set_experimental")[-1] == [False]
    page.click('button[data-view="actuation"]')
    expect(page.locator("#applyDepth")).to_be_disabled()
    assert page.errors == []


def test_led_check_steps_through_the_matrix(open_model):
    page = open_model("02B0")
    page.click('button[data-view="device"]')
    page.check("#expOn")
    expect(page.locator("#ledBox")).to_be_visible()
    expect(page.locator("#ledRow option")).to_have_count(5)
    expect(page.locator("#ledCol option")).to_have_count(15)
    page.click("#ledStart")
    assert wait_for_call(page, "led_check")[-1] == [0, 0]
    expect(page.locator("#ledCell")).to_have_text("Row 0, column 0")
    page.fill("#ledKey", "Esc")
    page.click("#ledNext")
    expect(page.locator("#ledCell")).to_have_text("Row 0, column 1")
    assert calls(page, "led_check")[-1] == [0, 1]
    page.fill("#ledKey", "1")
    page.click("#ledPrev")
    expect(page.locator("#ledKey")).to_have_value("Esc")   # what was typed for that cell comes back
    page.click("#ledPrev")                                   # wraps to the last cell
    expect(page.locator("#ledCell")).to_have_text("Row 4, column 14")
    assert calls(page, "led_check")[-1] == [4, 14]
    page.click("#ledNext")
    expect(page.locator("#ledCell")).to_have_text("Row 0, column 0")
    page.select_option("#ledRow", "2")
    page.select_option("#ledCol", "7")
    expect(page.locator("#ledCell")).to_have_text("Row 2, column 7")
    assert calls(page, "led_check")[-1] == [2, 7]
    report = page.locator("#ledReport").input_value()
    assert "Huntsman V3 Pro Mini (1532:02B0)" in report and "firmware 1.03" in report
    assert "Row 0, column 0: Esc" in report and "Row 0, column 1: 1" in report
    page.click("#ledStop")
    wait_for_call(page, "end_led_check")
    expect(page.locator("#ledStart")).to_be_visible()
    assert page.errors == []


def test_demo_model_picker(open_model):
    page = open_model()
    picker = page.locator("#demoModel")
    expect(picker).to_be_visible()
    expect(picker.locator("option")).to_have_count(7)
    picker.select_option("02B0")
    page.wait_for_url("**model=02B0**")
    expect(page.locator(".device-name")).to_have_text("Huntsman V3 Pro Mini")


# ---------- no keyboard at start, then Reconnect ----------

@pytest.fixture
def unplugged(browser):  # noqa: F811
    """?demo&model=none: no keyboard answers; Reconnect plugs in `plug` (demo only)."""
    pages = []

    def go(plug=None):
        pg = browser.new_page(viewport={"width": 1280, "height": 900})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.add_init_script(RECORDER)
        pg.goto(BASE + "&model=none" + (f"&plug={plug}" if plug else ""))
        expect(pg.locator("#conn")).to_have_text("Not connected")
        pages.append(pg)
        return pg
    yield go
    for pg in pages:
        pg.close()


def reconnect(page):
    page.click('button[data-view="device"]')
    page.click("#reload")


def test_no_keyboard_claims_no_features(unplugged):
    page = unplugged()
    assert visible_tabs(page) == ["lighting", "studio"]   # nothing that needs a model's feature
    expect(page.locator('.pane[data-pane="lighting"]')).to_be_visible()
    expect(page.locator("#expBadge")).to_be_hidden()
    page.click('button[data-view="device"]')
    expect(page.locator("#expBox")).to_be_hidden()
    expect(page.locator("#ledBox")).to_be_hidden()
    expect(page.locator("#restore")).to_be_hidden()
    assert page.errors == []


def test_reconnect_picks_up_a_model_plugged_in_later(unplugged):
    page = unplugged("02B0")
    assert page.locator(".cap").count() == 104       # the default layout until a keyboard answers
    reconnect(page)
    expect(page.locator("#conn")).to_have_text("Connected, firmware 1.03")
    expect(page.locator(".device-name")).to_have_text("Huntsman V3 Pro Mini")
    expect(page.locator("#expBadge")).to_be_visible()
    expect(page.locator(".cap")).to_have_count(61)
    ids = {int(i) for i in page.locator(".cap").evaluate_all("cs => cs.map(c => c.dataset.id)")}
    assert ids == {k["id"] for k in layout_of("02B0")}
    assert visible_tabs(page) == ["actuation", "rapid", "snap", "lighting", "studio"]
    expect(page.locator(".pane[data-pane=\"actuation\"] .lock-note")).to_have_count(1)
    assert len(calls(page, "layout")) == 2 and len(calls(page, "effects")) == 2
    expect(page.locator("#expBox")).to_be_visible()
    assert page.errors == []


def test_reconnect_to_a_model_with_fewer_effects_refills_the_list(unplugged):
    page = unplugged("0266")     # the V2 Analog has no starlight effects
    assert page.locator('#effect option[value="starlight_one"]').count() == 1
    reconnect(page)
    expect(page.locator(".device-name")).to_have_text("Huntsman V2 Analog")
    expect(page.locator('#effect option[value="starlight_one"]')).to_have_count(0)
    expect(page.locator('#effect option[value="spectrum"]')).to_have_count(1)
    assert page.errors == []


def test_reconnect_to_the_same_model_keeps_the_layout(open_model):
    page = open_model()
    reconnect(page)
    page.wait_for_function("() => window.__calls.filter(c => c[0] === 'model').length >= 2")
    expect(page.locator("#conn")).to_have_text("Connected, firmware 1.03")
    assert len(calls(page, "layout")) == 1 and len(calls(page, "effects")) == 1
    assert page.locator(".cap").count() == 104 and page.errors == []
