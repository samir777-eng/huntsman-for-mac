# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Huntsman for Mac: the control panel window for the Razer Huntsman V3 Pro on macOS.

Keyboard settings (actuation, firmware lighting, per-key colours, key tester) run here; Lighting Studio runs in the
background lighting service (service.py), reached through ServiceLink. Every keyboard operation here holds a pause
lease on the service so its frames never interleave with them."""
import contextlib
import copy
import json
import os
import plistlib
import re
import shlex
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
import platforms  # noqa: E402
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
    "autostart_added": False,   # Windows: this app wrote the start-at-login Run value once (ensure_autostart)
}


TABS = ("actuation", "rapid", "snap", "lighting", "studio", "device")   # the window's tabs (ui/app.js TITLES)
PRIVACY_INPUT_MONITORING = "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
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
        if u.get("tab") in TABS:
            st["ui"]["tab"] = u["tab"]
        if isinstance(u.get("liveSeen"), bool):
            st["ui"]["liveSeen"] = u["liveSeen"]
    st["studio"] = studio_mod.clean_studio(raw.get("studio"))
    st["smart"] = studio_mod.clean_smart(raw.get("smart"))
    st["experimental"] = raw.get("experimental") is True
    st["autostart_added"] = raw.get("autostart_added") is True
    return st


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        raw = None
    return _clean_state(raw)


def save_state(state):
    tmp = f"{STATE_FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
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
    with platforms.file_lock(os.path.join(os.path.dirname(STATE_FILE), "state.lock")):
        st = load_state()
        yield st
        save_state(st)


def apply_saved(kb, state=None):
    """Re-send what the keyboard keeps only in RAM: per-key colours, Rapid Trigger ON, Snap Tap ON.
    Each item on its own: a refusal is logged and the rest still goes out. Returns what was sent.
    Items the model lacks, or that Experimental support doesn't allow yet, are skipped with one log line."""
    st = state or load_state()
    steps = []
    c = st.get("custom")
    if c:
        steps.append(("per-key colours", "per_key", lambda: kb.set_custom(
            {int(k): v for k, v in c["keys"].items()}, hc.load_layout(kb.model), c["base"])))
    r = st.get("rapid") or {}
    if r.get("enabled"):
        steps.append(("Rapid Trigger", "rapid", lambda: rapid_apply(kb, r)))
    if st.get("snap"):
        steps.append(("Snap Tap", "snap_tap", lambda: kb.set_snap_tap(tuple(st["snap"]))))
    done, locked = [], []
    for name, feature, step in steps:
        if not kb.model.has(feature):
            continue   # e.g. Rapid Trigger saved for a V3 Pro, now a V2 is plugged in: nothing to send
        if not kb.allowed(feature):
            locked.append(name)
            continue
        try:
            step()
            done.append(name)
        except Exception:
            log(f"couldn't send {name} again")
    if locked:
        print(f"huntsman: not sending {', '.join(locked)} again: support for the {kb.model.name} is experimental "
              "and Experimental support is off", file=sys.stderr)
    return done


def restore_lighting(kb, state=None):
    """Put the keyboard's own lighting back after Studio streamed frames: the saved per-key colours, else the
    saved effect, else the effect stored on the keyboard (re-sent so it shows again instead of the frame buffer).
    Effects go to RAM (store 0): flash already holds them, and this runs on every Studio stop and quit."""
    if not kb.allowed("lighting"):
        return   # an experimental model with Experimental support off: nothing was changed, nothing to put back
    st = state or load_state()
    c, e = st.get("custom"), st.get("effect")
    if c:
        kb.set_custom({int(k): v for k, v in c["keys"].items()}, hc.load_layout(kb.model), c["base"])
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
    Written once, never overwritten; keys the firmware refuses are listed as skipped. Models without
    adjustable actuation (the V2 and V2 TKL) have nothing to keep."""
    if os.path.exists(SNAPSHOT_FILE) or not kb.model.has("actuation"):
        return
    snap = kb.snapshot(hc.every_key_id())
    tmp = SNAPSHOT_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SNAPSHOT_FILE)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def restore_factory(kb):
    """Every step is tried, and Rapid Trigger / Snap Tap are cleared from state.json even if the
    keyboard refuses one, so the app never re-sends them at the next login. Then any failure is raised.
    A model whose factory depth isn't known (the V2 Analog) is refused first, with nothing sent or cleared."""
    if kb.model.has("actuation"):
        kb.check_factory()
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
NOT_RUNNING_WINDOWS = ("The lighting service isn't running and couldn't be started ({}). "
                       "Start Huntsman for Mac again, or check the log in {}.")


NOT_RUNNING_INSTALLED = ("The lighting service isn't running and couldn't be started ({}). "
                         "Install Huntsman for Mac again, or check ~/Library/Logs/Huntsman for Mac.log.")


def not_running_message(detail):
    if platforms.is_windows():
        return NOT_RUNNING_WINDOWS.format(detail, platforms.log_path())
    return (NOT_RUNNING_INSTALLED if installed_bundle() else NOT_RUNNING).format(detail)


def service_socket():
    return os.path.join(hc.data_dir(), "service.sock")


def service_endpoint():
    """Where the lighting service listens: the UNIX socket service_socket() on the Mac, a named pipe on Windows."""
    return ipc.service_endpoint(hc.data_dir())


def ensure_autostart(force=False):
    """Windows: the start-at-login Run value through win_autostart.ensure(), remembering in state.json that it was
    added, so a value the user removed isn't added back (force: Studio turned on from the app). True when it was
    written. The Mac: None (its LaunchAgent is the installer's). Registry errors raise."""
    if not platforms.is_windows():
        return None
    from platforms import win_autostart
    with update_state() as st:
        st["autostart_added"], wrote = win_autostart.ensure(st["autostart_added"], force=force)
    return wrote


QUIT_WAIT = 15.0   # --quit-service: how long the service may take to restore the lighting and exit
# --quit-service exit codes. 0 stays "fine, nothing to do" (as before); 4 is also a success, and tells the Windows
# installer a service was running (it stops whichever service this user runs, maybe another copy's).
QUIT_NONE, QUIT_STOPPED, QUIT_STILL_RUNNING = 0, 4, 1


def service_stopped():
    """True when no lighting service is running: its instance lock (service.lock_path()) is free. Taken and given
    back at once; nothing is created when the data folder doesn't exist yet (no service ever ran)."""
    import service
    path = service.lock_path()
    if not os.path.isdir(os.path.dirname(path)):
        return True
    fd = service.acquire_instance_lock(path)
    if fd is None:
        return False
    try:
        platforms.unlock_fd(fd)
    except OSError:
        pass   # closing releases it anyway
    os.close(fd)
    return True


def stop_running_service(request=None, stopped=None, wait=QUIT_WAIT, clock=time.monotonic, sleep=time.sleep,
                         out=None):
    """`Huntsman.exe --quit-service` (the Windows installer runs it before an upgrade and an uninstall): ask the
    running lighting service to quit over its IPC, as the tray's "Quit lighting service" does, so it restores the
    keyboard's own lighting first; then wait until it is gone (its instance lock is free). Returns QUIT_NONE (0)
    when none was running, QUIT_STOPPED (4) when one was running and is gone now (4 also if a service that didn't
    answer went away meanwhile), QUIT_STILL_RUNNING (1) when one is still running after `wait` seconds (e.g. a 0.5
    service, which doesn't know "quit")."""
    out = out or (lambda line: print(line, flush=True))
    request = request or (lambda: ipc.Client(service_endpoint()).request("quit"))
    stopped = stopped or service_stopped
    answered = True
    try:
        reply = request()
        out("lighting service: " + ("quitting" if reply.get("ok") else f"refused: {reply.get('error')}"))
    except ipc.ServiceUnavailable:
        answered = False
        out("lighting service: not answering")
    except (ipc.ProtocolError, EOFError, OSError) as e:   # it may close the connection before the reply goes out
        out(f"lighting service: no reply ({type(e).__name__}); waiting for it to stop")
    deadline = clock() + wait
    if stopped() and not answered:
        out("lighting service: not running")
        return QUIT_NONE
    while not stopped():
        if clock() >= deadline:
            out(f"lighting service: still running after {wait:g} s")
            return QUIT_STILL_RUNNING
        sleep(0.1)
    out("lighting service: stopped")
    return QUIT_STOPPED


def remove_autostart(winreg=None):
    """`Huntsman.exe --remove-autostart` (the Windows uninstaller runs it): remove the start-at-login Run value when
    it starts this copy (win_autostart.remove_if_ours) and forget that it was added (state.json, only when it
    exists), so a later reinstall turns start at login on again like a first run. A value that starts another
    copy is left alone, with its flag. Nothing on the Mac. Returns 0."""
    if not platforms.is_windows():
        return 0
    from platforms import win_autostart
    result = win_autostart.remove_if_ours(winreg=winreg)
    print(f"start at login: {result}", flush=True)
    if result != "other" and os.path.exists(STATE_FILE):
        with update_state() as st:
            st["autostart_added"] = False
    return 0


# ---------- the installed app (packaging/mac: frozen, in /Applications from the .pkg) ----------

APP_BUNDLE_ID = "io.github.huntsman-for-mac"
APP_BUNDLE_NAME = "Huntsman for Mac.app"
PKG_ID = "io.github.huntsman-for-mac.pkg"   # the .pkg's receipt (packaging/mac/pkg)
LIGHTING_EXE = ("Contents", "Library", "LoginItems", "Huntsman Lighting.app", "Contents", "MacOS", "HuntsmanLighting")


def installed_bundle():
    """The installed app's bundle (the first "Huntsman for Mac.app" in the frozen executable's path, also from the
    nested service), or None: a source install (install.sh, not frozen), Windows, or a frozen program elsewhere."""
    if platforms.is_windows() or not getattr(sys, "frozen", False):
        return None
    parts = os.path.abspath(sys.executable).split(os.sep)
    if APP_BUNDLE_NAME not in parts:
        return None
    return os.sep.join(parts[:parts.index(APP_BUNDLE_NAME) + 1])


def agent_path():
    return os.path.expanduser(f"~/Library/LaunchAgents/{LIGHTING_LABEL}.plist")


def launch_agent(service_exe):
    """The lighting service's LaunchAgent, as install.sh writes it, plus the app it belongs to (so System
    Settings > Login Items shows it under Huntsman for Mac)."""
    log = os.path.join(os.path.expanduser("~"), "Library", "Logs", "Huntsman for Mac.log")
    return {
        "Label": LIGHTING_LABEL,
        "ProgramArguments": [service_exe],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "LimitLoadToSessionType": "Aqua",
        "ProcessType": "Interactive",
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "AssociatedBundleIdentifiers": [APP_BUNDLE_ID],
    }


def ensure_launch_agent(bundle):
    """The installed app sets up its own login item, as the Windows build does with its Run value: when the
    LaunchAgent is missing, unreadable or starts another copy (install.sh's ~/Applications app, an old path),
    write it for this bundle's service and load it (unloading the old one first). One that already starts this
    bundle's service is left exactly as it is. True when it was written."""
    path = agent_path()
    want = launch_agent(os.path.join(bundle, *LIGHTING_EXE))
    have = None
    try:
        with open(path, "rb") as f:
            have = plistlib.load(f)
    except FileNotFoundError:
        pass
    except Exception:   # unreadable: replaced below
        have = {}
    if isinstance(have, dict) and have.get("ProgramArguments") == want["ProgramArguments"]:
        return False
    domain = f"gui/{os.getuid()}"
    if have is not None:
        subprocess.run(["launchctl", "bootout", f"{domain}/{LIGHTING_LABEL}"], capture_output=True, text=True,
                       timeout=30)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        plistlib.dump(want, f)
    os.replace(tmp, path)
    subprocess.run(["launchctl", "bootstrap", domain, path], capture_output=True, text=True, timeout=10)
    return True


INSTALLED_PATH = "/Applications/" + APP_BUNDLE_NAME   # where the .pkg installs it (not relocatable)


def uninstall_script(bundle):
    """The AppleScript that removes the bundle and forgets the .pkg's receipt, as root, after macOS asks for an
    administrator's password. Settings and the log are not touched."""
    shell = (f"/bin/rm -rf {shlex.quote(bundle)} && "
             f"{{ /usr/sbin/pkgutil --forget {PKG_ID} >/dev/null 2>&1 || true; }}")
    quoted = shell.replace("\\", "\\\\").replace('"', '\\"')
    return f'do shell script "{quoted}" with administrator privileges'


def uninstall_mac(bundle, run=None):
    """Keyboard > Uninstall… (bundle must be INSTALLED_PATH): stop the lighting service (its SIGTERM handler gives
    the keyboard its own lighting back), remove the app with an administrator's password (uninstall_script), stop
    the service again (something may have started it meanwhile), then remove the LaunchAgent.
    Cancelled or failed at the password: the agent stays and the service starts again, nothing is removed.
    Settings in Application Support and the log are kept. run: subprocess.run (tests pass a fake)."""
    run = run or subprocess.run
    if bundle != INSTALLED_PATH:
        return {"ok": False, "error": f"Only the installer's copy, {INSTALLED_PATH}, can uninstall itself. "
                                      "Remove this copy by dragging it to the Trash."}
    domain = f"gui/{os.getuid()}"
    bootout = ["launchctl", "bootout", f"{domain}/{LIGHTING_LABEL}"]
    run(bootout, capture_output=True, text=True, timeout=30)
    r = run(["/usr/bin/osascript", "-e", uninstall_script(bundle)], capture_output=True, text=True, timeout=600)
    agent = agent_path()
    if r.returncode != 0:
        if os.path.exists(agent):
            run(["launchctl", "bootstrap", domain, agent], capture_output=True, text=True, timeout=10)
        why = "cancelled" if "-128" in (r.stderr or "") else f"failed: {(r.stderr or '').strip() or r.returncode}"
        return {"ok": False, "error": f"Uninstall {why}. Huntsman for Mac is still installed."}
    # a Studio call during the password prompt may have started the service again from its agent
    run(bootout, capture_output=True, text=True, timeout=30)
    try:
        os.remove(agent)
    except FileNotFoundError:
        pass
    return {"ok": True, "data": True}


def start_service():
    """Ask launchd to start the lighting service if it isn't running (never -k: killing a service that is still
    starting would interrupt a USB write); load its LaunchAgent first if it isn't loaded. The installed app
    (frozen) writes that LaunchAgent first if it is missing or stale (ensure_launch_agent); a source install
    relies on install.sh's. On Windows (no launchd):
    turn start at login on unless the user removed it (ensure_autostart) and start the service process
    (platforms/win_autostart.py). A second copy that finds the first running exits at once (the instance lock)."""
    if platforms.is_windows():
        from platforms import win_autostart
        try:
            ensure_autostart()
        except Exception as e:   # policy or a locked registry: starting now still works
            print(f"huntsman: couldn't turn on start at login: {e}", file=sys.stderr)
        win_autostart.spawn(win_autostart.service_argv())
        return
    bundle = installed_bundle()
    if bundle:   # the installed app: its login item, written here when missing or stale
        ensure_launch_agent(bundle)
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
            self._client = ipc.Client(service_endpoint())
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
                return {"ok": False, "error": not_running_message(e), "unavailable": True}
        with self._lock:   # one start at a time
            try:
                return self._request(cmd, args or {})
            except ipc.ServiceUnavailable:
                pass
            try:
                self._starter()
            except Exception as e:
                return {"ok": False, "error": not_running_message(e), "unavailable": True}
            deadline = time.monotonic() + self._wait
            while True:
                try:
                    return self._request(cmd, args or {})
                except ipc.ServiceUnavailable as e:
                    if time.monotonic() >= deadline:
                        return {"ok": False, "error": not_running_message(f"no answer: {e}"), "unavailable": True}
                    time.sleep(0.1)

    def lease(self):
        return Lease(self, self._lease_seconds, self._renew_every)

    def subscribe(self, on_event):
        return ipc.Subscription(service_endpoint(), on_event, frames=True)


class Api:
    def __init__(self, service=None):
        """service: a ServiceLink to the lighting service (tests pass one with a fake connection)."""
        self._kb = None
        self._lock = threading.RLock()
        self._test = None
        self._test_lease = None
        self._window = None
        self._progress_open = False
        self._led_check = False     # an LED check lit a cell and its lighting isn't back yet
        self.reapplied = []
        self._svc = service or ServiceLink()
        self._last_model = None     # the model last connected, shown (read only) while Razer Synapse runs
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
        reason = hc.synapse_block()
        if reason:   # Windows: let go of the keyboard, and don't open it, while Razer Synapse runs
            self._drop()
            raise hc.SynapseRunning(reason)
        if self._kb is None:
            kb = hc.Keyboard()
            self._last_model = kb.model
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
            t.stop("Live view stopped because the keyboard reconnected.")
        if self._kb is not None:
            self._last_model = self._kb.model
            if hasattr(self._kb.t, "close"):
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
            except (hc.ExperimentalLocked, hc.FeatureUnavailable) as e:   # refused before anything was sent
                return refused(e)
            except depth_stream.PermissionNeeded as e:   # Input Monitoring refused: the keyboard is fine, keep it
                return {"ok": False, "error": str(e), "reason": "permission"}
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

    def _refused(self, feature):
        """Before a write that first turns Studio off: the plain refusal if the connected model won't take it, so
        nothing changes. None when it may go ahead (or no keyboard is connected yet: the write itself checks).
        Windows: while Razer Synapse runs no handle is open, so the guard is asked here."""
        reason = hc.synapse_block()
        if reason:
            return refused(hc.SynapseRunning(reason))
        kb = self._kb
        try:
            if kb is not None:
                kb.check_write(feature)
        except (hc.ExperimentalLocked, hc.FeatureUnavailable) as e:
            return refused(e)
        return None

    # ----- reads -----
    def model(self):
        """The connected model (connecting first): name, PID, status, matrix, effects, features, whether
        Experimental support is on and whether writes are locked until it is.
        Windows, while Razer Synapse runs: nothing is sent; the last connected model from memory, marked "offline"
        and locked, or None if none was connected yet (platform_status() carries the reason)."""
        with self._lock:
            reason = hc.synapse_block()
            if reason:
                self._drop()
                m = self._last_model
                if m is None:
                    return {"ok": True, "data": None}
                from platforms import win_guard
                return {"ok": True, "data": {**hc.model_info(m), "experimental_on": hc.experimental_enabled(),
                                             "locked": True, "offline": True, "blocked": reason,
                                             "notices": win_guard.notices()}}

        def f(kb):
            d = {**hc.model_info(kb.model), "experimental_on": hc.experimental_enabled(),
                 "locked": not kb.allowed("lighting")}
            if platforms.is_windows():   # Razer Synapse running (writes refused), Dynamic Lighting on
                from platforms import win_guard
                d["blocked"], d["notices"] = win_guard.write_block_reason(), win_guard.notices()
            return d
        return self._run(f)

    def platform_status(self):
        """For the window's poll: the platform, why the keyboard is left alone (Windows: Razer Synapse runs) and
        Windows settings in the way. Asks only the guard (cached, a process list at most every few seconds): never
        touches the keyboard."""
        d = {"platform": platforms.current(), "blocked": hc.synapse_block(), "notices": [],
             "can_uninstall": installed_bundle() is not None}
        if platforms.is_windows():
            from platforms import win_guard
            d["notices"] = win_guard.notices()
        return {"ok": True, "data": d}

    def uninstall(self):
        """Keyboard > Uninstall… (the installed app only; platform_status()["can_uninstall"]): end a key test,
        then uninstall_mac; quits once everything is removed, else subscribes to the service's events again. A source install is removed with uninstall.sh."""
        bundle = installed_bundle()
        if bundle is None:
            if platforms.is_windows():
                return {"ok": False, "error": "Uninstall isn't offered in the Windows build: delete its folder."}
            return {"ok": False, "error": "This copy was installed from source: run ./uninstall.sh in its folder."}
        self.shutdown()
        r = uninstall_mac(bundle)
        if r["ok"]:
            self._quit_soon()
        else:   # still installed: the window keeps working, with the service's events
            self.start_events()
        return r

    def _quit_soon(self):
        """Close the window a moment after answering, so the page can say it's done; main() then exits."""
        def work():
            time.sleep(1.5)
            win = self._window
            if win is not None:
                win.destroy()
        in_background(work)

    def layout(self):
        """Keys of the connected model (the window asks for model() first, which connects)."""
        return hc.load_layout()

    def effects(self):
        return {n: {"speed": s, "colors": t.count("{rgb"), "dir": "{dir}" in t} for n, (t, s) in hc.EFFECTS.items()
                if n in hc.active_model().effects}

    def experimental(self):
        return {"ok": True, "data": hc.experimental_enabled()}

    def set_experimental(self, on):
        """Keyboard -> Experimental support. Turning it off first stops Studio (restoring the keyboard's own
        lighting while writes are still allowed) and ends an LED check."""
        if not isinstance(on, bool):
            return {"ok": False, "error": "on must be true or false"}
        with self._lock:
            if not on and hc.experimental_enabled():
                if self._led_check:
                    self.end_led_check()
                studio_off_before_lock(self._svc)
            hc.set_experimental(on)
        return {"ok": True, "data": on}

    def reconnect(self):
        with self._lock, self._paused():
            self._drop()
        return self._run(lambda kb: self.reapplied)

    def info(self):
        def f(kb):
            return {"version": hc.__version__, "model": hc.model_info(kb.model), "firmware": kb.firmware(), "profile": kb.saved,
                    "brightness": kb.brightness(), "effect": kb.get_effect_raw().hex(),
                    "state": load_state()}
        return self._run(f)

    def startup(self):
        """Re-apply RAM-only settings once when the app opens."""
        return self._run(lambda kb: self.reapplied)

    def read_depths(self):
        def f(kb):
            if not kb.model.has("actuation"):
                return {}   # the V2 and V2 TKL: no adjustable depth to read
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
                    if reason and self._test is session[0]:   # a newer session's window state isn't this one's
                        # "cmd": ⌘ on the Huntsman ended it; the window holds live view off as for the idle pause
                        self._pusher.push("onTestEnded", reason, ok, "cmd" if reason == depth_stream.LEAVE else "")
                in_background(follow_up)

            session = [None]
            self._test = session[0] = depth_stream.DepthSession(kb, batch, ended)
            try:
                started = self._test.start()
            except depth_stream.StillInDriverMode:
                release(stuck=True)   # not typing: left to expire, so the service switches it back before frames
                raise
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
            return {"ok": False, "error": "The keyboard may still be in live view and not typing. Unplug it and plug it back in."}
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
        no = self._refused("lighting")
        if no:
            return no
        self._studio_off_for_firmware()
        return self._run(lambda kb: set_effect(kb, name, opts))

    def set_custom(self, base, keys):
        try:
            base, colours = check_colours(base, keys)
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": str(e)}
        no = self._refused("per_key")
        if no:
            return no

        self._studio_off_for_firmware()

        def f(kb):
            kb.set_custom(colours, hc.load_layout(), base)
            with update_state() as st:
                st["custom"] = {"base": base, "keys": {str(k): v for k, v in colours.items()}}
            return True
        return self._run(f)

    def set_prefs(self, prefs):
        """Interface preferences (accent colour, the last tab, the live view's explanation seen), saved together.
        Not sent to the keyboard."""
        if not isinstance(prefs, dict):
            return {"ok": False, "error": "prefs must be an object"}
        prefs = {k: v for k, v in prefs.items() if k in ("accent", "accentMatch", "tab", "liveSeen")}
        if "accent" in prefs and not (isinstance(prefs["accent"], str) and ACCENT.match(prefs["accent"])):
            return {"ok": False, "error": "accent must be a colour like #3ddc84"}
        for k in ("accentMatch", "liveSeen"):
            if k in prefs and not isinstance(prefs[k], bool):
                return {"ok": False, "error": f"{k} must be true or false"}
        if "tab" in prefs and prefs["tab"] not in TABS:
            return {"ok": False, "error": "tab must be one of " + ", ".join(TABS)}
        with self._lock, update_state() as st:
            st["ui"].update(prefs)
        return {"ok": True, "data": True}

    def open_privacy(self):
        """System Settings at Privacy & Security, Input Monitoring (the live key tester needs it). macOS only."""
        if platforms.is_windows():
            return {"ok": False, "error": "Input Monitoring is a macOS setting.", "reason": "unavailable"}
        subprocess.run(["open", PRIVACY_INPUT_MONITORING], capture_output=True, timeout=10)
        return {"ok": True, "data": True}

    def set_brightness(self, pct):
        """While the slider drags: live only, so flash isn't rewritten on every step."""
        return self._run(lambda kb: kb.set_brightness(pct, stores=(0,)))

    def save_brightness(self, pct):
        """When the slider is released: saved on the keyboard so it survives a replug."""
        return self._run(lambda kb: kb.set_brightness(pct, stores=(1,)))

    def restore_original(self):
        return self._run(restore_factory)

    # ----- LED check (Keyboard tab, experimental models): which key is at matrix cell (row, column)? -----
    def led_check(self, row, col):
        """Light only cell (row, col); Studio stops first, since its frames would hide the cell."""
        if not (_is_int(row) and _is_int(col)):
            return {"ok": False, "error": "row and column must be whole numbers"}
        no = self._refused("per_key")
        if no:
            return no
        self._studio_off_for_firmware()

        def f(kb):
            cell = kb.light_cell(row, col)
            self._led_check = True
            return cell
        return self._run(f)

    def end_led_check(self):
        """Put back the lighting the keyboard showed before the check."""
        def f(kb):
            restore_lighting(kb)
            self._led_check = False
            return True
        return self._run(f)

    # ----- Lighting Studio: proxied to the lighting service (started if needed); each returns {"ok", ...} -----
    def studio_state(self):
        return self._studio("studio_state")

    def studio_enable(self, on):
        """Turning Studio on from the window also brings start at login back on Windows, if the user removed it
        (only once the service has taken the switch: a refused one changes nothing)."""
        r = self._studio("studio_enable", on=on)
        if on is True and r.get("ok") and platforms.is_windows():
            try:
                ensure_autostart(force=True)
            except Exception as e:
                print(f"huntsman: couldn't turn on start at login: {e}", file=sys.stderr)
        return r

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

    def studio_preview(self, seconds):
        """Studio off: the window's board previews the working preset for `seconds` (nothing reaches the keys).
        The Studio tab polls this every few seconds, so it never starts the service: after "Quit lighting service"
        (or the Windows installer's --quit-service) an open window must not bring it back."""
        r = self._svc.call("studio_preview", {"seconds": seconds}, start=False)
        return {k: v for k, v in r.items() if k != "unavailable"}

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
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            return {"ok": True, "data": {"path": path}}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}


def studio_off_before_lock(svc):
    """Before Experimental support goes off (the window and huntsman.py): stop Studio through the lighting service,
    which puts the keyboard's own lighting back while writes are still allowed. A service that isn't running has
    nothing streaming and isn't started for this."""
    r = svc.call("studio_enable", {"on": False})
    if not r["ok"] and not r.get("unavailable"):
        print(f"huntsman: couldn't turn Studio off: {r['error']}", file=sys.stderr)


def refused(e):
    """A write the connected model doesn't take, for the window: the plain message, and why (so it isn't shown as
    a lost connection): "experimental" (turn on Experimental support), "synapse" (Windows: quit Razer Synapse) or
    "unavailable" (the model lacks it)."""
    if isinstance(e, hc.SynapseRunning):
        reason = "synapse"
    else:
        reason = "experimental" if isinstance(e, hc.ExperimentalLocked) else "unavailable"
    return {"ok": False, "error": str(e), "reason": reason}


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


def _dlopen(path):
    import ctypes
    return ctypes.CDLL(path)


def _native_checks(out):
    """The Mac: load libusb, IOKit and CoreFoundation and look up one symbol in each, without calling anything
    (no libusb_init, no USB traffic). libusb from a source install without Homebrew's is only skipped; the
    installed app must have its own. Returns the number of failures."""
    import ctypes.util
    failed = 0
    usb = hc.libusb_path()
    if usb is None and not getattr(sys, "frozen", False):
        out("skip libusb (not installed: brew install libusb)")
        checks = []
    else:
        checks = [("libusb", usb, "libusb_get_version")]
    checks += [("IOKit", ctypes.util.find_library("IOKit"), "IOHIDManagerCreate"),
               ("CoreFoundation", ctypes.util.find_library("CoreFoundation"), "CFRunLoopGetCurrent")]
    for label, path, sym in checks:
        try:
            if not path:
                raise FileNotFoundError("not found")
            getattr(_dlopen(path), sym)
            out(f"ok   {label} {path}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            out(f"FAIL {label} ({path}): {type(e).__name__}: {e}")
    return failed


def self_test(out=None):
    """`--self-test`: a build's smoke test. Imports every module the build must contain (platforms/bundle.py),
    reads the data files and every model's layout and, on the Mac, loads the native libraries (_native_checks),
    without opening the keyboard or a window. Windows-only modules are skipped elsewhere, Mac-only ones aren't
    tried off a Mac. Returns 0 when everything is there, 1 otherwise."""
    import importlib
    from platforms import bundle
    out = out or (lambda line: print(line, flush=True))
    failed = 0
    mac_host = sys.platform == "darwin"   # the real host: the Mac-only modules can't load anywhere else
    for name in bundle.HIDDEN_IMPORTS + (bundle.MAC_ONLY if mac_host else []):
        if name in bundle.WINDOWS_ONLY and not platforms.is_windows():
            out(f"skip {name} (Windows only)")
            continue
        try:
            importlib.import_module(name)
            out(f"ok   {name}")
        except Exception as e:  # noqa: BLE001  (report every failure, then exit 1)
            failed += 1
            out(f"FAIL {name}: {type(e).__name__}: {e}")
    for rel in bundle.REQUIRED_FILES:
        path = os.path.join(HERE, *rel.split("/"))
        try:
            with open(path, "rb") as f:
                data = f.read()
            if rel.endswith(".json"):
                json.loads(data)
            out(f"ok   {rel}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            out(f"FAIL {rel}: {type(e).__name__}: {e}")
    for m in hc.models.MODELS.values():
        try:
            assert hc.load_layout(m), "empty layout"
            out(f"ok   layout {m.pid:04X}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            out(f"FAIL layout {m.pid:04X} ({m.layout}): {type(e).__name__}: {e}")
    if mac_host:
        failed += _native_checks(out)
    out(f"Huntsman for Mac {hc.__version__} self-test {'passed' if not failed else 'FAILED'}"
        f" ({platforms.current()}, frozen={bool(getattr(sys, 'frozen', False))})")
    return 1 if failed else 0


def entry(argv=None):
    """The program's entry point. The packaged Windows build is one Huntsman.exe: with --service it runs the
    lighting service (its start-at-login command), without it the window. --version and --self-test (the build's
    smoke test, app.self_test) print to stdout, or to the log file in the windowed build. --quit-service and
    --remove-autostart are for the Windows installer (packaging/windows/huntsman.iss)."""
    argv = sys.argv if argv is None else argv
    platforms.redirect_output()
    if "--version" in argv[1:]:
        print(f"Huntsman for Mac {hc.__version__}", flush=True)
        return 0
    if "--self-test" in argv[1:]:
        return self_test()
    if "--quit-service" in argv[1:]:
        return stop_running_service()
    if "--remove-autostart" in argv[1:]:
        return remove_autostart()
    if "--service" in argv[1:]:
        import service
        return service.main()
    return main()


if __name__ == "__main__":
    sys.exit(entry())
