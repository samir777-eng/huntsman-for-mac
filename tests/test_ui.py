# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Smoke tests for the window (ui/) in demo mode, driven by a headless Chromium through Playwright.

Every call the page makes to the Python side (window.pywebview.api) is recorded, so the tests can
check what the interface would send to the keyboard. No keyboard, USB or app process is involved.
Skipped when Playwright isn't installed (pip install -r requirements-dev.txt; playwright install chromium).
"""
import json
import pathlib
import re

import pytest

sync_api = pytest.importorskip("playwright.sync_api", exc_type=ImportError)

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = (ROOT / "ui" / "index.html").as_uri() + "?demo"
with open(ROOT / "layout.json") as f:
    IDS = {k["name"]: k["id"] for k in json.load(f)}

# Runs before the page's own scripts: its pywebviewready listener is registered first, so every api
# method is wrapped before app.js calls any of them. window.__override[name] replaces a method's result.
RECORDER = """
window.__calls = [];
window.__override = {};
addEventListener("pywebviewready", () => {
  const api = window.pywebview.api;
  for (const name of Object.keys(api)) {
    const real = api[name];
    api[name] = (...args) => {
      window.__calls.push([name, JSON.parse(JSON.stringify(args))]);
      return (window.__override[name] || real)(...args);
    };
  }
});
"""


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except sync_api.Error as e:  # Playwright installed but its browser isn't
            pytest.skip(f"Chromium for Playwright isn't installed (python -m playwright install chromium): {e}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page(viewport={"width": 1280, "height": 900})
    pg.errors = []
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.add_init_script(RECORDER)
    pg.goto(URL)
    sync_api.expect(pg.locator("#conn")).to_have_text("Connected, firmware 1.03")
    yield pg
    pg.close()


def calls(page, name):
    return [args for n, args in page.evaluate("window.__calls") if n == name]


def wait_for_call(page, name):
    page.wait_for_function("n => window.__calls.some(c => c[0] === n)", arg=name)
    return calls(page, name)


def cap(page, name):
    return page.locator(f'.cap[data-id="{IDS[name]}"]')


def legend(page, name):
    return cap(page, name).evaluate("c => c.style.getPropertyValue('--legend')")


def test_loads_without_console_errors(page):
    assert page.locator(".cap").count() == len(IDS)
    assert page.errors == []


def test_apply_depth_sends_only_selected(page):
    cap(page, "Q").click()
    cap(page, "E").click()
    sync_api.expect(page.locator("#applyDepth")).to_have_text("Apply to 2 keys")
    page.click("#applyDepth")
    (args,) = wait_for_call(page, "set_depth")
    assert sorted(args[0]) == sorted([IDS["Q"], IDS["E"]])


def test_apply_depth_no_selection_sends_empty(page):
    page.click("#applyDepth")
    (args,) = wait_for_call(page, "set_depth")
    assert args[0] == []


def open_effects(page, effect):
    page.click('button[data-view="lighting"]')
    page.click("#tabEffect")
    page.select_option("#effect", effect)


def test_static_effect_with_selection_paints_only_selected(page):
    before = page.evaluate("window.pywebview.api.info()")["data"]["state"]["custom"]
    open_effects(page, "static")
    page.fill("#c1", "#00ff00")
    cap(page, "Q").click()
    cap(page, "E").click()
    sync_api.expect(page.locator("#applyFx")).to_have_text("Apply to 2 keys")
    page.click("#applyFx")
    (args,) = wait_for_call(page, "set_custom")
    base, keys = args
    assert base == before["base"]
    expected = dict(before["keys"])
    expected.update({str(IDS["Q"]): [0, 255, 0], str(IDS["E"]): [0, 255, 0]})
    assert keys == expected
    assert calls(page, "set_effect") == []
    assert legend(page, "Q") == "#00ff00" and legend(page, "R") == "#ffffff"


def test_wave_with_selection_calls_set_effect_and_warns(page):
    open_effects(page, "wave")
    cap(page, "Q").click()
    sync_api.expect(page.locator("#fxNote")).to_contain_text("Effects light the whole keyboard")
    sync_api.expect(page.locator("#applyFx")).to_have_text("Apply to whole keyboard")
    page.click("#applyFx")
    (args,) = wait_for_call(page, "set_effect")
    assert args[0] == "wave"
    assert calls(page, "set_custom") == []


def test_key_tester_tab_is_gone(page):
    assert page.locator('[data-view="tester"]').count() == 0
    assert page.locator('[data-pane="tester"]').count() == 0
    assert page.locator("#testToggle").count() == 0


def quiet_tester(page):
    """start_test succeeds without the demo's simulated presses, so a test feeds its own depth readings."""
    page.evaluate("window.__override.start_test = () => Promise.resolve({ok: true, data: true})")


def test_actuation_test_button_starts_and_stops_one_session(page):
    banner, btn = page.locator("#testBanner"), page.locator("#actTest")
    sync_api.expect(btn).to_have_text("Test with a key press")
    sync_api.expect(page.locator("#actReadings")).to_be_visible()
    sync_api.expect(page.locator("#actReadings")).to_contain_text("sends travel readings instead of typing")
    sync_api.expect(banner).to_be_hidden()
    sync_api.expect(page.locator("#traceWrap")).to_be_hidden()
    btn.click()
    wait_for_call(page, "start_test")
    sync_api.expect(banner).to_be_visible()
    sync_api.expect(btn).to_have_text("Stop testing")
    sync_api.expect(page.locator("#traceWrap")).to_be_visible()
    btn.click()
    wait_for_call(page, "stop_test")
    sync_api.expect(banner).to_be_hidden()
    sync_api.expect(btn).to_have_text("Test with a key press")
    sync_api.expect(page.locator("#traceWrap")).to_be_hidden()
    assert len(calls(page, "start_test")) == 1 and len(calls(page, "stop_test")) == 1
    assert page.errors == []


def test_readings_follow_the_last_key(page):
    quiet_tester(page)
    page.click("#actTest")
    wait_for_call(page, "start_test")
    w = IDS["W"]
    page.evaluate(f"window.onDepth([[{w}, 1.2]])")
    page.evaluate(f"window.onDepth([[{w}, 2.6]])")
    sync_api.expect(cap(page, "W").locator(".front")).to_have_text("2.60")   # live travel on the key, as the tab showed
    page.evaluate(f"window.onDepth([[{w}, 0.4]])")
    sync_api.expect(page.locator("#tPeak")).to_have_text("2.60 mm")
    sync_api.expect(page.locator("#mKey")).to_have_text("Key W")
    sync_api.expect(page.locator("#mNum")).to_have_text("0.40")
    act = page.locator("#tAct").inner_text()
    rel = page.locator("#tRel").inner_text()
    assert act.endswith(" mm") and rel.endswith(" mm")
    page.evaluate("window.onDepth([])")
    sync_api.expect(cap(page, "W").locator(".front")).to_have_text(act.split()[0])   # back to its actuation point
    assert page.errors == []


def test_switching_tab_stops_the_test(page):
    page.click("#actTest")
    wait_for_call(page, "start_test")
    page.click('button[data-view="lighting"]')
    wait_for_call(page, "stop_test")
    sync_api.expect(page.locator("#testBanner")).to_be_hidden()
    sync_api.expect(page.locator("#traceWrap")).to_be_hidden()
    page.click('button[data-view="actuation"]')
    sync_api.expect(page.locator("#actTest")).to_have_text("Test with a key press")
    assert len(calls(page, "start_test")) == 1


def test_failed_paint_keeps_previous_colours(page):
    page.evaluate('window.__override.set_custom = () => Promise.resolve({ok: false, error: "No reply"})')
    page.click('button[data-view="lighting"]')
    old_q, old_w = legend(page, "Q"), legend(page, "W")
    cap(page, "Q").click()
    cap(page, "W").click()
    page.fill("#paint", "#0000ff")
    page.click("#paintSel")
    wait_for_call(page, "set_custom")
    sync_api.expect(page.locator("#toast")).to_have_text("No reply")
    assert (legend(page, "Q"), legend(page, "W")) == (old_q, old_w)
    # the next paint starts from the colours the keyboard confirmed, not from the failed draft
    page.evaluate("delete window.__override.set_custom")
    page.click("#eraseSel")
    page.wait_for_function("() => window.__calls.filter(c => c[0] === 'set_custom').length === 2")
    _, keys = calls(page, "set_custom")[1]
    assert str(IDS["Q"]) not in keys and str(IDS["W"]) not in keys and str(IDS["A"]) in keys


def test_progress_bar_follows_long_reads(page):
    bar = page.locator("#progress")
    sync_api.expect(bar).to_be_hidden()
    page.evaluate("window.onProgress(3, 10)")
    sync_api.expect(bar).to_be_visible()
    assert page.locator("#progress").get_attribute("aria-valuenow") == "30"
    page.evaluate("window.onProgress(10, 10)")
    sync_api.expect(bar).to_be_hidden()
    assert page.errors == []



def test_keyboard_pane_shows_the_app_version(page):
    page.click('button[data-view="device"]')
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / "huntsman_core.py").read_text()).group(1)
    sync_api.expect(page.locator("#devInfo")).to_contain_text("App version" + version)
