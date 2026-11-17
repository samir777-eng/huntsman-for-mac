# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Huntsman Control: a native window for the Razer Huntsman V3 Pro on macOS."""
import contextlib
import copy
import fcntl
import json
import os
import re
import sys
import threading
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import depth_stream  # noqa: E402
import huntsman_core as hc  # noqa: E402
import studio as studio_mod  # noqa: E402

STATE_FILE = os.path.join(hc.data_dir(), "state.json")
SNAPSHOT_FILE = os.path.join(hc.data_dir(), "first-launch-snapshot.json")
DEFAULT_STATE = {
    "rapid": {"enabled": False, "press": 0.3, "release": 0.3, "keys": "all", "continuous": False},
    "snap": None,
    "effect": None,     # last built-in effect
    "custom": None,     # {"base": [r,g,b], "keys": {id: [r,g,b]}} when per-key colours are active
    "ui": {},           # interface preferences, e.g. accent colour
    "studio": studio_mod.clean_studio(None),   # Lighting Studio: on/off, active preset, fps, brightness, audio, heatmap
    "smart": studio_mod.clean_smart(None),     # smart lighting: idle, sleep, lock, per-app presets
}


ACCENT = re.compile(r"^#[0-9a-fA-F]{6}$")


def log(msg):
    print(f"huntsman: {msg}", file=sys.stderr)
    traceback.print_exc()


# ---------- input checks (the UI and the CLI are not trusted to send sane values) ----------

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_rgb(v):
    try:
        hc.check_rgb(v)
        return True
    except ValueError:
        return False


def _key_id(k):
    if _is_int(k):
        return k
    if isinstance(k, str) and k.isdigit():
        return int(k)
    raise ValueError(f"{k!r} is not a key id")


def layout_ids():
    """Every key with an LED (incl. Fn): valid targets for colours."""
    return {k["id"] for k in hc.load_layout()}


def check_key_ids(keys):
    """Key ids whose actuation may be written; empty means all. Fn (59) and unknown ids are refused."""
    allowed = hc.all_key_ids()
    ids = [_key_id(k) for k in keys] or allowed
    bad = sorted(set(ids) - set(allowed))
    if bad:
        raise ValueError(f"these keys can't be changed: {bad}")
    return ids


def check_colours(base, keys):
    """Exactly three ints 0-255 per colour, and only keys that have an LED. Returns ([r,g,b], {id: [r,g,b]})."""
    allowed = layout_ids()
    out = {}
    for k, v in dict(keys).items():
        kid = _key_id(k)
        if kid not in allowed:
            raise ValueError(f"key {k!r} has no LED")
        out[kid] = hc.check_rgb(v)
    return hc.check_rgb(base), out


# ---------- state.json ----------

def _clean_state(raw):
    """Defaults, overlaid field by field (and sub-field by sub-field) with whatever in raw is valid,
    so one bad value never throws the rest away or reaches the keyboard."""
    st = copy.deepcopy(DEFAULT_STATE)
    if not isinstance(raw, dict):
        return st
    keys = set(hc.all_key_ids())
    r = raw.get("rapid")
    if isinstance(r, dict):
        d = st["rapid"]
        for f in ("enabled", "continuous"):
            if isinstance(r.get(f), bool):
                d[f] = r[f]
        for f in ("press", "release"):
            v = r.get(f)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.1 <= round(v, 2) <= 2.5:
                d[f] = v
        k = r.get("keys")
        if k == "all" or (isinstance(k, list) and all(_is_int(i) and i in keys for i in k)):
            d["keys"] = k
    s = raw.get("snap")
    if isinstance(s, list) and len(s) == 2 and all(_is_int(i) and i in keys for i in s) and s[0] != s[1]:
        st["snap"] = s
    e = raw.get("effect")
    if isinstance(e, dict) and e.get("name") in hc.EFFECTS:
        st["effect"] = e
    c = raw.get("custom")
    if isinstance(c, dict) and _is_rgb(c.get("base")) and isinstance(c.get("keys"), dict):
        lit = {str(i) for i in layout_ids()}
        st["custom"] = {"base": c["base"], "keys": {k: v for k, v in c["keys"].items() if k in lit and _is_rgb(v)}}
    u = raw.get("ui")
    if isinstance(u, dict):
        if isinstance(u.get("accent"), str) and ACCENT.match(u["accent"]):
            st["ui"]["accent"] = u["accent"]
        if isinstance(u.get("accentMatch"), bool):
            st["ui"]["accentMatch"] = u["accentMatch"]
    st["studio"] = studio_mod.clean_studio(raw.get("studio"))
    st["smart"] = studio_mod.clean_smart(raw.get("smart"))
    return st


def load_state():
    try:
        with open(STATE_FILE) as f:
            raw = json.load(f)
    except Exception:
        raw = None
    return _clean_state(raw)


def save_state(state):
    tmp = f"{STATE_FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=1)
            f.flush()
            os.fsync(f.fileno())  # the data is on disk before the rename makes it the real file
        os.replace(tmp, STATE_FILE)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


@contextlib.contextmanager
def update_state():
    """Read-modify-write state.json under a file lock: the app, the login agent and the CLI can run
    at once, and without it one would silently undo the other's change. Saved only if the body succeeds."""
    with open(os.path.join(os.path.dirname(STATE_FILE), "state.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        st = load_state()
        yield st
        save_state(st)


def apply_saved(kb, state=None):
    """Re-send what the keyboard keeps only in RAM: per-key colours, Rapid Trigger ON, Snap Tap ON.
    Each item on its own: a refusal is logged and the rest still goes out. Returns what was sent."""
    st = state or load_state()
    steps = []
    c = st.get("custom")
    if c:
        steps.append(("per-key colours", lambda: kb.set_custom({int(k): v for k, v in c["keys"].items()},
                                                               hc.load_layout(), c["base"])))
    r = st.get("rapid") or {}
    if r.get("enabled"):
        steps.append(("Rapid Trigger", lambda: rapid_apply(kb, r)))
    if st.get("snap"):
        steps.append(("Snap Tap", lambda: kb.set_snap_tap(tuple(st["snap"]))))
    done = []
    for name, step in steps:
        try:
            step()
            done.append(name)
        except Exception:
            log(f"couldn't send {name} again")
    return done


def restore_lighting(kb, state=None):
    """Put the keyboard's own lighting back after Studio streamed frames: the saved per-key colours, else the
    saved effect, else the effect stored on the keyboard (re-sent so it shows again instead of the frame buffer)."""
    st = state or load_state()
    c, e = st.get("custom"), st.get("effect")
    if c:
        kb.set_custom({int(k): v for k, v in c["keys"].items()}, hc.load_layout(), c["base"])
    elif e:
        kb.set_effect(e["name"], **{k: v for k, v in e.items() if k != "name"})
    else:
        raw = kb.get_effect_raw()
        kb.cmd(0x0F, 0x02, list(raw))


def set_effect(kb, name, opts):
    """Apply a built-in effect and record it (shared by the app and the command line)."""
    kw = {k: opts[k] for k in ("rgb1", "rgb2", "speed", "direction") if opts.get(k) is not None}
    kb.set_effect(name, **kw)
    with update_state() as st:
        st["effect"], st["custom"] = {"name": name, **kw}, None
    return True


def ensure_snapshot(kb):
    """On first launch, keep a copy of every key's settings so they can be put back by hand.
    Written once, never overwritten; keys the firmware refuses are listed as skipped."""
    if os.path.exists(SNAPSHOT_FILE):
        return
    snap = kb.snapshot(hc.every_key_id())
    tmp = SNAPSHOT_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(snap, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SNAPSHOT_FILE)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def restore_factory(kb):
    """Every step is tried, and Rapid Trigger / Snap Tap are cleared from state.json even if the
    keyboard refuses one, so the app never re-sends them at the next login. Then any failure is raised."""
    failed, errors = [], []
    steps = [lambda: failed.extend(kb.restore_factory(hc.all_key_ids())),
             lambda: kb.set_rapid([(k, None) for k in hc.every_key_id()]),
             lambda: kb.set_continuous(False),
             lambda: kb.set_snap_tap(None)]
    for step in steps:
        try:
            step()
        except Exception as e:
            log("factory restore step failed")
            errors.append(e)
    with update_state() as st:
        st["rapid"], st["snap"] = copy.deepcopy(DEFAULT_STATE["rapid"]), None
    if errors:
        raise errors[0]
    if failed:
        raise hc.DeviceError(f"{len(failed)} keys did not confirm the factory depth")
    return st


def rapid_apply(kb, cfg):
    chosen = set(hc.all_key_ids()) if cfg["keys"] == "all" else set(check_key_ids(cfg["keys"]) if cfg["keys"] else [])
    rt = (float(cfg["press"]), float(cfg["release"]))
    kb.set_rapid([(k, rt if cfg["enabled"] and k in chosen else None) for k in hc.every_key_id()])
    kb.set_continuous(bool(cfg["enabled"] and cfg.get("continuous")))


class JsPusher:
    """Sends values to the window from one thread, newest value per function, at most `fps` rounds a second.
    window.evaluate_js waits for the main thread, so the engine and audio threads must never call it."""

    def __init__(self, window_getter, fps=15):
        self._get, self._interval = window_getter, 1.0 / fps
        self._slots, self._lock, self._wake = {}, threading.Lock(), threading.Event()
        self._thread = None
        self.visible = True

    def push(self, fn, payload):
        if self._get() is None:
            return
        with self._lock:
            self._slots[fn] = payload
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="huntsman-ui-push", daemon=True)
                self._thread.start()
        self._wake.set()

    def _run(self):
        while True:
            self._wake.wait()
            self._wake.clear()
            with self._lock:
                slots, self._slots = self._slots, {}
            win = self._get()
            for fn, payload in slots.items():
                if win is None or (fn in ("onStudioFrame", "onStudioLevel") and not self.visible):
                    continue
                try:
                    win.evaluate_js("window.%s && window.%s(%s)" % (fn, fn, json.dumps(payload)))
                except Exception:
                    traceback.print_exc()
            threading.Event().wait(self._interval)


class Api:
    def __init__(self, engine_cls=None, inputs=None):
        """engine_cls and inputs (key_listener, audio_listener, smart_lighting, list_devices, schedule) are
        for tests; the app uses lighting.engine.Engine and the real macOS inputs."""
        self._kb = None
        self._lock = threading.RLock()
        self._test = None
        self._window = None
        self._progress_open = False
        self.reapplied = []
        self._engine_cls, self._inputs = engine_cls, dict(inputs or {})
        self.studio = None
        self._studio_lock = threading.Lock()
        self._engine_broken = False
        self._pusher = JsPusher(lambda: self._window)

    # ----- Lighting Studio plumbing -----
    def _get_studio(self):
        with self._studio_lock:
            if self.studio is None:
                from lighting.engine import Engine
                from lighting.frame import Keymap
                km = Keymap.load()
                st = load_state()
                engine = (self._engine_cls or Engine)(self._engine_keyboard, km, fps=st["studio"]["fps"],
                                                      restore=self._restore_lighting, on_error=self._engine_error,
                                                      heat_enabled=st["studio"]["heat"])
                engine.on_frame(lambda f: self._pusher.push("onStudioFrame", {str(k): list(v) for k, v in f.items()}))
                s = studio_mod.Studio(engine, st["studio"], st["smart"], save=self._save_studio, keymap=km,
                                      push=self._pusher.push, **self._inputs)
                s.on_change(lambda summary: self._pusher.push("onStudioChanged", summary))
                self.studio = s
            return self.studio

    def _save_studio(self, settings, smart):
        with update_state() as st:
            st["studio"], st["smart"] = settings, smart

    def _engine_keyboard(self):
        """The engine's keyboard: the app's own connection. Called by the engine thread while it holds its send
        lock, and every other use of self._kb runs with the engine paused, so the two never overlap. Never takes
        self._lock (an app call holding it may be waiting for the engine to pause)."""
        if self._engine_broken:
            self._engine_broken = False
            if self._kb is not None and hasattr(self._kb.t, "close"):
                self._kb.t.close()
            self._kb = None
        return self._keyboard()

    def _engine_error(self, e):
        if isinstance(e, (hc.DeviceError, OSError)):
            self._engine_broken = True   # reconnect on the next try
        self._pusher.push("onStudioStatus", {"engine": str(e)})

    def _restore_lighting(self):
        with self._lock:
            restore_lighting(self._keyboard())

    def _paused(self):
        return self.studio.engine.paused() if self.studio is not None else contextlib.nullcontext()

    def _studio_call(self, fn):
        try:
            return {"ok": True, "data": fn(self._get_studio())}
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def _studio_off_for_firmware(self):
        """The keyboard's own effects and per-key colours replace Studio: stop streaming first (no restore,
        since the caller is about to set the lighting)."""
        if self.studio is not None and self.studio.settings["enabled"]:
            self.studio.set_enabled(False, restore=False)

    def app_state(self):
        return self._get_studio().summary()

    def gui_ready(self):
        self._get_studio().gui_ready()

    def shutdown(self):
        """Quit: stop a key test, the engine (restoring the keyboard's lighting), listeners and smart lighting."""
        self.stop_test()
        if self.studio is not None:
            try:
                self.studio.shutdown()
            except Exception:
                traceback.print_exc()

    def _keyboard(self):
        """Connect; on every (re)connect put a keyboard stuck in driver mode back to typing (a crash
        during a key test leaves it there) and re-send the RAM-only settings, since a replug drops them.
        Neither the snapshot nor the re-send may block connecting: failures are logged."""
        if self._kb is None:
            kb = hc.Keyboard()
            depth_stream.recover_typing(kb)
            try:
                ensure_snapshot(kb)
            except Exception:
                log("couldn't save the first-launch snapshot")
            self.reapplied = apply_saved(kb)
            self._kb = kb
        return self._kb

    def _drop(self):
        """Forget the handle so the next call reconnects. A running key test is stopped first: it needs
        the transport to switch the keyboard back to typing."""
        t = self._test
        if t and t.running:
            t.stop("Testing stopped because the keyboard reconnected.")
        if self._kb is not None and hasattr(self._kb.t, "close"):
            self._kb.t.close()
        self._kb = None

    def _run(self, fn):
        """Serialize device access, with the Studio engine paused (it shares the connection); drop the handle
        on device failure so a replug reconnects."""
        with self._lock, self._paused():
            try:
                return {"ok": True, "data": fn(self._keyboard())}
            except ValueError as e:  # bad input: the connection is fine, keep it
                return {"ok": False, "error": str(e)}
            except Exception as e:
                traceback.print_exc()
                self._drop()
                return {"ok": False, "error": str(e)}
            finally:
                if self._progress_open:  # a long operation stopped part-way: don't leave the bar showing
                    self._progress(1, 1)

    def _progress(self, done, total):
        self._progress_open = done < total
        if self._window:
            self._window.evaluate_js(f"window.onProgress && window.onProgress({done},{total})")

    # ----- reads -----
    def layout(self):
        return hc.load_layout()

    def effects(self):
        return {n: {"speed": s, "colors": t.count("{rgb"), "dir": "{dir}" in t} for n, (t, s) in hc.EFFECTS.items()}

    def reconnect(self):
        with self._lock, self._paused():
            self._drop()
        return self._run(lambda kb: self.reapplied)

    def info(self):
        def f(kb):
            return {"version": hc.__version__, "firmware": kb.firmware(), "profile": kb.saved,
                    "brightness": kb.brightness(), "effect": kb.get_effect_raw().hex(),
                    "state": load_state()}
        return self._run(f)

    def startup(self):
        """Re-apply RAM-only settings once when the app opens."""
        return self._run(lambda kb: self.reapplied)

    def read_depths(self):
        def f(kb):
            ids = hc.all_key_ids()
            out = {}
            for i, k in enumerate(ids):
                out[k] = kb.read_points(k)
                if i % 8 == 0:
                    self._progress(i, len(ids))
            self._progress(len(ids), len(ids))
            return out
        return self._run(f)

    # ----- writes -----
    def set_depth(self, keys, mm, release_mm=None):
        try:
            ids = check_key_ids(keys)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        def f(kb):
            failed, done, n = [], [], len(ids)
            for i, k in enumerate(ids):  # the first half of the bar: writes; the second: reading them back
                if kb.set_actuation([k], mm, release_mm):
                    failed.append(k)
                else:
                    done.append(k)
                self._progress(i + 1, 2 * n)
            points = {}
            for j, k in enumerate(done):
                points[k] = kb.read_points(k)
                self._progress(n + j + 1, n + len(done))
            # if no key confirmed, _run's finally completes the bar
            return {"failed": failed, "done": points, "count": n}
        return self._run(f)

    # ----- key tester -----
    def start_test(self):
        def f(kb):
            if self._test and self._test.running:
                return True

            def batch(items):
                if self._window:
                    self._window.evaluate_js("window.onDepth && window.onDepth(%s)" % json.dumps(items))

            # driver mode: the engine must not send frames until the keyboard types again
            hold = self.studio.engine if self.studio is not None else None
            if hold is not None:
                hold.pause()

            def ended(reason, ok):
                # Runs on whatever thread stopped the test (possibly the main thread while the window
                # closes), so the follow-up work goes to a background thread and never blocks.
                nonlocal hold
                if hold is not None:  # resume exactly once, however often the session reports its end
                    hold.resume()
                    hold = None

                def follow_up():
                    if ok:  # a mode switch reloads the live profile from flash: re-send RAM-only settings
                        try:
                            with self._lock:
                                apply_saved(kb)
                        except Exception:
                            traceback.print_exc()
                    if self._window and reason:
                        try:
                            self._window.evaluate_js("window.onTestEnded && window.onTestEnded(%s, %s)"
                                                     % (json.dumps(reason), json.dumps(ok)))
                        except Exception:
                            pass
                threading.Thread(target=follow_up, daemon=True).start()

            self._test = depth_stream.DepthSession(kb, batch, ended)
            return self._test.start()
        return self._run(f)

    def stop_test(self):
        """Never takes the app lock: it must work while another call is busy or the window is closing."""
        t = self._test
        if t and not t.stop():
            return {"ok": False, "error": "The keyboard may still be in test mode. Unplug it and plug it back in."}
        return {"ok": True, "data": []}

    def set_rapid(self, cfg):
        def f(kb):
            rapid_apply(kb, cfg)
            with update_state() as st:
                st["rapid"] = cfg
            return True
        return self._run(f)

    def set_snap(self, pair):
        def f(kb):
            p = (int(pair[0]), int(pair[1])) if pair else None
            kb.set_snap_tap(p)
            with update_state() as st:
                st["snap"] = list(p) if p else None
            return True
        return self._run(f)

    def set_effect(self, name, opts):
        self._studio_off_for_firmware()
        return self._run(lambda kb: set_effect(kb, name, opts))

    def set_custom(self, base, keys):
        try:
            base, colours = check_colours(base, keys)
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": str(e)}

        self._studio_off_for_firmware()

        def f(kb):
            kb.set_custom(colours, hc.load_layout(), base)
            with update_state() as st:
                st["custom"] = {"base": base, "keys": {str(k): v for k, v in colours.items()}}
            return True
        return self._run(f)

    def set_prefs(self, prefs):
        """Interface preferences (accent colour), saved together. Not sent to the keyboard."""
        prefs = {k: v for k, v in dict(prefs).items() if k in ("accent", "accentMatch")}
        if "accent" in prefs and not (isinstance(prefs["accent"], str) and ACCENT.match(prefs["accent"])):
            return {"ok": False, "error": "accent must be a colour like #3ddc84"}
        if "accentMatch" in prefs and not isinstance(prefs["accentMatch"], bool):
            return {"ok": False, "error": "accentMatch must be true or false"}
        with self._lock, update_state() as st:
            st["ui"].update(prefs)
        return {"ok": True, "data": True}

    def set_brightness(self, pct):
        """While the slider drags: live only, so flash isn't rewritten on every step."""
        return self._run(lambda kb: kb.set_brightness(pct, stores=(0,)))

    def save_brightness(self, pct):
        """When the slider is released: saved on the keyboard so it survives a replug."""
        return self._run(lambda kb: kb.set_brightness(pct, stores=(1,)))

    def restore_original(self):
        return self._run(restore_factory)

    # ----- Lighting Studio (each returns {"ok", "data" | "error"}; inputs are validated in studio.py) -----
    def studio_state(self):
        return self._studio_call(lambda s: s.state())

    def studio_enable(self, on):
        return self._studio_call(lambda s: s.set_enabled(on))

    def set_active_preset(self, name):
        return self._studio_call(lambda s: s.set_active(name))

    def save_preset(self, preset):
        return self._studio_call(lambda s: s.save_preset(preset))

    def delete_preset(self, name):
        return self._studio_call(lambda s: s.delete_preset(name))

    def rename_preset(self, old, new):
        return self._studio_call(lambda s: s.rename_preset(old, new))

    def duplicate_preset(self, name, new=None):
        return self._studio_call(lambda s: s.duplicate_preset(name, new))

    def update_layers(self, layers):
        return self._studio_call(lambda s: s.update_layers(layers))

    def set_studio_brightness(self, level):
        return self._studio_call(lambda s: s.set_brightness(level))

    def set_fps(self, fps):
        return self._studio_call(lambda s: s.set_fps(fps))

    def set_audio_device(self, device):
        return self._studio_call(lambda s: s.set_audio_device(device))

    def set_audio_sensitivity(self, value):
        return self._studio_call(lambda s: s.set_audio_sensitivity(value))

    def set_heat(self, on):
        return self._studio_call(lambda s: s.set_heat(on))

    def reset_heat(self):
        return self._studio_call(lambda s: s.reset_heat())

    def set_smart(self, config):
        return self._studio_call(lambda s: s.set_smart(config))

    def import_preset(self, text):
        return self._studio_call(lambda s: s.import_preset(text))

    def export_preset(self, name):
        """{"json": text}; in the app also asks where to save it and returns {"path"} (None if cancelled)."""
        def f(s):
            text = s.export_preset(name)
            if self._window is None:
                return {"json": text}
            import webview
            safe = re.sub(r"[^\w\- ]+", "", name).strip() or "preset"
            path = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=f"{safe}.json")
            if not path:
                return {"path": None}
            path = path[0] if isinstance(path, (list, tuple)) else path
            with open(path, "w") as fh:
                fh.write(text)
            return {"path": path}
        return self._studio_call(f)

    def running_apps(self):
        """Open apps with a Dock icon, for per-app rules: [{"name", "bundle_id"}]."""
        try:
            from AppKit import NSWorkspace
            apps = NSWorkspace.sharedWorkspace().runningApplications()
            out = sorted({(str(a.localizedName() or a.bundleIdentifier()), str(a.bundleIdentifier()))
                          for a in apps if a.activationPolicy() == 0 and a.bundleIdentifier()})
            return {"ok": True, "data": [{"name": n, "bundle_id": b} for n, b in out]}
        except Exception as e:
            return {"ok": False, "error": f"Couldn't list open apps: {e}"}


def set_dock_icon(visible):
    """Regular app (Dock icon, app menu) while the window shows; accessory (menu bar only) while hidden.
    Main thread only."""
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().setActivationPolicy_(0 if visible else 1)
    except Exception:
        traceback.print_exc()


def on_main(fn):
    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(fn)
    except Exception:
        traceback.print_exc()


def in_background(fn):
    threading.Thread(target=fn, daemon=True).start()


def main(argv=None):
    """--background (the login item): start with the window hidden and only the menu bar icon showing.
    Closing the window keeps the app in the menu bar while Studio lighting is on (it needs this process);
    otherwise it quits as before. Quit from the menu bar stops Studio and restores the keyboard's lighting."""
    import webview

    from menubar import StatusMenu
    background = "--background" in (sys.argv[1:] if argv is None else argv)
    api = Api()
    win = webview.create_window("Huntsman for Mac", os.path.join(HERE, "ui", "index.html"), js_api=api,
                                width=1280, height=900, min_size=(1000, 720), background_color="#0e1013",
                                hidden=background)
    api._window = win
    api._pusher.visible = not background
    quitting = threading.Event()

    def hide():
        api._pusher.visible = False
        win.hide()
        on_main(lambda: set_dock_icon(False))

    def closing():
        api.stop_test()  # never waits on the app lock (see stop_test)
        if quitting.is_set():
            return None
        if api.studio is not None and api.studio.settings["enabled"]:
            hide()
            return False  # pywebview 6.2.1 runs `closing` on the main thread and cancels the close on False
        quitting.set()
        api.shutdown()
        return None

    def open_window():
        api._pusher.visible = True
        set_dock_icon(True)
        win.show()

    def quit_app():
        quitting.set()

        def work():
            api.shutdown()
            win.destroy()
        in_background(work)

    def toggle(on):
        in_background(lambda: api.studio_enable(on))

    def pick(name):
        def work():
            api.set_active_preset(name)
            if not api.studio.settings["enabled"]:
                api.studio_enable(True)
        in_background(work)

    win.events.closing += closing
    depth_stream.install_signal_stop()  # force quit / logout: switch a running key test back first

    def started():
        s = api._get_studio()
        summary = s.summary()
        menu = StatusMenu(toggle, pick, lambda: on_main(open_window), quit_app, presets=summary["presets"],
                          enabled=summary["enabled"], active=summary["active"])
        s.on_change(lambda m: menu.set_state(enabled=m["enabled"], presets=m["presets"], active=m["active"]))
        menu.install_soon()
        if background:
            on_main(lambda: set_dock_icon(False))
        api.startup()   # connect and re-send what the keyboard keeps only in RAM (what the login item is for)
        api.gui_ready()
        if s.settings["enabled"]:
            api.studio_enable(True)

    webview.start(started)
    api.shutdown()


if __name__ == "__main__":
    main()
