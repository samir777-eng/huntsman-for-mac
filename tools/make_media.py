# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Regenerate docs/screenshot-actuation.png and docs/demo-key-tester.gif from demo mode (no keyboard needed).

    .venv/bin/python tools/make_media.py

Needs the dev requirements (Playwright + Chromium) and ffmpeg (on PATH, /opt/homebrew/bin, or $FFMPEG). The page is
the demo (ui/index.html?demo) at 1280×900, opened on Actuation with the window "in front", so the live view runs.
W, A, S and D are selected and set to 1.2 mm, then key travel is fed to the page frame by frame on a fake clock, so
the trace's time axis matches the gif's (12.5 fps) however long each screenshot takes. The gif is scaled to 960×675
and made with palettegen/paletteuse.
"""
import math
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from playwright.sync_api import sync_playwright, expect  # noqa: E402
from test_ui import RECORDER, URL, IDS  # noqa: E402  (demo hooks: window in front, Actuation, intro seen)

PNG = os.path.join(ROOT, "docs", "screenshot-actuation.png")
GIF = os.path.join(ROOT, "docs", "demo-key-tester.gif")
SIZE = {"width": 1280, "height": 900}
FRAME_MS = 80                       # 12.5 fps, like the earlier gif
KEY_MS = 1400                       # each key: pressed and released, then a short rest
PRESS = [("W", 2.0), ("A", 3.6), ("S", 1.6), ("D", 2.8)]   # deepest point per key, in mm

# A fake clock for the trace (it draws the last 4 s against performance.now()).
CLOCK = """
const __realNow = performance.now.bind(performance);
window.__clock = null;
performance.now = () => window.__clock ?? __realNow();
"""


def ffmpeg():
    for p in (os.environ.get("FFMPEG"), shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if p and os.path.exists(p):
            return p
    sys.exit("ffmpeg not found: install it (brew install ffmpeg) or set FFMPEG")


def travel(t_ms):
    """(key, mm) at time t: each key goes down and back up in 1 s, then rests 0.4 s."""
    i = int(t_ms // KEY_MS) % len(PRESS)
    ph = (t_ms % KEY_MS) / 1000
    key, deep = PRESS[i]
    d = deep * math.sin(math.pi * ph) if ph < 1 else 0.0
    return IDS[key], round(max(0.0, d), 2)


def feed(page, t_ms):
    page.evaluate("t => { window.__clock = t; }", 100000 + t_ms)
    kid, d = travel(t_ms)
    page.evaluate("b => window.onDepth(b)", [[kid, d]] if d > 0.01 else [])


def setup(page):
    page.add_init_script(CLOCK)
    page.add_init_script(RECORDER)
    page.goto(URL)
    expect(page.locator("#conn")).to_have_text("Connected, firmware 1.03")
    page.wait_for_function("window.__calls.some(c => c[0] === 'start_test')")
    for k in ("W", "A", "S", "D"):
        page.locator(f'.cap[data-id="{IDS[k]}"]').click()
    page.fill("#depth", "1.2")
    page.dispatch_event("#depth", "input")
    page.click("#applyDepth")
    page.wait_for_function("window.__calls.some(c => c[0] === 'set_depth')", timeout=3000)
    page.wait_for_timeout(300)
    # no Apply toast, no demo-only model list in the header, and the meter's key jumps straight to each reading
    # (its 30 ms transition only runs on the real clock)
    page.add_style_tag(content="#toast, #demoModel { display: none !important; } .meter-key { transition: none !important; }")
    page.mouse.move(0, 0)


def main():
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        b = p.chromium.launch()
        page = b.new_page(viewport=SIZE)
        setup(page)
        # warm the trace up so the first frame already has 4 s of history
        for t in range(-4000, 0, FRAME_MS):
            feed(page, t % (KEY_MS * len(PRESS)))
        n = KEY_MS * len(PRESS) // FRAME_MS
        for f in range(n):
            feed(page, f * FRAME_MS)
            page.screenshot(path=os.path.join(tmp, f"f{f:03d}.png"))
        # the still: D near its deepest press (2.8 mm), as on the README
        page2 = b.new_page(viewport=SIZE)
        setup(page2)
        d_start = 3 * KEY_MS
        for t in range(d_start - 4000, d_start + 501, FRAME_MS // 4):
            feed(page2, t)
        page2.screenshot(path=PNG)
        b.close()
        palette = os.path.join(tmp, "palette.png")
        scale = "fps=12.5,scale=960:-1:flags=lanczos"
        subprocess.run([ffmpeg(), "-v", "error", "-y", "-framerate", "12.5", "-i", os.path.join(tmp, "f%03d.png"),
                        "-vf", f"{scale},palettegen=max_colors=128:stats_mode=diff", palette], check=True)
        subprocess.run([ffmpeg(), "-v", "error", "-y", "-framerate", "12.5", "-i", os.path.join(tmp, "f%03d.png"),
                        "-i", palette, "-lavfi", f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                        "-loop", "0", GIF], check=True)
    print(f"wrote {os.path.relpath(PNG, ROOT)} and {os.path.relpath(GIF, ROOT)} ({os.path.getsize(GIF):,} bytes)")


if __name__ == "__main__":
    main()
