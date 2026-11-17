"""Huntsman Control: a native window for the Razer Huntsman V3 Pro on macOS."""
import json
import os
import sys
import threading
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import huntsman_core as hc  # noqa: E402

STATE_FILE = os.path.join(hc.data_dir(), "state.json")
SNAPSHOT_FILE = os.path.join(hc.data_dir(), "first-launch-snapshot.json")
DEFAULT_STATE = {
    "rapid": {"enabled": False, "press": 0.3, "release": 0.3, "keys": "all", "continuous": False},
    "snap": None,
    "effect": None,     # last built-in effect
    "custom": None,     # {"base": [r,g,b], "keys": {id: [r,g,b]}} when per-key colours are active
    "ui": {},           # interface preferences, e.g. accent colour
}


def load_state():
    try:
        with open(STATE_FILE) as f:
            return {**DEFAULT_STATE, **json.load(f)}
    except Exception:
        return json.loads(json.dumps(DEFAULT_STATE))


def save_state(state):
    tmp = f"{STATE_FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE_FILE)


def apply_saved(kb, state=None):
    """Re-send what the keyboard keeps only in RAM: per-key colours, Rapid Trigger ON, Snap Tap ON."""
    st = state or load_state()
    done = []
    c = st.get("custom")
    if c:
        kb.set_custom({int(k): v for k, v in c["keys"].items()}, hc.load_layout(), c["base"])
        done.append("per-key colours")
    r = st.get("rapid") or {}
    if r.get("enabled"):
        rapid_apply(kb, r)
        done.append("Rapid Trigger")
    if st.get("snap"):
        kb.set_snap_tap(tuple(st["snap"]))
        done.append("Snap Tap")
    return done


def set_effect(kb, name, opts):
    """Apply a built-in effect and record it (shared by the app and the command line)."""
    kw = {k: opts[k] for k in ("rgb1", "rgb2", "speed", "direction") if opts.get(k) is not None}
    kb.set_effect(name, **kw)
    st = load_state()
    st["effect"], st["custom"] = {"name": name, **kw}, None
    save_state(st)
    return True


def ensure_snapshot(kb):
    """On first launch, keep a copy of every key's settings so they can be put back by hand."""
    if os.path.exists(SNAPSHOT_FILE):
        return
    snap = kb.snapshot(hc.every_key_id())
    tmp = SNAPSHOT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snap, f)
    os.replace(tmp, SNAPSHOT_FILE)


def restore_factory(kb):
    failed = kb.restore_factory(hc.all_key_ids())
    kb.set_rapid([(k, None) for k in hc.every_key_id()])
    kb.set_continuous(False)
    kb.set_snap_tap(None)
    st = load_state()
    st["rapid"], st["snap"] = DEFAULT_STATE["rapid"], None
    save_state(st)
    if failed:
        raise hc.DeviceError(f"{len(failed)} keys did not confirm the factory depth")
    return st


def rapid_apply(kb, cfg):
    chosen = set(hc.all_key_ids()) if cfg["keys"] == "all" else {int(k) for k in cfg["keys"]}
    rt = (float(cfg["press"]), float(cfg["release"]))
    kb.set_rapid([(k, rt if cfg["enabled"] and k in chosen else None) for k in hc.every_key_id()])
    kb.set_continuous(bool(cfg["enabled"] and cfg.get("continuous")))


class Api:
    def __init__(self):
        self._kb = None
        self._lock = threading.RLock()
        self._test = None
        self._window = None
        self.reapplied = []

    def _keyboard(self):
        """Connect; on every (re)connect re-send the RAM-only settings, since a replug drops them."""
        if self._kb is None:
            kb = hc.Keyboard()
            ensure_snapshot(kb)
            self.reapplied = apply_saved(kb)
            self._kb = kb
        return self._kb

    def _run(self, fn):
        """Serialize device access; drop the handle on failure so a replug reconnects."""
        with self._lock:
            try:
                return {"ok": True, "data": fn(self._keyboard())}
            except Exception as e:
                if self._kb is not None:
                    self._kb.t.close() if hasattr(self._kb.t, "close") else None
                self._kb = None
                traceback.print_exc()
                return {"ok": False, "error": str(e)}

    def _progress(self, done, total):
        if self._window:
            self._window.evaluate_js(f"window.onProgress && window.onProgress({done},{total})")

    # ----- reads -----
    def layout(self):
        return hc.load_layout()

    def effects(self):
        return {n: {"speed": s, "colors": t.count("{rgb"), "dir": "{dir}" in t} for n, (t, s) in hc.EFFECTS.items()}

    def reconnect(self):
        with self._lock:
            if self._kb is not None and hasattr(self._kb.t, "close"):
                self._kb.t.close()
            self._kb = None
        return self._run(lambda kb: self.reapplied)

    def info(self):
        def f(kb):
            return {"firmware": kb.firmware(), "profile": kb.saved,
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
        def f(kb):
            ids = [int(k) for k in keys] or hc.all_key_ids()
            failed, done = [], []
            for i, k in enumerate(ids):
                if kb.set_actuation([k], mm, release_mm):
                    failed.append(k)
                else:
                    done.append(k)
                self._progress(i + 1, len(ids))
            return {"failed": failed, "done": {k: kb.read_points(k) for k in done}, "count": len(ids)}
        return self._run(f)

    # ----- key tester -----
    def start_test(self):
        def f(kb):
            import depth_stream
            if self._test and self._test.running:
                return True

            def batch(items):
                if self._window:
                    self._window.evaluate_js("window.onDepth && window.onDepth(%s)" % json.dumps(items))

            def ended(reason, ok):
                # Runs on whatever thread stopped the test (possibly the main thread while the window
                # closes), so the follow-up work goes to a background thread and never blocks.
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
            self._test.start()
            return True
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
            st = load_state()
            st["rapid"] = cfg
            save_state(st)
            return True
        return self._run(f)

    def set_snap(self, pair):
        def f(kb):
            p = (int(pair[0]), int(pair[1])) if pair else None
            kb.set_snap_tap(p)
            st = load_state()
            st["snap"] = list(p) if p else None
            save_state(st)
            return True
        return self._run(f)

    def set_effect(self, name, opts):
        return self._run(lambda kb: set_effect(kb, name, opts))

    def set_custom(self, base, keys):
        def f(kb):
            kb.set_custom({int(k): v for k, v in keys.items()}, hc.load_layout(), base)
            st = load_state()
            st["custom"] = {"base": base, "keys": {str(k): v for k, v in keys.items()}}
            save_state(st)
            return True
        return self._run(f)

    def set_prefs(self, prefs):
        """Interface preferences (accent colour), saved together. Not sent to the keyboard."""
        prefs = {k: v for k, v in dict(prefs).items() if k in ("accent", "accentMatch")}
        with self._lock:
            st = load_state()
            st.setdefault("ui", {}).update(prefs)
            save_state(st)
        return {"ok": True, "data": True}

    def set_brightness(self, pct):
        return self._run(lambda kb: kb.set_brightness(pct))

    def restore_original(self):
        return self._run(restore_factory)


def main():
    import webview
    api = Api()
    win = webview.create_window("Huntsman for Mac", os.path.join(HERE, "ui", "index.html"), js_api=api,
                                width=1280, height=900, min_size=(1000, 720), background_color="#0e1013")
    api._window = win
    win.events.closing += lambda: api.stop_test()  # never waits on the app lock (see stop_test)
    webview.start()


if __name__ == "__main__":
    main()
