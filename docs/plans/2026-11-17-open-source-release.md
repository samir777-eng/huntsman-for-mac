# Open-source release of Huntsman for Mac (2026-11-17)

## Baseline
Working personal tool in ~/Documents/huntsman-control: protocol core (45 fake-transport tests), pywebview UI,
CLI, hard-coded paths, personal files (snapshot, state, logs) in the code folder, no license.

## Requirements
1. Clean repo, no personal data; GPL-3.0 (layout/key data derives from easyrazer, GPL-3.0) with credits.
2. Installs on another Mac with one script; no hard-coded user paths.
3. Honest README: tested hardware, experimental features, safety and recovery.
4. Owner asks: Synapse-like dark UI, realistic keyboard, live actuation meter in the Actuation tab, accent choice.

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
