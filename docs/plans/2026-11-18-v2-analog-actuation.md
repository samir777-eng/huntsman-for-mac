# V2 Analog actuation (2026-11-18)

## Requirement
Actuation point for the Huntsman V2 Analog (1532:0266), experimental, both platforms, behind the Experimental switch.

## Protocol (easyrazer, V2 Analog verified on hardware by easyrazer unless noted)
- Read 02:92 [profile, fwID, layer] size 80 → [profile, fwID, layer, thrL, thrH, fnId, fnSize, fnData…].
- Write 02:12 same format: read, change thrL/thrH only, write, read back and compare.
- Scale: mm = thr/255 × 2.1 + 1.5. Hardware mode clamps actuation to 15–250 → offer 1.62–3.56 mm (only 250 end
  verified). Release thrH ≥ 5 and ≤ thrL − 10 (unverified).
- Profiles: active saved profile first, then live profile 0 (same order as V3).
- Rapid Trigger / Snap Tap on the V2 Analog are host-side (driver mode + SendInput) — out of scope.

## Changes
models.py: V2 Analog gets `actuation` with its own scale/range; actuation UI uses the model's range/step; key ids from
easyrazer's 0266 keymap. Tests first: encode/decode, clamp, read-modify-write keeps fn bytes, gate, UI range.
