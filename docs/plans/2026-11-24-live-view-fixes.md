# 0.4.2: live-view fixes from the hardware check (2026-11-24)

## Baseline
- master = v0.4.1, 1372 tests pass (2 skipped). Branch `live-view-fixes`.
- Live view (docs/plans/2026-11-22-live-key-tester.md) checked on the V3 Pro by the owner, 2026-11-24, from a fresh
  `./install.sh` of master:
  1. Click another window (mouse) → typing back at once: pass. (A first try failed once and didn't come back; see A.)
  2. Back to the window → live again: pass.
  3. Switching tab → typing at once: pass.
  4. Screen lock → password typed on the Huntsman: pass.
  5. Input Monitoring off → notice + Open Privacy settings (lands on Input Monitoring) + Try again → live: pass, but
     the two buttons read as plain text links (B).
  6. 5-minute pause + Resume: pass.
  7. Opens on the last tab (quit with the mouse, reopen): pass.
- Found: the Input Monitoring grant is held by the Python binaries (`…/Huntsman for Mac.app/Contents/Resources/venv/bin/python`,
  Homebrew `python3.13`), not by the bundle id `io.github.huntsman-for-mac` (TCC.db, 2026-11-24). `tccutil reset
  ListenEvent io.github.huntsman-for-mac` does nothing.
- Found: the Huntsman's Windows key lights on the on-screen board in live view (travel stream reports LEFT_GUI, id 127).

## Problem
A. In live view the Huntsman sends no key reports, so its own shortcuts (Cmd-Tab, Cmd-Q, Cmd-Space) never reach macOS.
   README/CHANGELOG/landing page say "Cmd-Tab" brings typing back: false for the Huntsman itself. A user without a
   second keyboard/mouse at hand is stuck until the 5-minute pause.
B. "Try again" / "Open Privacy settings" in the live notice look like text, not buttons.
C. Docs say nothing true about where Input Monitoring is listed (python, not "Huntsman for Mac").
D. Empty gap in the Actuation panel between the live status line and "Last key" (HANDOFF Next 0c,
   docs/screenshot-actuation.png).

Non-goals: posting the shortcut to macOS for the user (needs Accessibility permission), the AppleScript `quit` being
ignored (noted in HANDOFF), Windows.

## Decision (owner, 2026-11-24)
A: pressing ⌘ (the Windows/Start key, layout name `LEFT_GUI`) on the Huntsman ends live view at once, so the
shortcut pressed next works.

## Behaviour
- While live, when the travel stream shows `LEFT_GUI` past a press depth (implementer picks; ≥ 0.5 mm suggested,
  constant with a test), live view stops (keyboard back to typing) as fast as possible: detect in Python in the
  stream thread (no window round-trip), then the normal stop path (`DepthSession.stop`, lease, follow-up).
- The window then holds live view off like the idle pause: status "Typing again: you pressed ⌘. …", the Paused chip
  with Resume; no restart until the window is focused again (after leaving it) or Resume is clicked. Holding or
  pressing ⌘ again doesn't loop.
- The live status line while live says how to leave: e.g. "Live view on. Press ⌘ or click another window to type
  again." (keep one live region, spoken once per start).
- Models without `LEFT_GUI` in their layout: unchanged (key tester runs only on the V3 Pro today).
- B: Try again / Open Privacy settings become real buttons (existing button styles), same ids/behaviour.
- D: the gap goes; nothing else in the panel moves (screenshot before/after).

## Tests first
- tests/test_depth_stream*.py / test_app.py: a session whose stream reports LEFT_GUI past the depth stops by itself
  with a distinct reason; below the depth it doesn't; other keys don't; switch-back failure still reports UNPLUG.
- tests/test_ui*.py (demo mode): the stop reason holds live view off (no restart while focused), Resume and
  refocus restart it; status text names ⌘; Try again / Open Privacy settings are `<button>` styled as buttons
  (not `.link`); the gap: layout assertion on the panel.
- Demo mode (ui/demo.js) simulates the ⌘ stop so the UI tests and the media can show it.

## Docs (verified behaviour only, after the hardware re-check)
README (live view paragraph, "Version 0.4.1" paragraph → checked results, Permissions: python entry), CHANGELOG
0.4.2, HANDOFF (results above, TCC fact, Next), landing page text if it says Cmd-Tab.

## Hardware re-check for 0.4.2 (owner, one at a time)
⌘ stops live view and a Cmd-Tab right after works; ⌘ held doesn't restart/loop; Resume after ⌘; buttons look like
buttons; gap gone; check 1 (mouse) still passes.

## Rollback
Revert the merge; 0.4.1 stays published.
