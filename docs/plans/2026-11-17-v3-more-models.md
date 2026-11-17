# v0.3.0: more Huntsman models (2026-11-17)

## Problem
The app only opens 1532:02A6 (Huntsman V3 Pro, full size). Owners of the other Huntsman V3 Pro models and of the
Huntsman V2 family have no Mac app either. The maintainer only owns the 02A6, so every other model ships untested and
must be confirmed by outside testers.

## Research (sources cloned 2026-11-17: OpenRazer master cd5c424, janeblower/easyrazer master, librazermacos 556f186)
| Model | PID | Lighting matrix | Analog commands | Layout source |
|---|---|---|---|---|
| V3 Pro (owned, verified) | 02A6 | 6×22 | easyrazer, verified here | layout.json |
| V3 Pro TKL | 02A7 | 6×22 (OpenRazer) | same as 02A6 (easyrazer, untested) | easyrazer dev-layout-pro-tkl.json (84 keys) |
| V3 Pro 8KHz | 02CF | 6×22 | same as 02A6 (untested); OpenRazer reads the active varstore (05:84) first | layout.json |
| V3 Pro Mini | 02B0 | 5×15 (OpenRazer) | same as 02A6 (easyrazer: tested on hardware) | easyrazer dev-layout-mini.json (61 keys, Fn layer) |
| V2 | 026C | 6×22 | none (not analog) | layout.json key positions |
| V2 TKL | 026B | 6×18 | none (not analog) | derived from full size minus numpad |
| V2 Analog | 0266 | 8×23 (easyrazer, from 0F:80 reply; OpenRazer says 8×22) | different protocol, out of scope | layout.json + dial, case edge, wrist rest rows |

All seven use interface 3, 90-byte reports, tid 0x1F, extended class 0x0F (02 effects, 03 frame, 04 brightness),
LED 0x05. V2 Analog has no starlight. LED (row, col) positions per key are **not documented** for any model except
the 02A6 (ours, checked on hardware); for the others they are a best guess until a tester confirms them.

## Requirements
1. A model table (`models.py`): PID, name, lighting matrix size, layout file, firmware effect list, capabilities
   (actuation, rapid trigger, snap tap, key tester, per-key lighting, studio) and a status: `verified` or
   `experimental`. 02A6 is the only `verified` model.
2. Detection: the app, CLI, lighting service, key listener and key tester open the first supported model found and
   use its matrix size, layout and capabilities. **02A6 behaviour stays byte-for-byte identical** (tests pin it).
3. Layout files per model (`layouts/<pid>.json`, same format as layout.json; layout.json stays for 02A6). Frame
   building, Studio, per-key paint, heatmap and the on-screen keyboard use the active model's layout and matrix.
4. Safety gate for experimental models:
   - Connecting, reading firmware version, effect and brightness: always allowed (reads only).
   - Lighting (firmware effects, brightness, per-key colours, Studio): allowed after the user turns on
     **Keyboard → Experimental support** (one switch, remembered, with a plain warning).
   - Actuation, Rapid Trigger, Snap Tap on experimental V3 models: also behind the switch.
   - Key tester (driver mode, stops typing): **off** for experimental models; not offered.
   - V2 family: actuation, Rapid Trigger, Snap Tap and key tester tabs are hidden (hardware or protocol absent).
5. LED check (Keyboard tab, experimental models only, behind the switch): lights one matrix cell at a time and shows
   its row/column, so a tester can report which key lit; result text is easy to paste into an issue.
6. UI shows the detected model name and "Experimental" badge; demo mode can switch between models.
7. Docs: README supported-hardware table with status per model, CONTRIBUTING tester steps, issue template asks for
   `huntsman.py status` and LED check output.

Non-goals: V2 Analog actuation/analog features, wireless models, firmware updates, any new write command.

## Decisions
- No new command types: only commands already verified on 02A6 are sent to other models.
- Unknown matrix size or layout → lighting stays off for that model rather than guessing frame sizes.
- Active profile read (05:84): sent to every model, as already done and verified on 02A6 (OpenRazer uses the same
  read on the 8KHz). Whether the 8KHz reports its profile the same way is a tester check.

## Tests (written first)
- Model table: every model has a layout whose LED cells fit its matrix; no duplicate LEDs; PIDs unique.
- 02A6 regression: frames, actuation, effects and snapshot packets identical to before (golden bytes).
- Detection with fake transports per PID; unsupported PID refused.
- Gate: experimental model + switch off → every write raises before reaching the transport; switch on → allowed;
  key tester never allowed on experimental models; V2 has no actuation API.
- Frame size follows the model matrix (5×15, 6×18, 8×23).
- UI (demo mode): model switcher, hidden tabs for V2, badge, Experimental switch, LED check.

## Implementation split (Opus implementers, sequential where files overlap)
1. Core: models.py, layouts, detection, gate, frame sizes (huntsman_core, depth_stream, inputs/keys, lighting).
2. App/service/CLI wiring + UI (tabs, badge, switch, LED check, demo).
3. Docs.
Then an independent Opus review, hardware regression on the owner's 02A6, merge, release v0.3.0.

## Review 1 (independent Opus, 2026-11-17)
No Critical findings: no write reaches an experimental model with the switch off; driver mode can't reach one.
Fixed: snapshot tied to its model (PID, mismatch refused); window re-reads the model on reconnect; Studio turns off
once on a locked model instead of retrying; key listener follows a model change; effects use the model's row count;
CLI `experimental off` stops Studio first; more 02A6 golden scenarios (key tester, apply_saved, restores, Studio
frames) recorded from master; switch read cached by mtime. Open: one snapshot file per user (a second model gets none).
