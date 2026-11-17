# Open-source release of Huntsman for Mac (2026-11-17)

## Baseline
An earlier personal prototype: protocol core (45 fake-transport tests), pywebview UI,
CLI, hard-coded paths, personal files (snapshot, state, logs) in the code folder, no license.

## Requirements
1. Clean repo, no personal data; GPL-3.0 (layout/key data derives from easyrazer, GPL-3.0) with credits.
2. Installs on another Mac with one script; no hard-coded user paths.
3. Honest README: tested hardware, experimental features, safety and recovery.
4. Interface goals: Synapse-like dark UI, realistic keyboard, live actuation meter in the Actuation tab, accent choice.

Non-goals: other models, signed/notarised builds, Windows/Linux.

## Decisions
- Live meter needs driver mode (keyboard stops typing); offered as an explicit test mode with 60 s auto-stop,
  return-to-hardware on stop/close/exit, and RAM-only settings re-sent afterwards (mode switch reloads profile 0).
- Rapid Trigger / Snap Tap ON written to the live profile only (as easyrazer), re-sent at app start and login.
- First-launch snapshot instead of shipping a backup; "factory" restore = Synapse defaults 76/70.
- No Razer logo/brand assets; Synapse layout conventions only. Not copying Razer's app code or art.
- App bundle carries its own code + venv (TCC blocks unsigned apps reading ~/Downloads).

## Tests
- tests/test_core.py: packets, CRC, reply validation, thresholds, release rules, Rapid Trigger packets
  (easyrazer vector), effects, per-key frame, gamma, snapshot round-trip, factory restore, depth report parsing.
- Manual hardware checks listed in HANDOFF.md.

## Batch 3: open-source readiness (2026-11-17)
Requirements: UI smoke tests; generated demo layout kept in sync; installer hardening (quarantine, ad-hoc
signature, running-app check, escaped paths, Python choice); pinned dependencies; SPDX headers and NOTICE;
CONTRIBUTING, SECURITY, CHANGELOG, issue templates; version shown in CLI and UI; visible progress for long
reads/writes; README with real install/update/uninstall, Input Monitoring, CLI, troubleshooting and a
verified/unverified table; no personal details in tracked files.

Decisions:
- UI tests drive `ui/index.html?demo` in headless Chromium; an init script wraps `window.pywebview.api` on
  `pywebviewready` (registered before app.js) so every call is recorded. Skipped without Playwright.
- Repo checks (demo layout, licence headers) live in tests/test_repo.py so they run without Playwright.
- Python 3.11 minimum (pyobjc 13 requires it); 3.14+ is allowed with an "untested" note rather than refused.
- venv is created with --copies and the app runs Python with -B, so the ad-hoc signature stays valid
  (`codesign --verify --deep --strict`); the old bundle is moved aside and restored if the build fails.
- Progress: app.py reports writes then read-back as one bar; `_run` completes the bar if an operation fails.
- requirements.txt pins the full set frozen from the installed app's venv (Python 3.13).

Tests written first (red, then green): progress bar, demo-layout render(), licence headers, `--version`,
`info()` version, progress contract (set_depth read-back, failure completes the bar). The other UI cases describe existing behaviour and passed on first run.
Not testable here: install.sh end to end (would replace the installed app); its escaping was checked with
a scratch script and the ad-hoc signature on a copy of the installed bundle.
