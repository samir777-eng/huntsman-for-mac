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
- `tests/test_repo.py` checks that `ui/demo-layout.js` matches `layout.json` and that every source file has its licence header.

If you change `layout.json`, regenerate the demo layout with `python tools/make_demo_layout.py`.

## Previewing the interface

Open `ui/index.html?demo` in a browser. A simulated keyboard answers every call, including the key tester.

## Reporting a new model

Open a [new model issue](.github/ISSUE_TEMPLATE/new_model.md) with:

1. The model name, exactly as on the box.
2. The USB Product ID and Vendor ID: **Apple menu → About This Mac → More Info → System Report → USB**, then select the Razer keyboard.
3. The firmware version, if you know it (Synapse on Windows shows it).
4. If you have a Huntsman V3 Pro: the output of `huntsman.py status` (see the README's command line section).

The app only connects to 1532:02A6. Please don't change the Product ID and write to another model on your own; open the issue and we'll work out a read-only check first.

## Code style

- Keep changes small and focused. One logical change per pull request.
- Every new `.py`, `.js`, `.sh`, `.html` or `.css` file starts with the SPDX licence header used in the existing files.
- Interface text is plain and in sentence case.
- Add an entry to `CHANGELOG.md` under a new "Unreleased" heading at the top.

By contributing you agree that your contribution is licensed under GPL-3.0-or-later.
