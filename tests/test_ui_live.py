# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""UX audit of the live key tester (2026-11-22): the first tab, a stable layout, one message, screen readers,
Input Monitoring, the paused chip, the readings title, the trace label, the toast and the "Starting" flash.
Demo mode in headless Chromium, every call recorded (test_ui's RECORDER)."""
import re

import pytest

from test_ui import IDS, RECORDER, URL, browser, calls, cap, front, page, sync_api, wait_for_call  # noqa: F401

expect = sync_api.expect


def open_with(browser, w=1280, h=900, init=""):  # noqa: F811
    pg = browser.new_page(viewport={"width": w, "height": h})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.add_init_script(RECORDER)
    if init:
        pg.add_init_script(init)
    pg.goto(URL)
    expect(pg.locator("#conn")).to_have_text("Connected, firmware 1.03")
    return pg


@pytest.fixture
def opened(browser):  # noqa: F811
    pages = []

    def go(**kw):
        pg = open_with(browser, **kw)
        pages.append(pg)
        return pg
    yield go
    for pg in pages:
        pg.close()


def box(loc):
    return loc.evaluate("e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }")


# ---------- 1. the first tab, the last tab, the one-time explanation ----------

def test_first_launch_opens_lighting_and_the_huntsman_keeps_typing(opened):
    pg = opened(init="window.__ui = {}")
    expect(pg.locator('#sources button[data-view="lighting"]')).to_have_attribute("aria-current", "page")
    pg.wait_for_timeout(700)
    assert calls(pg, "start_test") == []


def test_the_last_tab_is_remembered(opened):
    pg = opened(init="window.__ui = {tab: 'snap', liveSeen: true}")
    expect(pg.locator('#sources button[data-view="snap"]')).to_have_attribute("aria-current", "page")
    pg.click('#sources button[data-view="rapid"]')
    pg.wait_for_function("() => window.__calls.some(c => c[0] === 'set_prefs' && c[1][0].tab === 'rapid')")


def test_the_first_live_view_explains_itself_once(opened):
    pg = opened(init="window.__ui = {tab: 'actuation'}")
    wait_for_call(pg, "start_test")
    intro = pg.locator("#liveIntro")
    expect(intro).to_be_visible()
    expect(intro).to_contain_text("Click another window to type again")
    pg.wait_for_function("() => window.__calls.some(c => c[0] === 'set_prefs' && c[1][0].liveSeen === true)")
    intro.locator("button").click()
    expect(intro).to_be_hidden()


def test_the_explanation_doesnt_come_back(page):
    wait_for_call(page, "start_test")
    expect(page.locator("#liveIntro")).to_be_hidden()


# ---------- 2, 3. the layout stays put; a short window keeps the presets in view ----------

def test_the_layout_doesnt_jump_when_the_window_loses_focus(page):
    wait_for_call(page, "start_test")
    expect(page.locator("#traceWrap")).to_be_visible()
    before = box(cap(page, "ESC")), box(page.locator("#presets"))
    front(page, focus=False)
    wait_for_call(page, "stop_test")
    expect(page.locator("#traceWrap")).to_have_class(re.compile(r"\bpaused\b"))
    expect(page.locator("#traceWrap")).to_be_visible()
    expect(page.locator("#actReadings")).to_be_visible()
    page.wait_for_timeout(200)
    after = box(cap(page, "ESC")), box(page.locator("#presets"))
    assert all(abs(a - b) <= 1 for x, y in zip(before, after) for a, b in zip(x, y)), (before, after)


def test_a_short_window_keeps_the_trace_small_and_the_presets_in_view(opened):
    pg = opened(w=1024, h=700)
    wait_for_call(pg, "start_test")
    h = pg.locator("#trace").evaluate("e => e.clientHeight")
    assert 110 <= h <= 0.22 * 700 + 1
    assert h < box(pg.locator("#board"))[3] - box(pg.locator("#board"))[1]   # never taller than the board
    expect(pg.locator("#presets")).to_be_in_viewport()
    expect(pg.locator("#applyDepth")).to_be_in_viewport()
    assert box(pg.locator("#presets"))[3] <= box(pg.locator("#applyDepth"))[1]   # not under the sticky Apply


# ---------- 4, 5, 12. one message; one live region; no "Starting" flash ----------

def test_the_message_is_said_once(page):
    wait_for_call(page, "start_test")
    expect(page.locator("#testBanner")).to_contain_text("Click another window to type again")
    assert page.locator("#actReadings .warn").count() == 0
    expect(page.locator("#liveText")).to_have_text("Live view on.")


def test_only_the_status_line_is_a_live_region(page):
    assert page.locator("#testBanner").get_attribute("role") is None
    assert page.locator("#mHit").get_attribute("aria-live") is None
    assert page.locator("#liveNote").get_attribute("role") == "status"


def test_starting_shows_only_when_it_takes_a_while(opened):
    pg = opened(init="window.__override.start_test = () => new Promise(r => setTimeout(() => r({ok: true, data: true}), 1500))")
    wait_for_call(pg, "start_test")
    pg.wait_for_timeout(150)
    expect(pg.locator("#traceChip")).not_to_contain_text("Starting")
    expect(pg.locator("#traceChip")).to_contain_text("Starting live view")        # after ~400 ms
    expect(pg.locator("#liveNote")).not_to_contain_text("Starting")              # never announced
    expect(pg.locator("#liveNote")).to_contain_text("Live view on")


# ---------- 6. Input Monitoring refused ----------

def test_permission_refused_offers_privacy_settings(opened):
    pg = opened(init="window.__override.start_test = () => Promise.resolve({ok: false, reason: 'permission', "
                     "error: 'Allow Input Monitoring for this app in System Settings.'})")
    wait_for_call(pg, "start_test")
    note = pg.locator("#liveNote")
    expect(note).to_have_class(re.compile(r"\bnotice\b"))
    expect(pg.locator("#liveGo")).to_have_text("Try again")
    pg.click("#livePrivacy")
    wait_for_call(pg, "open_privacy")


def test_other_failures_offer_no_privacy_settings(opened):
    pg = opened(init="window.__override.start_test = () => Promise.resolve({ok: false, reason: 'unavailable', error: 'The keyboard is busy.'})")
    wait_for_call(pg, "start_test")
    expect(pg.locator("#liveGo")).to_be_visible()
    expect(pg.locator("#livePrivacy")).to_be_hidden()


# ---------- 7, 8. "Live view"; resume from the chip only ----------

def test_idle_pause_says_live_view_and_resumes_only_from_the_chip(page):
    wait_for_call(page, "start_test")
    page.evaluate("window.onTestEnded('Live view paused after 5 minutes without a key press.', true)")
    expect(page.locator("#liveNote")).to_contain_text(
        "Live view paused after 5 minutes without a key press. The Huntsman types normally.")
    chip = page.locator("#traceChip")
    expect(chip).to_contain_text("Paused")
    cap(page, "Q").click()                                   # a board click selects; it doesn't resume
    expect(cap(page, "Q")).to_have_class(re.compile(r"\bsel\b"))
    page.wait_for_timeout(600)
    assert len(calls(page, "start_test")) == 1
    page.click("#traceResume")
    page.wait_for_function("() => window.__calls.filter(c => c[0] === 'start_test').length === 2")


# ---------- 9, 10. readings title; trace label ----------

def test_readings_say_which_key(page):
    wait_for_call(page, "start_test")
    expect(page.locator("#tKey")).to_have_text("Last key: –")
    page.evaluate(f"window.onDepth([[{IDS['W']}, 1.5]])")
    expect(page.locator("#tKey")).to_have_text("Last key: W")


def test_trace_names_the_key_and_asks_for_one_when_empty(page):
    wait_for_call(page, "start_test")
    page.wait_for_function("() => window.__texts.includes('Press any key on your Huntsman')")
    page.evaluate(f"window.__texts = []; window.onDepth([[{IDS['W']}, 1.5]]); window.onDepth([[{IDS['W']}, 1.6]])")
    texts = page.evaluate("window.__texts")
    assert "W" in texts and "Press any key on your Huntsman" not in texts


# ---------- 11. the toast stays off the keys ----------

def test_apply_toast_doesnt_cover_the_keys_while_live(page):
    wait_for_call(page, "start_test")
    page.click("#applyDepth")
    page.click('#confirmApply button[value="apply"]')
    expect(page.locator("#toast")).to_have_class(re.compile(r"\bshow\b"))
    t, b = box(page.locator("#toast")), box(page.locator("#board"))
    assert t[1] >= b[3], (t, b)                                # below the board, at the dock
