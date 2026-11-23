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
# The key tester starts by itself on Actuation, so start_test answers without the demo's simulated presses (a test
# feeds its own depth readings), and window.__front = {focus, visible} stands in for the window being in front.
# The saved interface preferences (state.ui) are window.__ui: by default the window was last on Actuation and the
# live view's one-time explanation was seen; window.__ui = {} is a first launch. Text drawn on canvases goes to
# window.__texts.
RECORDER = """
window.__calls = [];
window.__override = { start_test: () => Promise.resolve({ok: true, data: true}) };
window.__front = { focus: true, visible: true };
window.__ui = { tab: "actuation", liveSeen: true };
window.__texts = [];
Document.prototype.hasFocus = () => window.__front.focus;
Object.defineProperty(Document.prototype, "visibilityState", { get: () => window.__front.visible ? "visible" : "hidden" });
const fillText = CanvasRenderingContext2D.prototype.fillText;
CanvasRenderingContext2D.prototype.fillText = function (t, ...a) { window.__texts.push(String(t)); return fillText.call(this, t, ...a); };
addEventListener("pywebviewready", () => {
  const api = window.pywebview.api;
  const info = api.info;
  api.info = (...a) => info(...a).then(r => { if (r.ok) r.data.state.ui = { ...(r.data.state.ui || {}), ...window.__ui }; return r; });
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
    page.click('#confirmApply button[value="apply"]')   # W, A, S and D use another depth: asked first
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
    page.click('button[data-view="lighting"]')
    cap(page, "Q").click()                                  # selected on Per key
    page.click("#tabEffect")
    page.select_option("#effect", "wave")
    cap(page, "E").click()                                  # an effect doesn't select: it lights every key
    sync_api.expect(page.locator(".cap.sel")).to_have_count(0)
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


def front(page, focus=True, visible=True):
    """The window comes to the front or goes away: focus/blur and visibilitychange, as WebKit sends them."""
    page.evaluate("""([f, v]) => { const was = window.__front; window.__front = {focus: f, visible: v};
      if (was.visible !== v) document.dispatchEvent(new Event("visibilitychange"));
      if (was.focus !== f) window.dispatchEvent(new Event(f ? "focus" : "blur")); }""", [focus, visible])


def count(page, name):
    return len(calls(page, name))


def test_no_test_button(page):
    assert page.locator("#actTest").count() == 0 and page.locator("#bannerStop").count() == 0


def test_key_tester_starts_by_itself_on_actuation(page):
    wait_for_call(page, "start_test")
    sync_api.expect(page.locator("#testBanner")).to_be_visible()
    sync_api.expect(page.locator("#traceWrap")).to_be_visible()
    sync_api.expect(page.locator("#liveNote")).to_contain_text("Live view on")
    sync_api.expect(page.locator("#testBanner")).to_contain_text("Click another window to type again")
    page.wait_for_timeout(600)
    assert count(page, "start_test") == 1 and count(page, "stop_test") == 0   # no repeats
    assert page.errors == []


def test_keys_stay_selectable_while_live(page):
    wait_for_call(page, "start_test")
    cap(page, "W").click()
    sync_api.expect(cap(page, "W")).to_have_class(re.compile(r"\bsel\b"))
    sync_api.expect(page.locator("#actScope")).to_contain_text("1 selected key")


def test_apply_while_live_keeps_testing(page):
    """Today's behaviour, kept: Apply writes while the tester runs and the tester carries on."""
    wait_for_call(page, "start_test")
    page.click("#applyDepth")
    page.click('#confirmApply button[value="apply"]')   # W, A, S and D use another depth: asked first
    wait_for_call(page, "set_depth")
    sync_api.expect(page.locator("#testBanner")).to_be_visible()
    assert count(page, "stop_test") == 0


def test_readings_follow_the_last_key(page):
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


def test_switching_tab_stops_and_coming_back_restarts(page):
    wait_for_call(page, "start_test")
    page.click('button[data-view="lighting"]')
    wait_for_call(page, "stop_test")
    sync_api.expect(page.locator("#testBanner")).to_be_hidden()
    sync_api.expect(page.locator("#traceWrap")).to_be_hidden()
    page.wait_for_timeout(500)
    assert count(page, "start_test") == 1
    page.click('button[data-view="actuation"]')
    page.wait_for_function("() => window.__calls.filter(c => c[0] === 'start_test').length === 2")
    sync_api.expect(page.locator("#testBanner")).to_be_visible()


def test_tab_change_while_the_test_starts_stops_it(browser):
    """start_test is slow; the user opens Lighting before it answers. The test must not keep running there."""
    pg = browser.new_page()
    pg.add_init_script(RECORDER)
    pg.add_init_script("window.__override.start_test = () => new Promise(r => setTimeout(() => r({ok: true, data: true}), 600))")
    pg.goto(URL)
    wait_for_call(pg, "start_test")
    pg.click('button[data-view="lighting"]')
    wait_for_call(pg, "stop_test")
    sync_api.expect(pg.locator("#testBanner")).to_be_hidden()
    pg.close()


def test_no_start_while_the_window_is_not_in_front(browser):
    for f, v in [(False, True), (True, False)]:
        pg = browser.new_page()
        pg.add_init_script(RECORDER)
        pg.add_init_script(f"window.__front = {{focus: {str(f).lower()}, visible: {str(v).lower()}}}")
        pg.goto(URL)
        sync_api.expect(pg.locator("#conn")).to_have_text("Connected, firmware 1.03")
        pg.wait_for_timeout(700)
        assert count(pg, "start_test") == 0
        sync_api.expect(pg.locator("#liveNote")).to_contain_text("isn't in front")
        front(pg)                                           # comes to the front: starts
        wait_for_call(pg, "start_test")
        pg.close()


def test_blur_stops_and_focus_restarts(page):
    wait_for_call(page, "start_test")
    front(page, focus=False)
    wait_for_call(page, "stop_test")
    sync_api.expect(page.locator("#testBanner")).to_be_hidden()
    sync_api.expect(page.locator("#liveNote")).to_contain_text("The Huntsman types normally")
    front(page)
    page.wait_for_function("() => window.__calls.filter(c => c[0] === 'start_test').length === 2")


def test_quick_blur_and_focus_switch_nothing(page):
    wait_for_call(page, "start_test")
    page.wait_for_timeout(100)
    for _ in range(3):
        front(page, focus=False)
        page.wait_for_timeout(50)
        front(page)
    page.wait_for_timeout(800)
    assert count(page, "start_test") == 1 and count(page, "stop_test") == 0


def test_hidden_stops_at_once_and_visible_restarts(page):
    wait_for_call(page, "start_test")
    front(page, visible=False)
    wait_for_call(page, "stop_test")
    front(page)
    page.wait_for_function("() => window.__calls.filter(c => c[0] === 'start_test').length === 2")


def test_idle_stop_waits_for_focus_or_a_click(page):
    wait_for_call(page, "start_test")
    page.evaluate("window.onTestEnded('Live view paused after 5 minutes without a key press.', true)")
    sync_api.expect(page.locator("#testBanner")).to_be_hidden()
    sync_api.expect(page.locator("#liveNote")).to_contain_text("5 minutes without a key press")
    go = page.locator("#traceResume")
    sync_api.expect(go).to_have_text("Resume")
    page.click('button[data-view="lighting"]')         # coming back to the tab counts as asking again
    page.click('button[data-view="actuation"]')
    page.wait_for_function("() => window.__calls.filter(c => c[0] === 'start_test').length === 2")
    page.evaluate("window.onTestEnded('Live view paused after 5 minutes without a key press.', true)")
    page.wait_for_timeout(700)
    assert count(page, "start_test") == 2                # paused: no restart by itself
    go.click()
    page.wait_for_function("() => window.__calls.filter(c => c[0] === 'start_test').length === 3")
    page.evaluate("window.onTestEnded('Live view paused after 5 minutes without a key press.', true)")
    front(page, focus=False)
    front(page)                                          # focus again also resumes
    page.wait_for_function("() => window.__calls.filter(c => c[0] === 'start_test').length === 4")


def test_start_failure_shows_try_again_and_no_retry_loop(browser):
    pg = browser.new_page()
    pg.add_init_script(RECORDER)
    pg.add_init_script("window.__override.start_test = () => Promise.resolve({ok: false, error: 'Allow Input Monitoring for this app.', reason: 'permission'})")
    pg.goto(URL)
    wait_for_call(pg, "start_test")
    sync_api.expect(pg.locator("#liveNote")).to_contain_text("Allow Input Monitoring for this app.")
    sync_api.expect(pg.locator("#liveGo")).to_have_text("Try again")
    sync_api.expect(pg.locator("#conn")).to_have_text("Connected, firmware 1.03")   # not a lost connection
    front(pg, focus=False)
    front(pg)                                            # focus again: still held, no retry
    pg.wait_for_timeout(1000)
    assert count(pg, "start_test") == 1
    sync_api.expect(pg.locator("#toast")).not_to_contain_text("Allow Input Monitoring")   # the panel says it, once
    pg.click("#liveGo")
    pg.wait_for_function("() => window.__calls.filter(c => c[0] === 'start_test').length === 2")
    pg.wait_for_timeout(700)
    assert count(pg, "start_test") == 2
    pg.close()


def test_close_stops_the_tester(page):
    wait_for_call(page, "start_test")
    page.evaluate("dispatchEvent(new Event('beforeunload'))")
    wait_for_call(page, "stop_test")


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


def test_a_lock_while_live_stops_it_and_says_no_starting(page):
    wait_for_call(page, "start_test")
    page.evaluate("model.blocked = 'Quit Razer Synapse.'; lockUi()")   # writes become locked while live
    wait_for_call(page, "stop_test")
    sync_api.expect(page.locator("#testBanner")).to_be_hidden()
    sync_api.expect(page.locator("#liveNote")).not_to_contain_text("Starting")
