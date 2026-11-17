# v2: Lighting Studio (2026-11-17)

## Problem
The keyboard's firmware effects are all exposed already (static, breathing ×3, spectrum, wave, reactive ×2,
ripple ×2, starlight ×3; fire is refused by firmware 1.03). Users want many more effects, typing reactions,
sound-reactive lighting, a layer editor with presets, and smart behaviour (idle/sleep/per-app). Anything beyond
firmware effects must be rendered by the app and streamed as per-key frames.

## Spike results (hardware, 2026-11-17, V3 Pro fw 1.03)
- Per-key frame = 6 packets (0F:03, rows 0–5, cols 0–21, size 0x47) after switching to custom mode once.
  Send + poll reply immediately: 294 fps, 0 failures; 1 ms sleep before poll: 109 fps. Current transport
  (15 ms sleep) gives 9 fps → the engine needs a fast exchange path. Target 30 fps (configurable 15–60).
- Key events during normal typing: IOKit input-value callbacks on the keyboard's interfaces give HID
  usage page 7 press/release (W 0x1A, A 0x04, S 0x16, D 0x07). Needs Input Monitoring. No driver mode.
- Sound: an input device stream (microphone, or a loopback device such as BlackHole for system audio).

## Requirements
1. Lighting engine renders frames at a target fps and streams them only when they change; one owner of the
   USB link (the existing process/file locks); pauses cleanly for other device operations; stops on quit and
   restores the saved firmware lighting.
2. Effect library (app-rendered): solid, gradient (linear/radial, 2–5 stops), rainbow (custom palette, speed,
   direction, scale), colour cycle, breathing (custom colours), aurora, matrix rain, plasma, fire, starfield,
   audio spectrum (bars across the keyboard), audio pulse (level → brightness/colour), typing heatmap.
3. Typing reactions: ripple, afterglow (key fades), explosion (radial burst), trail (row sweep), each with
   colour/palette, size, fade time.
4. Layers: ordered list; each layer = effect + params + key set ("all" or ids) + blend (normal, add, screen,
   multiply, max) + opacity + enabled. Presets: named layer stacks; save, rename, duplicate, delete, import/
   export JSON; built-in starter presets.
5. Smart lighting: idle timeout (dim or off after N minutes without input), off when the Mac sleeps or the
   screen locks and back on wake, per-app rules (frontmost app bundle id → preset), global brightness.
6. Menu bar: status item with on/off, preset list, open window, quit. Closing the window keeps the app
   running in the menu bar; login item launches the app in the background instead of `apply-saved`.
7. Privacy: key events are used only in memory for reactions; the heatmap stores per-key counts only, local,
   resettable, off by default. Audio is analysed in memory and never recorded or stored.
8. Firmware effects stay available ("Keyboard effects" mode); Studio mode is app-driven.

Non-goals: per-game SDK integrations, network sync, Windows.

## Architecture and interfaces (contract between implementers)
Package `lighting/` (pure Python, no I/O except where noted):
- `lighting/frame.py`: `Frame = dict[int, tuple[int,int,int]]` (key id → RGB 0..255).
  `Keymap` built from `layout.json`: `Keymap.keys` list of `KeyInfo(id, name, label, x, y, w, h, row, led)`;
  `Keymap.center(id) -> (cx, cy)`, `Keymap.bounds -> (w, h)`; `Keymap.by_hid_usage(usage) -> id | None`
  (HID usage page 7 → key id via names in layout.json; table in `lighting/hid_usage.py`).
- `lighting/effects/` modules, each registering `EffectSpec(name, label, category, params: list[ParamSpec],
  needs: set[str] in {"keys","audio","time"})` and a renderer class with
  `render(t: float, ctx: RenderContext) -> Frame` (only keys in ctx.keys). `RenderContext(keymap, keys: list[int],
  params: dict, audio: AudioState | None, events: list[KeyEvent], heat: dict[int,int])`.
  `KeyEvent(key_id: int, down: bool, t: float)`; `AudioState(level: float 0..1, bands: list[float] 16 bands 0..1)`.
  `ParamSpec(name, label, kind in {"color","colors","float","int","choice","bool"}, default, min, max, choices)`.
  `lighting.effects.REGISTRY: dict[str, EffectSpec]` and `create(name, params) -> renderer`.
- `lighting/layers.py`: `Layer(id, effect, params, keys: "all"|list[int], blend, opacity, enabled)`,
  `compose(layers, t, ctx_base) -> Frame` (bottom to top; blends in linear-light-free 8-bit sRGB math).
- `lighting/presets.py`: `Preset(name, layers, brightness)`, load/save `presets.json` in `hc.data_dir()`,
  validation (unknown effect/param → error), built-ins.
- `lighting/engine.py`: `Engine(keyboard_factory, keymap, fps=30)`: `.start()`, `.stop(restore=True)`,
  `.set_preset(Preset)`, `.push_key_event(KeyEvent)`, `.set_audio(AudioState)`, `.set_brightness(0..1)`,
  `.pause()/resume()` (context manager `engine.paused()` used by every other device call),
  `.on_frame(callback(frame))` for the UI preview (throttled ~15 fps). Uses `Keyboard.send_frame_fast(rows)`.
- `huntsman_core.Keyboard.send_frame_fast(rows)`: six 0F:03 packets with immediate reply polling (no 15 ms
  sleep), under the existing USB locks; `enter_custom_mode()`.

Package `inputs/`:
- `inputs/keys.py`: `KeyListener(callback(KeyEvent))` via IOKit input-value callbacks on the Huntsman only;
  start/stop; reports permission errors clearly.
- `inputs/audio.py`: `AudioListener(device=None, callback(AudioState))`, lists devices, 16 log bands, smoothing;
  uses `sounddevice` + `numpy`.
- `inputs/smart.py`: `SmartLighting(rules, on_change)`: idle seconds (IOKit HIDIdleTime), sleep/wake and screen
  lock/unlock (NSWorkspace / distributed notifications), frontmost app (NSWorkspace) → actions
  {dim: 0..1 | off | preset name}.
- `menubar.py`: NSStatusItem integration with pywebview's Cocoa loop.

## Implementation split
1. Engine + effects + layers + presets + core fast path + tests (implementer A).
2. Inputs (keys, audio, smart) + menu bar + background launch + tests (implementer B), in parallel with A.
3. Integration: app.py API + UI Studio (layer editor, effect gallery with live previews from the engine,
   presets bar, smart lighting pane) + demo-mode simulation + UI tests (implementer C), after A and B.
4. Independent review; hardware verification by the main agent.

## Tests
Pure renderers: deterministic frames for fixed t/params, value ranges, only requested keys, param validation.
Layers: blend math, opacity, key masks, order. Presets: round-trip, validation, built-ins valid.
Engine: fake keyboard records frames; fps throttle; no resend of identical frames; pause/resume; stop restores.
Inputs: HID usage mapping; audio band math on synthetic sine input; smart rules state machine with fake clock.
UI: Playwright in demo mode for layer add/remove/reorder, preset save/switch, smart pane.
Hardware (manual): fps, typing reactions, audio, idle/sleep, per-app switch, quit restores firmware lighting.
