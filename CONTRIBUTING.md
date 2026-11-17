# Contributing

Thanks for helping. The most useful contributions right now are hardware reports: Rapid Trigger, Snap Tap, other Huntsman models, Intel Macs and older macOS.

## Safety rule

**Never send a command to the keyboard that hasn't been tested, and never write anything that could reach the firmware or its flash in a way the project doesn't already do.** Commands come from reverse engineering, not Razer documentation; a wrong write can leave a keyboard needing Synapse on Windows to recover. If you're unsure, open an issue with the packet bytes first and ask.

- Don't add firmware update, bootloader or unknown-command code.
- New write commands need a read-back check, a test against the simulated keyboard in `tests/test_core.py`, and a written note of how they were checked on hardware.

## Running the tests

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q tests
```

- `tests/test_core.py` and `tests/test_app.py` run against a simulated keyboard (`FakeTransport`). They never open USB and redirect settings files to a temporary folder.
- `tests/test_ui.py` opens `ui/index.html?demo` in headless Chromium and records what the interface sends. It is skipped when Playwright isn't installed.
- `tests/test_repo.py` checks that `ui/demo-layout.js` matches `layout.json` and `layouts/` and that every source file has its licence header.

If you change `layout.json` or a file in `layouts/`, regenerate the demo layout with `python tools/make_demo_layout.py`.

## Previewing the interface

Open `ui/index.html?demo` in a browser. A simulated keyboard answers every call, including the key tester. Add `&model=02B0` (or another product ID) to preview another model; a list in the header switches between them.

## Testing an experimental model

The Huntsman V3 Pro TKL (02A7), V3 Pro 8KHz (02CF), V3 Pro Mini (02B0), V2 (026C), V2 TKL (026B) and V2 Analog (0266)
have experimental support. Nobody has tested them with this app, and their LED positions are a guess. If you own one:

1. Install the app and open it. The header shows the model name with an *Experimental* badge.
2. Run `huntsman.py status` (see the README's command line section) and keep the output. It only reads.
3. Turn on **Keyboard → Experimental support**, or run `huntsman.py experimental on`. Read the warning first.
4. Run the **LED check** in the Keyboard tab: note which key lights for each row and column, then click
   **Copy summary**. Every cell helps; the corners and edges of each row help most.
5. Try the features the README lists for your model, one at a time, and note what happened.
6. Open a [new model issue](.github/ISSUE_TEMPLATE/new_model.md) with all of the above.

To stop, first use *Restore factory depth* if you changed actuation (it puts the V3 Pro models' keys back to 1.2 mm),
then turn the switch off (or `huntsman.py experimental off`). With the switch off, the app can't write to the keyboard.

If your model isn't in the list, open the same issue with the model name, USB IDs and firmware version. Please don't
add a Product ID to `models.py` and write to it on your own; we'll work out a read-only check first.

## Code style

- Keep changes small and focused. One logical change per pull request.
- Every new `.py`, `.js`, `.sh`, `.html` or `.css` file starts with the SPDX licence header used in the existing files.
- Interface text is plain and in sentence case.
- Add an entry to `CHANGELOG.md` under a new "Unreleased" heading at the top.

By contributing you agree that your contribution is licensed under GPL-3.0-or-later.
