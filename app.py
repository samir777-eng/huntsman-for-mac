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

STATE_FILE = os.path.join(hc.data_dir(), "state.json")
SNAPSHOT_FILE = os.path.join(hc.data_dir(), "first-launch-snapshot.json")
DEFAULT_STATE = {
    "rapid": {"enabled": False, "press": 0.3, "release": 0.3, "keys": "all", "continuous": False},
    "snap": None,
    "effect": None,     # last built-in effect
    "custom": None,     # {"base": [r,g,b], "keys": {id: [r,g,b]}} when per-key colours are active
    "ui": {},           # interface preferences, e.g. accent colour
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


class Api:
    def __init__(self):
        self._kb = None
        self._lock = threading.RLock()
        self._test = None
        self._window = None
        self.reapplied = []

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
        """Serialize device access; drop the handle on device failure so a replug reconnects."""
        with self._lock:
            try:
                return {"ok": True, "data": fn(self._keyboard())}
            except ValueError as e:  # bad input: the connection is fine, keep it
                return {"ok": False, "error": str(e)}
            except Exception as e:
                traceback.print_exc()
                self._drop()
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
            self._drop()
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
        try:
            ids = check_key_ids(keys)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        def f(kb):
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
        return self._run(lambda kb: set_effect(kb, name, opts))

    def set_custom(self, base, keys):
        try:
            base, colours = check_colours(base, keys)
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": str(e)}

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


def main():
    import webview
    api = Api()
    win = webview.create_window("Huntsman for Mac", os.path.join(HERE, "ui", "index.html"), js_api=api,
                                width=1280, height=900, min_size=(1000, 720), background_color="#0e1013")
    api._window = win
    win.events.closing += lambda: api.stop_test()  # never waits on the app lock (see stop_test)
    depth_stream.install_signal_stop()  # force quit / logout: switch a running key test back first
    webview.start()


if __name__ == "__main__":
    main()
