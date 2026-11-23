# Live key tester (no Test button), 0.4.1

Owner request 2026-11-22: "I don't like the test button; Synapse doesn't have it, it shows the tested key and the
graph moves right away."

## Constraint
The travel stream (report 0x0B) only comes in driver mode, and in driver mode the keyboard stops typing
(depth_stream.py). So the tester can't run all the time. It runs only while the owner is looking at it.

## Behaviour
- **Starts by itself** when all hold: view is Actuation, the window is focused and visible, a model with the
  `key_tester` feature is connected (V3 Pro 02A6 on macOS), Synapse/no-keyboard/offline states don't block, and no
  other write is in progress.
- **Stops by itself** (keyboard types again) on: leaving Actuation, window blur (another app, Cmd-Tab),
  `visibilitychange` hidden (minimise, screen lock), close/quit (existing beforeunload + shutdown hooks), keyboard
  gone/Reconnect, and after 5 minutes with no key travel (idle limit, replaces the 60 s limit for this mode).
  Blur is debounced ~300 ms; focus back restarts it (also debounced) so tab flapping doesn't flood mode switches.
- **After an idle stop** it doesn't restart until the window is focused again or the owner clicks the stage.
- **On a start failure** (Input Monitoring denied, keyboard busy) it shows the reason once with a "Try again" button
  and doesn't retry by itself until the next focus/tab entry (no prompt loop, no toast spam).
- The "Test with a key press" / "Stop testing" button goes away. A status line in the panel says
  "Live: the Huntsman's typing is paused while this window is in front" (and "Paused: click here or press a key …"
  states as needed). The banner Stop button goes away too.
- Pressed keys light on the on-screen board and the meter/trace move at once (existing onDepth rendering).
- Apply / preset changes while live: keep whatever the code does today while testing (implementer checks and
  records it); a write must not leave the keyboard in driver mode.
- Unchanged: models without `key_tester` show the disabled reason (testerWhy) and never start; Windows never starts.

## Tests first
UI tests (tests/test_ui*.py, demo mode, headless Chromium) for: auto start on entering Actuation when focused; no
start when unfocused/hidden; stop on tab change, blur, hidden; restart on focus; idle stop after the limit (fake
clock); a start failure shows Try again and no retry loop; no start on models without key_tester / Windows; no Test
button. App tests (tests/test_app.py) for any API change (e.g. a start_test time-limit argument).

## Docs
README "Actuation and the key tester", CHANGELOG 0.4.1, HANDOFF, landing page text if it mentions the button,
demo gif caption if it names the button.
