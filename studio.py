# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The Studio controller: ties the lighting engine to presets, settings, typing and sound listeners and smart
lighting. It lives in the lighting service (service.py), which exposes it to the app over ipc.py and drives it from
the menu bar (menubar.StatusMenu).

- Settings live in state.json under "studio" and "smart" (clean_studio / clean_smart validate them field by
  field); user presets in presets.json (lighting.presets); typing counts in heatmap.json.
- The engine shows the "working" preset: the active preset plus unsaved edits (update_layers, debounced so a
  slider drag doesn't restart typing reactions on every step). Smart lighting may dim it, switch it off or show
  another preset for the frontmost app without changing the user's choice.
- The key listener runs only while the shown preset needs key presses (or the heatmap is counting), the audio
  listener only while it needs sound. Permission errors are kept for the window to show.
- Key presses and audio stay in memory; only per-key press counts are written, and only when the heatmap is on.

Lock order: nothing called with Studio._lock held may wait on another lock that can be held while waiting for
the main thread, or on the window. So the engine's restore callback (which takes the service's device lock) runs only after
Studio._lock is released, and smart lighting notifications (delivered on the main thread) hand their work to a
worker thread instead of taking Studio._lock there.
"""
import copy
import json
import os
import threading
import time
import traceback

import huntsman_core as hc
from lighting import effects as fx
from lighting.engine import PREVIEW_FPS
from lighting.frame import AudioState as LightAudio
from lighting.presets import Preset, builtin_presets, load_presets, save_presets

FPS_MIN, FPS_MAX = 15, 60
SENS_MIN, SENS_MAX = 0.1, 4.0
DEBOUNCE = 0.15
MAX_IMPORT = 256 * 1024
PREVIEW_MAX = 30.0   # seconds one studio_preview request lasts at most; the window asks again while it shows Studio
EXPORT_FORMAT = "huntsman-for-mac-preset"
DEFAULT_STUDIO = {"enabled": False, "active": "Rainbow wave", "fps": 30, "brightness": 1.0,
                  "audio": {"device": None, "sensitivity": 1.0}, "heat": False}
NEUTRAL = {"brightness": 1.0, "off": False, "preset": None}

DESCRIPTIONS = {
    "solid": "One colour on every key.",
    "gradient": "A still blend of two to five colours across the keyboard.",
    "rainbow": "A moving band of colours that sweeps across the keys.",
    "colour_cycle": "The whole keyboard fades through a palette together.",
    "breathing": "Slowly fades in and out, one colour per breath.",
    "aurora": "Soft curtains of colour drifting like northern lights.",
    "matrix": "Falling streaks of light, row by row.",
    "plasma": "Liquid, swirling colour that never repeats exactly.",
    "fire": "Flickering flames rising from the bottom row.",
    "starfield": "Keys twinkle on and off at random, like stars.",
    "audio_spectrum": "Bars that rise with the sound, bass on the left.",
    "audio_pulse": "The keyboard brightens and changes colour with the volume.",
    "heatmap": "Keys you press most glow hottest. Counts only, stored on this Mac.",
    "reactive_ripple": "A ring of light spreads out from each key you press.",
    "reactive_afterglow": "Pressed keys light up, then fade.",
    "reactive_explosion": "A burst of colour around each key you press.",
    "reactive_trail": "A streak runs along the row of each key you press.",
}


# ---------- settings validation (state.json) ----------

def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_fps(v):
    if not _num(v) or int(v) != v or not FPS_MIN <= v <= FPS_MAX:
        raise ValueError(f"frames per second must be a whole number {FPS_MIN}-{FPS_MAX}")
    return int(v)


def check_level(v, what="brightness"):
    if not _num(v) or not 0 <= v <= 1:
        raise ValueError(f"{what} must be 0-1")
    return float(v)


def check_sensitivity(v):
    if not _num(v) or not SENS_MIN <= v <= SENS_MAX:
        raise ValueError(f"sensitivity must be {SENS_MIN}-{SENS_MAX}")
    return float(v)


def check_device(v):
    if v is None:
        return None
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ValueError("the audio device must be a device number or none for the default input")
    return v


def clean_studio(raw):
    """Defaults overlaid field by field with whatever in raw is valid."""
    out = copy.deepcopy(DEFAULT_STUDIO)
    if not isinstance(raw, dict):
        return out
    for key, check in (("enabled", bool), ("heat", bool)):
        if isinstance(raw.get(key), check):
            out[key] = raw[key]
    if isinstance(raw.get("active"), str) and raw["active"].strip():
        out["active"] = raw["active"]
    for key, check in (("fps", check_fps), ("brightness", check_level)):
        try:
            out[key] = check(raw.get(key))
        except ValueError:
            pass
    a = raw.get("audio")
    if isinstance(a, dict):
        for key, check in (("device", check_device), ("sensitivity", check_sensitivity)):
            if key in a:
                try:
                    out["audio"][key] = check(a[key])
                except ValueError:
                    pass
    return out


def clean_smart(raw):
    """Smart lighting settings: inputs.smart.normalise_config, keeping the valid parts of a bad config."""
    from inputs.smart import DEFAULT_CONFIG, normalise_config
    if not isinstance(raw, dict):
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        return normalise_config(raw)
    except ValueError:
        pass
    out = copy.deepcopy(DEFAULT_CONFIG)
    idle = raw.get("idle")
    if isinstance(idle, dict):
        for k, v in idle.items():
            try:
                out = normalise_config({**out, "idle": {**out["idle"], k: v}})
            except ValueError:
                pass
    for k in ("sleep_off", "lock_off"):
        if isinstance(raw.get(k), bool):
            out[k] = raw[k]
    rules = raw.get("app_rules")
    for r in rules if isinstance(rules, list) else []:
        try:
            out = normalise_config({**out, "app_rules": out["app_rules"] + [r]})
        except ValueError:
            pass
    return out


# ---------- effects catalogue for the window ----------

def _plain(v):
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def effect_catalog():
    return [{"name": s.name, "label": s.label, "category": s.category, "description": DESCRIPTIONS.get(s.name, ""),
             "needs": sorted(s.needs),
             "params": [{"name": p.name, "label": p.label, "kind": p.kind, "default": _plain(p.default),
                         "min": p.min, "max": p.max, "choices": _plain(p.choices) if p.choices else None}
                        for p in s.params]}
            for s in fx.REGISTRY.values()]


def preset_needs(preset):
    needs = set()
    for layer in preset.layers if preset else []:
        if layer.enabled and layer.effect in fx.REGISTRY:
            needs |= fx.REGISTRY[layer.effect].needs
    return needs


# ---------- default platform hooks (imported lazily: pyobjc, IOKit, PortAudio) ----------

def _key_listener(callback):
    import platforms
    if platforms.is_windows():   # Raw Input (experimental)
        from platforms.win_keys import RawKeyListener
        return RawKeyListener(callback)
    from inputs.keys import KeyListener
    return KeyListener(callback)


def _audio_listener(device, callback, sensitivity=1.0, on_error=None):
    from inputs.audio import AudioListener
    return AudioListener(device, callback, sensitivity=sensitivity, on_error=on_error)


def _smart_lighting(config, on_change):
    from inputs.smart import SmartLighting
    return SmartLighting(config, on_change)


def _list_devices():
    from inputs.audio import list_input_devices
    return [{"index": d.index, "name": d.name, "loopback": d.is_loopback} for d in list_input_devices()]


def _in_thread(fn):
    threading.Thread(target=fn, name="huntsman-studio", daemon=True).start()


def _timer(delay, fn):
    t = threading.Timer(delay, fn)
    t.daemon = True
    t.start()
    return t


class Studio:
    def __init__(self, engine, settings, smart, *, save, keymap, push=None, key_listener=None, audio_listener=None,
                 smart_lighting=None, list_devices=None, schedule=None, spawn=None, heat_path=None, clock=None,
                 sleep=None):
        """save(studio_settings, smart_config) persists both. push(fn_name, payload) sends to the window.
        spawn(fn) runs fn on another thread (tests pass a synchronous one); clock and sleep pace the preview."""
        self.engine, self.keymap = engine, keymap
        self.settings, self.smart_cfg = clean_studio(settings), clean_smart(smart)
        self._save, self._push = save, push or (lambda *_: None)
        self._make_keys = key_listener or _key_listener
        self._make_audio = audio_listener or _audio_listener
        self._make_smart = smart_lighting or _smart_lighting
        self._list_devices = list_devices or _list_devices
        self._schedule = schedule or _timer
        self._spawn = spawn or _in_thread
        self._clock, self._sleep = clock or time.monotonic, sleep or time.sleep
        self._preview_until, self._previewing = None, False
        self._smart_slot = threading.Lock()   # guards _smart_next / _smart_busy only; never held while waiting
        self._smart_next, self._smart_busy = None, False
        self._heat_path = heat_path or os.path.join(hc.data_dir(), "heatmap.json")
        self._lock = threading.RLock()
        self._builtins = builtin_presets(keymap)
        self.errors = {"keys": None, "audio": None, "presets": None}
        try:
            self.user = load_presets()
        except ValueError as e:
            self.user = []
            self.errors["presets"] = f"{e}. Your saved presets weren't loaded; saving a preset replaces the file."
        self.working = self._find(self.settings["active"]) or self._builtins[0]
        self.settings["active"] = self.working.name
        self.dirty = False
        self.action = dict(NEUTRAL)
        self._shown_key = None
        self._keys = self._audio = self._smart = None
        self._pending = None
        self._gui = False
        self._listeners = []
        self.engine.set_fps(self.settings["fps"])
        self.engine.set_heat_enabled(self.settings["heat"])
        self.engine.set_heat(self._load_heat())

    # ---------- reads ----------

    def presets(self):
        return ([{**p.to_dict(), "builtin": True} for p in self._builtins]
                + [{**p.to_dict(), "builtin": False} for p in self.user])

    def state(self):
        with self._lock:
            try:
                devices, dev_error = self._list_devices(), None
            except Exception as e:
                devices, dev_error = [], f"Couldn't list sound inputs: {e}"
            return {"effects": effect_catalog(), "presets": self.presets(), "active": self.settings["active"],
                    "working": self.working.to_dict(), "dirty": self.dirty, "enabled": self.settings["enabled"],
                    "fps": self.settings["fps"], "brightness": self.settings["brightness"],
                    "needs": sorted(preset_needs(self.working)),
                    "audio": {**self.settings["audio"], "devices": devices, "error": dev_error},
                    "heat": {"enabled": self.settings["heat"], "keys": len(self.engine.heat_counts())},
                    "smart": copy.deepcopy(self.smart_cfg), "action": dict(self.action),
                    "errors": dict(self.errors)}

    def summary(self):
        with self._lock:
            return {"enabled": self.settings["enabled"], "active": self.settings["active"],
                    "presets": [p["name"] for p in self.presets()]}

    def on_change(self, callback):
        """callback(summary) after the on/off state, the active preset or the preset list changes."""
        self._listeners.append(callback)

    # ---------- presets ----------

    def _find(self, name):
        for p in self._builtins + self.user:
            if p.name == name:
                return Preset.from_dict(p.to_dict())
        return None

    def _is_builtin(self, name):
        return any(p.name == name for p in self._builtins)

    def _unique(self, base):
        names = {p.name for p in self._builtins + self.user}
        if base not in names:
            return base
        n = 2
        while f"{base} {n}" in names:
            n += 1
        return f"{base} {n}"

    def _store(self, users):
        save_presets(users)
        self.user = users
        self.errors["presets"] = None

    def set_active(self, name):
        with self._lock:
            p = self._find(name)
            if p is None:
                raise ValueError(f"there's no preset called {name!r}")
            self._activate(p)
        self._changed()

    def _activate(self, preset):
        self._cancel_pending()
        self.working, self.dirty = preset, False
        self.settings["active"] = preset.name
        self._persist()
        self._apply()

    def save_preset(self, d):
        """Save (create or replace) a user preset and make it the active one."""
        p = Preset.from_dict(d)
        with self._lock:
            if self._is_builtin(p.name):
                raise ValueError(f"{p.name!r} is built in. Use Save as with a new name.")
            users = [u for u in self.user if u.name != p.name]
            idx = next((i for i, u in enumerate(self.user) if u.name == p.name), len(users))
            users.insert(idx, p)
            self._store(users)
            self._activate(Preset.from_dict(p.to_dict()))
        self._changed()

    def delete_preset(self, name):
        with self._lock:
            if self._is_builtin(name):
                raise ValueError("built-in presets can't be deleted")
            if not any(u.name == name for u in self.user):
                raise ValueError(f"there's no preset called {name!r}")
            self._store([u for u in self.user if u.name != name])
            if self.settings["active"] == name:
                self._activate(self._find(self._builtins[0].name))
        self._changed()

    def rename_preset(self, old, new):
        with self._lock:
            if self._is_builtin(old):
                raise ValueError("built-in presets can't be renamed. Duplicate it first.")
            if not isinstance(new, str) or not new.strip():
                raise ValueError("a preset needs a name")
            new = new.strip()
            if new != old and self._find(new) is not None:
                raise ValueError(f"a preset called {new!r} already exists")
            if not any(u.name == old for u in self.user):
                raise ValueError(f"there's no preset called {old!r}")
            users = [Preset(new, u.layers, u.brightness) if u.name == old else u for u in self.user]
            self._store(users)
            if self.settings["active"] == old:
                self.working = Preset(new, self.working.layers, self.working.brightness)
                self.settings["active"] = new
                self._persist()
        self._changed()

    def duplicate_preset(self, name, new=None):
        with self._lock:
            p = self._find(name)
            if p is None:
                raise ValueError(f"there's no preset called {name!r}")
            src = self.working if name == self.settings["active"] else p   # keep unsaved edits
            copy_ = Preset.from_dict({**src.to_dict(), "name": self._unique(new.strip() if new else f"{name} copy")})
            self._store(self.user + [copy_])
            self._activate(Preset.from_dict(copy_.to_dict()))
            out = copy_.name
        self._changed()
        return out

    def import_preset(self, text):
        if not isinstance(text, str) or len(text) > MAX_IMPORT:
            raise ValueError("that isn't a preset file (too large or empty)")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"that isn't a preset file: {e.msg}") from e
        if isinstance(data, dict) and data.get("format") == EXPORT_FORMAT:
            data = data.get("preset")
        p = Preset.from_dict(data)
        with self._lock:
            p.name = self._unique(p.name.strip())
            self._store(self.user + [p])
            self._activate(Preset.from_dict(p.to_dict()))
        self._changed()
        return p.name

    def export_preset(self, name):
        with self._lock:
            p = self.working if name == self.settings["active"] else self._find(name)
            if p is None:
                raise ValueError(f"there's no preset called {name!r}")
            return json.dumps({"format": EXPORT_FORMAT, "version": 1, "preset": p.to_dict()}, indent=1)

    # ---------- live edits ----------

    def update_layers(self, layers):
        """Validate now; show after DEBOUNCE seconds of quiet. Returns what the edited preset needs."""
        with self._lock:
            p = Preset.from_dict({"name": self.working.name, "brightness": self.working.brightness, "layers": layers})
            self.working, self.dirty = p, True
            self._cancel_pending()
            self._pending = self._schedule(DEBOUNCE, self._apply_pending)
            return sorted(preset_needs(p))

    def _apply_pending(self):
        with self._lock:
            self._pending = None
            self._apply()

    def _cancel_pending(self):
        if self._pending is not None:
            try:
                self._pending.cancel()
            except Exception:
                pass
            self._pending = None

    def set_brightness(self, level):
        with self._lock:
            self.settings["brightness"] = check_level(level)
            self._persist()
            self._apply()

    def set_fps(self, fps):
        with self._lock:
            fps = check_fps(fps)
            self.engine.set_fps(fps)
            self.settings["fps"] = fps
            self._persist()

    def set_audio_device(self, device):
        with self._lock:
            self.settings["audio"]["device"] = check_device(device)
            self._persist()
            self._stop_audio()
            self._sync_inputs()

    def set_audio_sensitivity(self, value):
        with self._lock:
            self.settings["audio"]["sensitivity"] = check_sensitivity(value)
            self._persist()
            if self._audio is not None and hasattr(self._audio, "set_sensitivity"):
                self._audio.set_sensitivity(self.settings["audio"]["sensitivity"])

    def set_heat(self, on):
        if not isinstance(on, bool):
            raise ValueError("the heatmap switch must be true or false")
        with self._lock:
            self.settings["heat"] = on
            self.engine.set_heat_enabled(on)
            self._persist()
            if not on:
                self._save_heat()
            self._sync_inputs()

    def reset_heat(self):
        with self._lock:
            self.engine.reset_heat()
            try:
                os.remove(self._heat_path)
            except FileNotFoundError:
                pass

    def set_smart(self, config):
        cfg = clean_smart_strict(config)
        with self._lock:
            self.smart_cfg = cfg
            self._persist()
            if self._smart is not None:
                self._smart.set_config(cfg)

    # ---------- on / off ----------

    def set_enabled(self, on, restore=True):
        """Studio on: the engine streams the working preset. Off: it stops, and (restore=True) the saved
        keyboard lighting comes back; restore=False when the caller is about to set the lighting itself."""
        if not isinstance(on, bool):
            raise ValueError("on must be true or false")
        stopped = False
        with self._lock:
            self.settings["enabled"] = on
            self._persist()
            if on:
                self._apply()
                self.engine.start()
                self._sync_inputs()
                self._start_smart()
            else:
                self._stop_inputs()
                self._stop_smart()
                self.action = dict(NEUTRAL)
                self._save_heat()
                if self.engine.running:
                    self.engine.stop(restore=False)
                    stopped = True
        if stopped and restore:
            self._restore_unless_on()
        self._changed()

    def preview(self, seconds):
        """While Studio is off, show the working preset on the window's on-screen board for `seconds` (at most
        PREVIEW_MAX; the window asks again while it shows Studio, and 0 stops). Frames are only composed and pushed
        to the window: nothing is sent to the keyboard. While Studio is on the engine's own previews do this."""
        if not _num(seconds) or seconds < 0:
            raise ValueError("seconds must be a number, 0 or more")
        with self._lock:
            self._preview_until = self._clock() + min(float(seconds), PREVIEW_MAX) if seconds > 0 else None
            if self._previewing or self._preview_until is None or self.settings["enabled"]:
                return
            self._previewing = True
            self._apply()   # the engine composes what the window would show
        self._spawn(self._preview_loop)

    def _preview_loop(self):
        fresh = True
        while True:
            with self._lock:
                if (self.settings["enabled"] or self._preview_until is None
                        or self._clock() >= self._preview_until):
                    self._previewing = False
                    return
            self.engine.preview(fresh=fresh)   # the engine's own lock; Studio's isn't held while composing
            fresh = False
            self._sleep(1.0 / PREVIEW_FPS)

    def gui_ready(self):
        """The Cocoa loop is running: smart lighting can observe sleep, lock and app switches now."""
        with self._lock:
            self._gui = True
            if self.settings["enabled"]:
                self._start_smart()

    def shutdown(self):
        """Quit: stop listeners and smart lighting, restore the keyboard's own lighting. The on/off setting is
        kept, so Studio comes back at the next launch."""
        stopped = False
        with self._lock:
            self._preview_until = None
            self._cancel_pending()
            self._stop_inputs()
            self._stop_smart()
            self._save_heat()
            if self.engine.running:
                self.engine.stop(restore=False)
                stopped = True
        if stopped:
            self.engine.restore_firmware()   # after releasing the lock (see Lock order)

    # ---------- internals ----------

    def _restore_unless_on(self):
        """The keyboard's own lighting back, without Studio._lock held (the restore takes the service's lock). If
        Studio was switched on again meanwhile, the engine re-enters custom mode on its next frame anyway."""
        with self._lock:
            if self.engine.running:
                return
        self.engine.restore_firmware()

    def _persist(self):
        self._save(copy.deepcopy(self.settings), copy.deepcopy(self.smart_cfg))

    def _changed(self):
        s = self.summary()
        for cb in list(self._listeners):
            try:
                cb(s)
            except Exception:
                traceback.print_exc()

    def _shown(self):
        name = self.action.get("preset")
        return (self._find(name) if name else None) or self.working

    def _apply(self):
        """Hand the engine what should show now. set_preset only when the preset really changed, since it
        restarts typing reactions."""
        shown = self._shown()
        key = json.dumps(shown.to_dict(), sort_keys=True)
        if key != self._shown_key:
            self.engine.set_preset(shown)
            self._shown_key = key
        a = self.action
        self.engine.set_brightness(0.0 if a["off"] else self.settings["brightness"] * float(a["brightness"]))
        self._sync_inputs()

    def _on_smart(self, action):
        """Called on the main thread (sleep/lock notifications) or the smart polling thread: never waits for
        Studio._lock here. The newest action is applied on a worker thread; older pending ones are dropped."""
        with self._smart_slot:
            self._smart_next = dict(action)
            if self._smart_busy:
                return
            self._smart_busy = True
        self._spawn(self._drain_smart)

    def _drain_smart(self):
        while True:
            with self._smart_slot:
                action, self._smart_next = self._smart_next, None
                if action is None:
                    self._smart_busy = False
                    return
            try:
                with self._lock:
                    self.action = {**NEUTRAL, **action}
                    self._apply()
                    shown = dict(self.action)
                self._push("onStudioAction", shown)
            except Exception:
                traceback.print_exc()

    def _start_smart(self):
        if not self._gui or self._smart is not None:
            return
        try:
            self._smart = self._make_smart(copy.deepcopy(self.smart_cfg), self._on_smart)
            self._smart.start()
        except Exception:
            traceback.print_exc()
            self._smart = None

    def _stop_smart(self):
        s, self._smart = self._smart, None
        if s is not None:
            try:
                s.stop()
            except Exception:
                traceback.print_exc()

    def _sync_inputs(self):
        on = self.settings["enabled"] and not self.action["off"]
        needs = preset_needs(self._shown()) if on else set()
        want_keys = on and ("keys" in needs or self.settings["heat"])
        want_audio = on and "audio" in needs
        if want_keys and self._keys is None:
            self._keys = self._start("keys", lambda: self._make_keys(self.engine.push_key_event))
        elif not want_keys:
            self._stop_keys()
        if want_audio and self._audio is None:
            self._audio = self._start("audio", lambda: self._make_audio(
                self.settings["audio"]["device"], self._on_audio,
                sensitivity=self.settings["audio"]["sensitivity"], on_error=self._on_audio_error))
        elif not want_audio:
            self._stop_audio()

    def _start(self, kind, make):
        try:
            lst = make()
            lst.start()
        except Exception as e:
            if not isinstance(e, RuntimeError):
                traceback.print_exc()
            self.errors[kind] = str(e) or f"The {kind} input didn't start."
            self._push("onStudioStatus", {"errors": dict(self.errors)})
            return None
        if self.errors[kind]:
            self.errors[kind] = None
            self._push("onStudioStatus", {"errors": dict(self.errors)})
        return lst

    def restart_key_listener(self):
        """Another model was plugged in: a running key listener matches the old product id, so start a new one.
        Never call with the engine's send lock held (this takes Studio._lock); the service spawns it."""
        with self._lock:
            if self._keys is None:
                return
            self._stop_keys()
            self._sync_inputs()

    def _stop_keys(self):
        k, self._keys = self._keys, None
        if k is not None:
            k.stop()
        self.errors["keys"] = None

    def _stop_audio(self):
        a, self._audio = self._audio, None
        if a is not None:
            a.stop()
        self.errors["audio"] = None

    def _stop_inputs(self):
        self._stop_keys()
        self._stop_audio()

    def _on_audio(self, state):
        # inputs.types.AudioState and lighting.frame.AudioState carry the same fields; the engine gets its own type
        self.engine.set_audio(LightAudio(float(state.level), list(state.bands)))
        self._push("onStudioLevel", round(float(state.level), 3))

    def _on_audio_error(self, message):
        self.errors["audio"] = message
        self._push("onStudioStatus", {"errors": dict(self.errors)})

    def _load_heat(self):
        try:
            with open(self._heat_path, encoding="utf-8") as f:
                raw = json.load(f)
            return {int(k): int(v) for k, v in raw.items() if int(k) in self.keymap and int(v) >= 0}
        except (OSError, ValueError, AttributeError, TypeError):
            return {}

    def _save_heat(self):
        if not self.settings["heat"]:
            return
        counts = self.engine.heat_counts()
        tmp = f"{self._heat_path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({str(k): v for k, v in counts.items()}, f)
            os.replace(tmp, self._heat_path)
        except OSError:
            traceback.print_exc()
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


def clean_smart_strict(config):
    """For values coming from the window: all valid, or ValueError (no silent repair)."""
    from inputs.smart import normalise_config
    return normalise_config(config)
