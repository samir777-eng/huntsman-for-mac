# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Huntsman Lighting: the background lighting service.

Runs as a menu bar accessory (no Dock icon) from "Huntsman for Mac.app/Contents/Library/LoginItems/Huntsman
Lighting.app", started at login by the LaunchAgent io.github.huntsman-for-mac.lighting and kept alive after the
app's window quits, so Studio effects keep running (like Razer Synapse's service). It owns:

- the Studio controller (studio.py): lighting engine, typing and sound listeners, smart lighting;
- the menu bar icon: Lighting on/off, presets, Open Huntsman for Mac, Quit lighting service;
- a UNIX socket at data_dir()/service.sock (ipc.py; a named pipe on Windows) for the app: the Studio commands in SPECS, an event stream,
  and pause leases. The app takes a lease around every keyboard operation; a lease ends on resume or when it
  isn't renewed in time (a crashed app), and on expiry the service first switches a keyboard left in driver
  mode (key tester) back to typing, then resumes the engine.

One instance per user (a lock on data_dir()/service.lock: flock, or msvcrt.locking on Windows). At start it re-sends what the keyboard keeps only in
RAM (per-key colours, Rapid Trigger, Snap Tap: the old apply-saved login item's job) and turns Studio back on if
it was on. Quitting (menu, logout, SIGTERM) stops the engine and restores the keyboard's own lighting to RAM.

Windows (experimental, untested on a Windows PC): the same service runs as `Huntsman.exe --service` (or
service.py from source), started at login by the HKCU Run value (platforms/win_autostart.py) and by the app when
it isn't answering; a pystray tray icon (platforms/win_tray.py) shows the same menu; logoff/shutdown arrive as
WM_ENDSESSION on a hidden window. Quitting leaves start at login on, so, as on the Mac, it stays off until the next
login or until the app's window opens (it asks the service for Studio's state, starting it). While Razer Synapse runs the keyboard isn't opened at all (platforms/win_guard.py):
Studio stays off, the tray says why, and check_guard() (every few seconds) turns Studio back on once Synapse quits if it
was on before.
"""
import os
import secrets
import subprocess
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import app as appmod  # noqa: E402  (shared state.json and keyboard helpers; no window code at import)
import depth_stream  # noqa: E402
import huntsman_core as hc  # noqa: E402
import ipc  # noqa: E402
import platforms  # noqa: E402
import studio as studio_mod  # noqa: E402

LABEL = "io.github.huntsman-for-mac.lighting"
APP_BUNDLE_ID = "io.github.huntsman-for-mac"
LEASE_MIN, LEASE_MAX = 0.5, 30.0
MAX_LEASES = 16
REAP_EVERY = 0.25
QUIT_TITLE = "Quit lighting service"
# What "Quit lighting service" does, on both platforms: start at login is left as it is (the Mac's LaunchAgent stays
# loaded and exit 0 keeps launchd from restarting it; the Windows Run value stays), so the service is back at the
# next login or when the app needs it.
QUIT_STEPS = ("stop the server", "stop Studio and restore the keyboard's lighting", "exit")
GUARD_EVERY = 5.0

SPECS = {
    "ping": {}, "summary": {}, "studio_state": {}, "reset_heat": {}, "running_apps": {},
    "studio_enable": {"on": ("bool",), "restore": ("bool", None)},
    "set_active_preset": {"name": ("str",)},
    "save_preset": {"preset": ("dict",)},
    "delete_preset": {"name": ("str",)},
    "rename_preset": {"old": ("str",), "new": ("str",)},
    "duplicate_preset": {"name": ("str",), "new": ("str", "none", None)},
    "import_preset": {"text": ("str",)},
    "export_preset": {"name": ("str",)},
    "update_layers": {"layers": ("list",)},
    "set_studio_brightness": {"level": ("num",)},
    "set_fps": {"fps": ("num",)},
    "set_audio_device": {"device": ("int", "none")},
    "set_audio_sensitivity": {"value": ("num",)},
    "set_heat": {"on": ("bool",)},
    "set_smart": {"config": ("dict",)},
    "pause": {"lease_seconds": ("num",), "token": ("str", None)},
    "resume": {"token": ("str",)},
}


def socket_path():
    return os.path.join(hc.data_dir(), "service.sock")


def service_endpoint():
    """The UNIX socket socket_path() on the Mac; on Windows a named pipe with an authkey file (ipc.PipeEndpoint)."""
    return ipc.service_endpoint(hc.data_dir())


def lock_path():
    return os.path.join(hc.data_dir(), "service.lock")


def acquire_instance_lock(path):
    """An fd holding the exclusive lock on path, or None if another service holds it."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    if not platforms.try_lock_fd(fd):
        os.close(fd)
        return None
    return fd


def list_running_apps():
    """Open apps with a Dock icon, for per-app rules: [{"name", "bundle_id"}]. On Windows: programs with a window,
    by program name."""
    if platforms.is_windows():
        from platforms import win_smart
        return win_smart.list_running_apps()
    from AppKit import NSWorkspace
    apps = NSWorkspace.sharedWorkspace().runningApplications()
    out = sorted({(str(a.localizedName() or a.bundleIdentifier()), str(a.bundleIdentifier()))
                  for a in apps if a.activationPolicy() == 0 and a.bundleIdentifier()})
    return [{"name": n, "bundle_id": b} for n, b in out]


def log(msg):
    print(f"huntsman-lighting: {msg}", file=sys.stderr, flush=True)


class LightingService:
    def __init__(self, engine_cls=None, inputs=None, clock=time.monotonic):
        """engine_cls, inputs (Studio's listener hooks) and clock are for tests."""
        self._engine_cls, self._inputs, self._clock = engine_cls, dict(inputs or {}), clock
        self.studio = None
        self._kb = None
        self._engine_broken = False
        self._dev = threading.RLock()            # the service's own keyboard use (connect, restore, recover)
        self._lease_lock = threading.Lock()
        self._leases = {}                        # token -> expiry (clock time)
        self._restore_due = False
        self._quitting = self._shut = False
        self._subs, self._subs_lock = {}, threading.Lock()
        self.reapplied, self.restored = [], []
        self._keymap_pid = None                  # model whose layout Studio and the engine use
        self._guard_reason = None                # Windows: why writes are refused (Razer Synapse), as last told
        self._guard_wants_on = False             # Studio was on (or meant to be) when Synapse took the keyboard
        self._guard_listeners = []

    # ---------- start and stop ----------

    def start(self):
        from lighting.engine import Engine
        from lighting.frame import Keymap
        try:
            with self._dev:
                self._keyboard()   # detects the model (layout, frame size, key listener PID); re-sends RAM settings
        except Exception:
            log("keyboard not reachable at start; will connect when needed")
            traceback.print_exc()
        km = Keymap.load()
        self._keymap_pid = hc.active_model().pid
        st = appmod.load_state()
        engine = (self._engine_cls or Engine)(self._engine_keyboard, km, fps=st["studio"]["fps"],
                                              restore=self._restore_lighting, on_error=self._engine_error,
                                              heat_enabled=st["studio"]["heat"])
        engine.on_frame(lambda f: self._emit("onStudioFrame", {str(k): list(v) for k, v in f.items()}))
        s = studio_mod.Studio(engine, st["studio"], st["smart"], save=self._save_studio, keymap=km,
                              push=self._emit, **self._inputs)
        s.on_change(lambda summary: self._emit("onStudioChanged", summary))
        self.studio = s
        if s.settings["enabled"]:
            reason = self.studio_blocked()
            if reason:
                s.settings["enabled"] = False   # shown off; state.json keeps the choice until it's changed
                log(f"Studio stays off: {reason}")
                self._guard_wants_on = platforms.is_windows() and self._synapse_blocks()
            else:
                s.set_enabled(True)

    def gui_ready(self):
        self.studio.gui_ready()

    def shutdown(self):
        """Stop the engine and listeners and restore the keyboard's lighting (even under a lease: the service is
        going away). Studio's on/off setting is kept for the next start. Safe to call twice."""
        if self._shut or self.studio is None:
            return
        self._shut = self._quitting = True
        try:
            self.studio.shutdown()
        except Exception:
            traceback.print_exc()
        with self._lease_lock:
            self._leases.clear()

    def run_reaper(self):
        def loop():
            while not self._shut:
                try:
                    self.expire_leases()
                except Exception:
                    traceback.print_exc()
                time.sleep(REAP_EVERY)
        threading.Thread(target=loop, name="huntsman-leases", daemon=True).start()

    # ---------- keyboard ----------

    def _keyboard(self):
        reason = hc.synapse_block()
        if reason:   # Windows: let go of the keyboard, and don't open it, while Razer Synapse runs
            self._drop()
            raise hc.SynapseRunning(reason)
        if self._kb is None:
            kb = hc.Keyboard()
            depth_stream.recover_typing(kb)
            self.reapplied = appmod.apply_saved(kb)
            self._kb = kb
            self._follow_model(kb.model)
        return self._kb

    def _follow_model(self, model):
        """A keyboard first reached after start (or a different model plugged in): Studio and the engine switch to
        its layout, and the key listener to its product id. The engine thread holds its send lock here or is
        paused, so no frame is being built."""
        if self.studio is None or model.pid == self._keymap_pid:
            return
        from lighting.frame import Keymap
        km = Keymap(hc.load_layout(model))
        self._keymap_pid = model.pid
        self.studio.engine.keymap = self.studio.keymap = km
        # the key listener matches one product id; restart it off this thread (it may be the engine's, holding
        # the send lock, and the restart takes Studio's lock)
        self.studio._spawn(self.studio.restart_key_listener)
        log(f"{model.name} connected; using its layout")

    def studio_blocked(self):
        """Why Studio can't stream to the connected keyboard (an experimental model with Experimental support off),
        else None. No keyboard yet: None, and the engine connects when it can. While the engine streams, the
        keyboard is the engine's (and already took the frames): None. Windows: Razer Synapse running, asked first."""
        reason = hc.synapse_block()
        if reason:   # Windows: Razer Synapse runs, so the keyboard isn't even opened to ask
            return reason
        if self.studio is not None and self.studio.engine.running:
            return None
        try:
            with self._dev:
                kb = self._keyboard()
        except Exception:
            return None
        for feature in ("per_key", "studio"):
            try:
                kb.check_write(feature)
            except (hc.ExperimentalLocked, hc.FeatureUnavailable) as e:
                return str(e)
        return None

    def set_studio_enabled(self, on, restore=True):
        """Studio on or off, for the window and the menu. Refused with the plain reason while blocked."""
        if on:
            reason = self.studio_blocked()
            if reason:
                raise ValueError(reason)
        self._guard_wants_on = False   # the user's own choice from now on
        self.studio.set_enabled(on, restore=restore)

    # ---------- Windows: Razer Synapse ----------

    def _synapse_blocks(self):
        from platforms import win_guard
        return win_guard.write_block_reason() is not None

    def on_guard(self, fn):
        """fn(reason or None) whenever the reason writes are refused changes (the tray's notice)."""
        self._guard_listeners.append(fn)

    def check_guard(self):
        """Windows: re-check Razer Synapse; tell the listeners when that changed, and once Synapse is gone turn
        Studio back on if Synapse was what turned it off. Returns the current reason (None on the Mac)."""
        if not platforms.is_windows():
            return None
        from platforms import win_guard
        reason = win_guard.write_block_reason()
        if reason == self._guard_reason:
            return reason
        self._guard_reason = reason
        if reason:
            log(f"keyboard left alone: {reason}")
        else:
            log("Razer Synapse quit; writes allowed again")
        for fn in list(self._guard_listeners):
            try:
                fn(reason)
            except Exception:
                traceback.print_exc()
        if reason is None and self._guard_wants_on and self.studio is not None:
            try:
                self.set_studio_enabled(True)
            except ValueError as e:   # e.g. Experimental support went off meanwhile
                log(f"Studio stays off: {e}")
        return reason

    def run_guard(self, every=GUARD_EVERY):
        def loop():
            while not self._shut:
                try:
                    self.check_guard()
                except Exception:
                    traceback.print_exc()
                time.sleep(every)
        threading.Thread(target=loop, name="huntsman-guard", daemon=True).start()

    def _drop(self):
        if self._kb is not None and hasattr(self._kb.t, "close"):
            try:
                self._kb.t.close()
            except Exception:
                pass
        self._kb = None

    def _engine_keyboard(self):
        """Called by the engine thread holding its send lock; every other use of self._kb runs with the engine
        paused or stopped, so the two never overlap."""
        if self._engine_broken:
            self._engine_broken = False
            self._drop()
        return self._keyboard()

    def _engine_error(self, e):
        if isinstance(e, (hc.ExperimentalLocked, hc.FeatureUnavailable)):
            # The keyboard refused frames (e.g. Experimental support was turned off from the command line): not a
            # lost connection, so no reconnect loop. Studio goes off, from another thread (this is the engine's).
            log(f"Studio off: {e}")
            if isinstance(e, hc.SynapseRunning):   # back on once Synapse quits (check_guard)
                self._guard_wants_on, self._guard_reason = True, str(e)
            self._emit("onStudioStatus", {"engine": str(e)})
            self.studio._spawn(self._studio_off_refused)
            return
        if isinstance(e, (hc.DeviceError, OSError)):
            self._engine_broken = True
        self._emit("onStudioStatus", {"engine": str(e)})

    def _studio_off_refused(self):
        try:
            self.studio.set_enabled(False)   # not set_studio_enabled: the Synapse flag stays
        except Exception:
            traceback.print_exc()

    def _restore_lighting(self):
        """The engine's restore callback. While the app holds a lease (it is changing the keyboard) the restore
        waits until the last lease ends; quitting restores at once."""
        with self._lease_lock:
            if self._leases and not self._quitting:
                self._restore_due = True
                return
            self._restore_due = False
        self._do_restore()

    def _do_restore(self):
        if hc.synapse_block():   # Windows: Razer Synapse owns the lights; nothing to put back, nothing is sent
            return
        with self._dev, self.studio.engine.paused():
            try:
                appmod.restore_lighting(self._keyboard())
            except Exception:
                self._drop()
                raise
            self.restored.append(self._clock())

    def _recover_typing(self):
        """A lease expired: the app may have crashed during a key test and left the keyboard in driver mode."""
        try:
            with self._dev:
                depth_stream.recover_typing(self._keyboard())
        except Exception:
            self._drop()
            traceback.print_exc()

    # ---------- leases ----------

    def pause(self, lease_seconds, token=None):
        if not LEASE_MIN <= lease_seconds <= LEASE_MAX:
            raise ValueError(f"lease_seconds must be {LEASE_MIN}-{LEASE_MAX}")
        with self._lease_lock:
            expires = self._clock() + lease_seconds
            if token is not None:
                if token not in self._leases:
                    raise ValueError("that pause lease has ended")
                self._leases[token] = expires
                return {"token": token, "expires_in": lease_seconds}
            if self._shut:
                raise ValueError("the lighting service is quitting")
            if len(self._leases) >= MAX_LEASES:
                raise ValueError("too many pause leases")
            token = secrets.token_hex(16)
            self._leases[token] = expires
        self.studio.engine.pause()
        return {"token": token, "expires_in": lease_seconds}

    def resume(self, token):
        with self._lease_lock:
            if self._leases.pop(token, None) is None:
                raise ValueError("that pause lease has ended")
        self._lease_ended()

    def expire_leases(self):
        now = self._clock()
        with self._lease_lock:
            gone = [t for t, exp in self._leases.items() if exp <= now]
            for t in gone:
                del self._leases[t]
        if gone:
            log(f"{len(gone)} pause lease(s) expired; switching the keyboard back to typing if needed")
            self._recover_typing()   # the engine is still paused here
            for _ in gone:
                self._lease_ended()

    def _lease_ended(self):
        self.studio.engine.resume()
        with self._lease_lock:
            due = self._restore_due and not self._leases
            if due:
                self._restore_due = False
        if due and not self.studio.engine.running:
            try:
                self._do_restore()
            except Exception:
                traceback.print_exc()

    # ---------- commands ----------

    def handle(self, cmd, args):
        spec = SPECS.get(cmd)
        if spec is None:
            return {"ok": False, "error": f"unknown command {cmd!r}"}
        try:
            a = ipc.check_args(spec, args)
            return {"ok": True, "data": self._commands()[cmd](**a)}
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e) or type(e).__name__}

    def _commands(self):
        s = self.studio
        return {
            "ping": lambda: True,
            "summary": s.summary,
            "studio_state": s.state,
            "studio_enable": self.set_studio_enabled,
            "set_active_preset": s.set_active,
            "save_preset": lambda preset: s.save_preset(preset),
            "delete_preset": s.delete_preset,
            "rename_preset": s.rename_preset,
            "duplicate_preset": lambda name, new=None: s.duplicate_preset(name, new),
            "import_preset": s.import_preset,
            "export_preset": s.export_preset,
            "update_layers": s.update_layers,
            "set_studio_brightness": s.set_brightness,
            "set_fps": s.set_fps,
            "set_audio_device": s.set_audio_device,
            "set_audio_sensitivity": s.set_audio_sensitivity,
            "set_heat": s.set_heat,
            "reset_heat": s.reset_heat,
            "set_smart": s.set_smart,
            "running_apps": list_running_apps,
            "pause": self.pause,
            "resume": self.resume,
        }

    def _save_studio(self, settings, smart):
        with appmod.update_state() as st:
            st["studio"], st["smart"] = settings, smart

    # ---------- events ----------

    def subscribe(self, send, frames=False):
        key = object()
        with self._subs_lock:
            self._subs[key] = (send, bool(frames))

        def unsubscribe():
            with self._subs_lock:
                self._subs.pop(key, None)
        return unsubscribe

    def _emit(self, name, *args):
        with self._subs_lock:
            subs = list(self._subs.values())
        for send, frames in subs:
            if name in ("onStudioFrame", "onStudioLevel") and not frames:
                continue
            try:
                send(name, list(args))
            except Exception:
                traceback.print_exc()


def _in_background(fn):
    def run():
        try:
            fn()
        except Exception:
            traceback.print_exc()
    threading.Thread(target=run, daemon=True).start()


def make_menu(svc, menu_cls, on_open, on_quit, run=_in_background, **menu_kw):
    """The menu bar icon, wired to the service's Studio. Handlers run on the main thread, so device work goes
    to `run` (a background thread)."""
    s = svc.studio

    def enable(on):
        try:
            svc.set_studio_enabled(on)
        except ValueError as e:   # an experimental model with Experimental support off
            log(f"Studio stays off: {e}")

    def pick(name):
        def work():
            s.set_active(name)
            if not s.settings["enabled"]:
                enable(True)
        run(work)
    summary = s.summary()
    menu = menu_cls(lambda on: run(lambda: enable(on)), pick, on_open, on_quit,
                    presets=summary["presets"], enabled=summary["enabled"], active=summary["active"], **menu_kw)
    s.on_change(lambda m: menu.set_state(enabled=m["enabled"], presets=m["presets"], active=m["active"]))
    return menu


def ensure_autostart():
    """Windows: turn start at login on (first run, and the value follows a moved Huntsman.exe), but not back on
    after the user removed it (app.ensure_autostart). Never raises."""
    if not platforms.is_windows():
        return
    try:
        if appmod.ensure_autostart():
            log("start at login turned on")
    except Exception as e:
        log(f"couldn't turn on start at login: {e}")


def open_app():
    """Open the window app: the bundle this service sits in, else by bundle id. Windows: Huntsman.exe (or app.py)
    without a console window."""
    if platforms.is_windows():
        from platforms import win_autostart
        try:
            win_autostart.spawn(win_autostart.app_argv(), popen=subprocess.Popen)
        except OSError:
            traceback.print_exc()
        return
    outer = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
    cmd = ["/usr/bin/open", outer] if outer.endswith(".app") else ["/usr/bin/open", "-b", APP_BUNDLE_ID]
    try:
        subprocess.Popen(cmd)
    except OSError:
        traceback.print_exc()


_KEEP = {}   # the app delegate must stay alive while the run loop uses it


def main(argv=None):
    os.makedirs(hc.data_dir(), exist_ok=True)
    fd = acquire_instance_lock(lock_path())
    if fd is None:
        log("already running")
        return 0
    _KEEP["lock"] = fd
    if platforms.is_windows():
        return _main_windows()

    from AppKit import NSApplication
    from Foundation import NSObject
    from PyObjCTools import AppHelper

    from menubar import StatusMenu

    nsapp = NSApplication.sharedApplication()
    nsapp.setActivationPolicy_(1)   # accessory: menu bar icon, no Dock icon, no app menu
    svc = LightingService()
    server = ipc.Server(service_endpoint(), svc.handle, svc.subscribe)
    stopped = threading.Lock()
    finished = threading.Event()

    def stop():
        # A second caller (e.g. launchd's SIGTERM arriving during the logout quit) must wait for the first
        # one's lighting restore instead of returning straight into os._exit.
        if not stopped.acquire(blocking=False):
            finished.wait(depth_stream.SHUTDOWN_LIMIT if hasattr(depth_stream, "SHUTDOWN_LIMIT") else 3.0)
            return
        try:
            server.close()
            svc.shutdown()
        finally:
            finished.set()

    class Delegate(NSObject):
        def applicationShouldTerminate_(self, sender):   # logout, restart, shut down
            try:
                stop()
            except Exception:
                traceback.print_exc()
            return 1   # NSTerminateNow
    _KEEP["delegate"] = Delegate.alloc().init()
    nsapp.setDelegate_(_KEEP["delegate"])

    depth_stream.add_shutdown_hook(stop)
    depth_stream.install_signal_stop()   # SIGTERM / SIGHUP: stop, restore, exit non-zero

    def quit_service():
        def work():
            stop()
            AppHelper.callAfter(lambda: nsapp.terminate_(None))   # exits 0: launchd leaves it quit
        _in_background(work)

    server.start()   # answer the app's requests while starting, so it never thinks the service is down
    svc.start()
    svc.run_reaper()
    menu = make_menu(svc, StatusMenu, on_open=open_app, on_quit=quit_service, quit_title=QUIT_TITLE)

    def ready():
        menu.install()
        svc.gui_ready()
    AppHelper.callAfter(ready)
    log("started")
    AppHelper.runEventLoop(installInterrupt=False)
    stop()
    return 0


WM_QUERYENDSESSION, WM_ENDSESSION = 0x0011, 0x0016


def _main_windows():
    """The service on Windows: tray icon on the main thread, a hidden window for logoff/shutdown, the Synapse
    re-check, start at login turned on. Same LightingService and IPC as on the Mac."""
    platforms.redirect_output()
    from platforms.win_tray import TrayMenu
    from platforms.win_window import MessageWindow

    svc = LightingService()
    server = ipc.Server(service_endpoint(), svc.handle, svc.subscribe)
    stopped = threading.Lock()
    finished = threading.Event()
    holder = {}

    def stop():
        if not stopped.acquire(blocking=False):
            finished.wait(depth_stream.SHUTDOWN_LIMIT)
            return
        try:
            server.close()
            svc.shutdown()
        finally:
            finished.set()

    def end_session(_hwnd, wparam, _lparam):
        if wparam:   # the session really ends: restore the lighting before Windows ends the process
            try:
                stop()
            except Exception:
                traceback.print_exc()
        return 0

    session = MessageWindow("session", {WM_QUERYENDSESSION: lambda h, w, l: 1, WM_ENDSESSION: end_session},
                            message_only=False)
    depth_stream.add_shutdown_hook(stop)
    depth_stream.install_signal_stop()

    def quit_service():
        def work():
            stop()
            menu = holder.get("menu")
            if menu is not None:
                menu.remove()   # ends the tray loop: main() returns 0; start at login stays on
        _in_background(work)

    server.start()
    ensure_autostart()
    svc.start()
    svc.run_reaper()
    try:
        session.start()
    except OSError as e:
        log(f"no logoff/shutdown notice: {e}")
    menu = make_menu(svc, TrayMenu, on_open=open_app, on_quit=quit_service, quit_title=QUIT_TITLE)
    holder["menu"] = menu
    svc.on_guard(lambda reason: menu.set_state(notice="Paused: Razer Synapse is running" if reason else None))
    svc.run_guard()
    log("started")

    def ready():
        svc.gui_ready()
    menu.run(on_ready=ready)   # blocks until the tray is removed
    stop()
    session.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
