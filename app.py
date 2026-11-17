# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Huntsman for Mac: the control panel window for the Razer Huntsman V3 Pro on macOS.

Keyboard settings (actuation, firmware lighting, per-key colours, key tester) run here; Lighting Studio runs in the
background lighting service (service.py), reached through ServiceLink. Every keyboard operation here holds a pause
lease on the service so its frames never interleave with them."""
import contextlib
import copy
import fcntl
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import depth_stream  # noqa: E402
import huntsman_core as hc  # noqa: E402
import ipc  # noqa: E402
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
    "experimental": False,  # Keyboard -> Experimental support: writes to untested models (huntsman_core.gate)
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
    st["experimental"] = raw.get("experimental") is True
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
    saved effect, else the effect stored on the keyboard (re-sent so it shows again instead of the frame buffer).
    Effects go to RAM (store 0): flash already holds them, and this runs on every Studio stop and quit."""
    st = state or load_state()
    c, e = st.get("custom"), st.get("effect")
    if c:
        kb.set_custom({int(k): v for k, v in c["keys"].items()}, hc.load_layout(), c["base"])
    elif e:
        kb.set_effect(e["name"], store=0, **{k: v for k, v in e.items() if k != "name"})
    else:
        raw = kb.get_effect_raw()   # [store, led, effect...] as read from flash
        kb.cmd(0x0F, 0x02, [0] + list(raw[1:]))


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
    """Sends values to the window from one thread, newest call per function, at most `fps` rounds a second.
    window.evaluate_js waits for the main thread, so no other thread may call it: not the engine or audio
    threads, and nothing holding Api._lock (the main thread may be waiting for that lock)."""

    def __init__(self, window_getter, fps=15):
        self._get, self._interval = window_getter, 1.0 / fps
        self._slots, self._lock, self._wake = {}, threading.Lock(), threading.Event()
        self._thread = None
        self.visible = True

    def push(self, fn, *args):
        """Call window.fn(*args) soon; a newer push to the same fn replaces one not sent yet."""
        if self._get() is None:
            return
        with self._lock:
            self._slots[fn] = args
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
            for fn, args in slots.items():
                if win is None or (fn in ("onStudioFrame", "onStudioLevel") and not self.visible):
                    continue
                try:
                    win.evaluate_js("window.%s && window.%s(%s)" % (fn, fn, ",".join(json.dumps(a) for a in args)))
                except Exception:
                    traceback.print_exc()
            threading.Event().wait(self._interval)


LIGHTING_LABEL = "io.github.huntsman-for-mac.lighting"
LEASE_SECONDS = 5.0
SERVICE_EVENTS = ("onStudioFrame", "onStudioChanged", "onStudioStatus", "onStudioAction", "onStudioLevel")
NOT_RUNNING = ("The lighting service isn't running and couldn't be started ({}). "
               "Reinstall with ./install.sh, or check ~/Library/Logs/Huntsman for Mac.log.")


def service_socket():
    return os.path.join(hc.data_dir(), "service.sock")


def start_service():
    """Ask launchd to start the lighting service if it isn't running (never -k: killing a service that is still
    starting would interrupt a USB write); load its LaunchAgent first if it isn't loaded."""
    target = f"gui/{os.getuid()}/{LIGHTING_LABEL}"
    r = subprocess.run(["launchctl", "kickstart", target], capture_output=True, text=True, timeout=10)
    if r.returncode == 0:
        return
    plist = os.path.expanduser(f"~/Library/LaunchAgents/{LIGHTING_LABEL}.plist")
    if not os.path.exists(plist):
        raise RuntimeError("its login item isn't installed")
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", plist], capture_output=True, text=True, timeout=10)
    r = subprocess.run(["launchctl", "kickstart", target], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "launchctl kickstart failed").strip())


class Lease:
    """A pause lease on the lighting service: the engine sends no frames while it is held. Renewed on a thread
    every renew_every seconds, so a long operation (or a key test) keeps it; if this app dies the lease
    expires on its own. Without a running service it does nothing (no engine to pause)."""

    def __init__(self, link, seconds, renew_every):
        self._link, self._seconds, self._every = link, seconds, renew_every
        self.token, self._stop = None, threading.Event()

    def acquire(self):
        r = self._link.call("pause", {"lease_seconds": self._seconds})
        if r["ok"]:
            self.token = r["data"]["token"]
            threading.Thread(target=self._renew, name="huntsman-lease", daemon=True).start()
        elif not r.get("unavailable"):
            print(f"huntsman: couldn't pause the lighting service: {r['error']}", file=sys.stderr)
        return self

    def _renew(self):
        while not self._stop.wait(self._every):
            tok = self.token
            if tok is None:
                return
            r = self._link.call("pause", {"lease_seconds": self._seconds, "token": tok})
            if not r["ok"] and not r.get("unavailable"):
                self.token = None   # the service restarted: take a new lease
                self.acquire()
                return

    def release(self):
        self._stop.set()
        tok, self.token = self.token, None
        if tok is not None:
            self._link.call("resume", {"token": tok})

    def abandon(self):
        """Stop renewing without resuming: the lease expires and the service checks the keyboard first."""
        self._stop.set()
        self.token = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


class ServiceLink:
    """The app's side of the lighting service socket. connect() -> object with request(cmd, args) (an
    ipc.Client by default); starter() starts the service (start_service by default)."""

    def __init__(self, connect=None, starter=None, wait=10.0, lease_seconds=LEASE_SECONDS, renew_every=None):
        self._client = None
        self._connect = connect or (lambda: self._default_client())
        self._starter = starter or start_service
        self._wait, self._lease_seconds = wait, lease_seconds
        self._renew_every = renew_every or lease_seconds / 2.5
        self._lock = threading.Lock()

    def _default_client(self):
        if self._client is None:
            self._client = ipc.Client(service_socket())
        return self._client

    def _request(self, cmd, args):
        return self._connect().request(cmd, args)

    def call(self, cmd, args=None, start=False):
        """{"ok", "data" | "error"}; "unavailable": True when the service isn't running (and start is False or
        starting it failed)."""
        try:
            return self._request(cmd, args or {})
        except ipc.ServiceUnavailable as e:
            if not start:
                return {"ok": False, "error": NOT_RUNNING.format(e), "unavailable": True}
        with self._lock:   # one start at a time
            try:
                return self._request(cmd, args or {})
            except ipc.ServiceUnavailable:
                pass
            try:
                self._starter()
            except Exception as e:
                return {"ok": False, "error": NOT_RUNNING.format(e), "unavailable": True}
            deadline = time.monotonic() + self._wait
            while True:
                try:
                    return self._request(cmd, args or {})
                except ipc.ServiceUnavailable as e:
                    if time.monotonic() >= deadline:
                        return {"ok": False, "error": NOT_RUNNING.format(f"no answer: {e}"), "unavailable": True}
                    time.sleep(0.1)

    def lease(self):
        return Lease(self, self._lease_seconds, self._renew_every)

    def subscribe(self, on_event):
        return ipc.Subscription(service_socket(), on_event, frames=True)


class Api:
    def __init__(self, service=None):
        """service: a ServiceLink to the lighting service (tests pass one with a fake connection)."""
        self._kb = None
        self._lock = threading.RLock()
        self._test = None
        self._test_lease = None
        self._window = None
        self._progress_open = False
        self.reapplied = []
        self._svc = service or ServiceLink()
        self._events = None
        self._pusher = JsPusher(lambda: self._window)

    # ----- the lighting service -----
    def _paused(self):
        """Around every keyboard operation: the service's engine sends no frames meanwhile."""
        return self._svc.lease()

    def _studio(self, cmd, **args):
        return {k: v for k, v in self._svc.call(cmd, args, start=True).items() if k != "unavailable"}

    def _on_service_event(self, name, args):
        """Events from the service go to the window. Names are checked: they become JavaScript."""
        if name in SERVICE_EVENTS and isinstance(args, list):
            self._pusher.push(name, *args)

    def start_events(self):
        if self._events is None:
            self._events = self._svc.subscribe(self._on_service_event)

    def _studio_off_for_firmware(self):
        """The keyboard's own effects and per-key colours replace Studio: stop streaming first (no restore,
        since the caller is about to set the lighting). Doesn't start a service that isn't running."""
        r = self._svc.call("studio_enable", {"on": False, "restore": False})
        if not r["ok"] and not r.get("unavailable"):
            print(f"huntsman: couldn't turn Studio off: {r['error']}", file=sys.stderr)

    def shutdown(self):
        """Quit: stop a key test and the event stream. Studio keeps running in the lighting service."""
        self.stop_test()
        ev, self._events = self._events, None
        if ev is not None:
            ev.close()

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
        """Through the pusher: callers hold self._lock, and evaluate_js would wait for the main thread."""
        self._progress_open = done < total
        self._pusher.push("onProgress", done, total)

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
                self._pusher.push("onDepth", items)

            # driver mode: the lighting service must not send frames until the keyboard types again. The lease
            # outlives this call (renewed while the test runs); a failed switch-back abandons it, so it expires
            # and the service switches a stuck keyboard back to typing before it sends frames again.
            hold_lock = threading.Lock()
            hold = [self._svc.lease().acquire()]
            self._test_lease = hold[0]

            def release(stuck=False):
                """Exactly once."""
                with hold_lock:
                    h, hold[0] = hold[0], None
                if h is None:
                    return
                if self._test_lease is h:
                    self._test_lease = None
                if stuck:
                    h.abandon()
                else:
                    h.release()

            def ended(reason, ok):
                # Runs on whatever thread stopped the test (possibly the main thread while the window
                # closes), so the follow-up work goes to a background thread and never blocks.
                if not ok:
                    release(stuck=True)

                def follow_up():
                    try:
                        if ok:  # a mode switch reloads the live profile from flash: re-send RAM-only settings
                            with self._lock:
                                apply_saved(kb, load_state())   # under the test's lease; Studio re-sends after
                    except Exception:
                        traceback.print_exc()
                    finally:
                        release(stuck=not ok)
                    if reason:
                        self._pusher.push("onTestEnded", reason, ok)
                in_background(follow_up)

            self._test = depth_stream.DepthSession(kb, batch, ended)
            try:
                started = self._test.start()
            except BaseException:
                release()   # never started, or stopped again (a failed switch-back already kept the hold)
                raise
            if not started:
                release()
            return started
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

    # ----- Lighting Studio: proxied to the lighting service (started if needed); each returns {"ok", ...} -----
    def studio_state(self):
        return self._studio("studio_state")

    def studio_enable(self, on):
        return self._studio("studio_enable", on=on)

    def set_active_preset(self, name):
        return self._studio("set_active_preset", name=name)

    def save_preset(self, preset):
        return self._studio("save_preset", preset=preset)

    def delete_preset(self, name):
        return self._studio("delete_preset", name=name)

    def rename_preset(self, old, new):
        return self._studio("rename_preset", old=old, new=new)

    def duplicate_preset(self, name, new=None):
        return self._studio("duplicate_preset", name=name, new=new)

    def update_layers(self, layers):
        return self._studio("update_layers", layers=layers)

    def set_studio_brightness(self, level):
        return self._studio("set_studio_brightness", level=level)

    def set_fps(self, fps):
        return self._studio("set_fps", fps=fps)

    def set_audio_device(self, device):
        return self._studio("set_audio_device", device=device)

    def set_audio_sensitivity(self, value):
        return self._studio("set_audio_sensitivity", value=value)

    def set_heat(self, on):
        return self._studio("set_heat", on=on)

    def reset_heat(self):
        return self._studio("reset_heat")

    def set_smart(self, config):
        return self._studio("set_smart", config=config)

    def import_preset(self, text):
        return self._studio("import_preset", text=text)

    def running_apps(self):
        return self._studio("running_apps")

    def export_preset(self, name):
        """{"json": text}; in the app also asks where to save it and returns {"path"} (None if cancelled)."""
        r = self._studio("export_preset", name=name)
        if not r["ok"]:
            return r
        text = r["data"]
        if self._window is None:
            return {"ok": True, "data": {"json": text}}
        try:
            import webview
            safe = re.sub(r"[^\w\- ]+", "", name).strip() or "preset"
            path = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=f"{safe}.json")
            if not path:
                return {"ok": True, "data": {"path": None}}
            path = path[0] if isinstance(path, (list, tuple)) else path
            with open(path, "w") as fh:
                fh.write(text)
            return {"ok": True, "data": {"path": path}}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}


def in_background(fn):
    threading.Thread(target=fn, daemon=True).start()


def main(argv=None):
    """The control panel window. Studio lighting runs in the lighting service (service.py), which keeps going
    after this window quits; closing the window (red button, Cmd-Q, the app menu) quits the app normally.
    SIGTERM/SIGHUP switch a running key test back to typing first."""
    import webview

    api = Api()
    win = webview.create_window("Huntsman for Mac", os.path.join(HERE, "ui", "index.html"), js_api=api,
                                width=1280, height=900, min_size=(1000, 720), background_color="#0e1013")
    api._window = win

    def closing():
        api.stop_test()  # never waits on the app lock (see stop_test)
        api.shutdown()
        return None

    win.events.closing += closing
    depth_stream.add_shutdown_hook(api.shutdown)
    depth_stream.install_signal_stop()  # SIGTERM / SIGHUP: switch a running key test back, shut down, exit

    def started():
        api.start_events()   # live preview and state changes from the lighting service

    webview.start(started)
    api.shutdown()


if __name__ == "__main__":
    main()
