# UX audit fixes for 0.4.0 (2026-11-18)

Source: independent UX audit in demo mode (49 screenshots; scratchpad ux/). Owner chose: fix all 10 + quick wins
before 0.4.0.

1. No-keyboard empty state on the stage with a primary Reconnect; panel disabled; header doesn't show a stale model;
   error toasts cleared on connect; "Connected to {model}" toast.
2. Actuation: mixed depths show "Mixed (a–b)"; not dirty until the user edits; Apply names what changes / confirms
   before overwriting keys with different depths.
3. Small windows: legends and depth labels scale with key size, depth labels hidden below a size (shown on hover).
4. Sticky panel footer for the primary Apply; readings + warning only while testing.
5. Studio previews edits on the on-screen board while Studio is off, with a "Preview, Studio off [Turn on]" chip.
6. Built-in presets: "Save as…" is primary with an inline hint; no dead-looking Save.
7. Gear labelled "Keyboard"; key tester shown disabled with the reason on models without it.
8. Windows: one Synapse notice (bold first line, details in a disclosure), lock note hidden while Synapse runs, copy
   says "this app" not "Huntsman for Mac" where it reads oddly on Windows.
9. Select bar hidden where selection does nothing; scope line "Applying to N selected keys · Clear".
10. Snap Tap: switch + Apply like Rapid Trigger, "On for A and D" state, dirty marker, pick keys on the board.
Quick wins: aria-live on the live readout, bigger reorder targets, new Solid layer defaults to Multiply/50%,
"Onboard profile", no stale toasts across tabs. Spelling stays British ("Colour") to match the README and app.

Tests first (UI tests in demo mode for each); 02A6 bytes unchanged (golden tests); then independent review and a
hardware check of actuation, Snap Tap and Studio preview on the owner's keyboard.
