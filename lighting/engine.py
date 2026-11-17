# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The lighting engine: renders the active preset at a target fps and streams per-key frames.

- Frames go out only when they change; the first frame after start/resume/reconnect switches the
  keyboard to its custom (per-key) effect.
- Gamma correction happens here, once, at the sink (picker sRGB -> LED drive level, as hc.gamma).
- Every other device operation runs inside `with engine.paused():`, which waits for the frame in flight.
- Keyboard errors are reported through on_error and retried with exponential back-off, never in a loop.
- stop(restore=True) calls the injected restore callback (e.g. re-apply the saved firmware effect).
"""
import contextlib
import threading
import time

import huntsman_core as hc
from lighting.effects import RenderContext
from lighting.frame import KeyEvent
from lighting.layers import compose
from lighting.presets import Preset

PREVIEW_FPS = 15
MIN_FPS, MAX_FPS = 1, 120
MAX_PENDING_EVENTS = 512


class Engine:
    def __init__(self, keyboard_factory, keymap, fps=30, *, restore=None, on_error=None,
                 clock=time.monotonic, backoff=(0.5, 8.0), heat_enabled=False):
        """keyboard_factory() -> object with send_frame_fast(rows) and enter_custom_mode() (a hc.Keyboard);
        called lazily, and again after an error. restore() runs on stop(restore=True).
        on_error(exc) gets every keyboard, render or callback error. clock must match KeyEvent.t."""
        self._factory, self.keymap = keyboard_factory, keymap
        self._restore, self._on_error, self._clock = restore, on_error, clock
        self._backoff_min, self._backoff_max = backoff
        self.set_fps(fps)
        self._lock = threading.Lock()        # preset, brightness, inputs
        self._send_lock = threading.Lock()   # held while a frame is being sent; pause() waits on it
        self._stop_event = threading.Event()
        self._thread = None
        self._preset = None
        self._brightness = 1.0
        self._events, self._audio = [], None
        self._heat, self._heat_enabled = {}, bool(heat_enabled)
        self._previews = []
        self._preview_at, self._preview_frame = None, None
        self._kb, self._need_mode, self._last_rows = None, True, None
        self._pause_count = 0
        self._retry_at, self._backoff = None, None
        self._lut = [hc.gamma([i, i, i])[0] for i in range(256)]

    # ---------- configuration and inputs (any thread) ----------

    def set_fps(self, fps):
        if not isinstance(fps, (int, float)) or isinstance(fps, bool) or not MIN_FPS <= fps <= MAX_FPS:
            raise ValueError(f"fps must be {MIN_FPS}-{MAX_FPS}")
        self.fps = fps

    def set_preset(self, preset):
        """Show a preset (validated and copied, so later edits to the caller's object don't race the
        render thread). None stops sending; the keyboard keeps the last frame."""
        copy = None if preset is None else Preset.from_dict(preset.to_dict())
        with self._lock:
            self._preset = copy

    def set_brightness(self, level):
        if not isinstance(level, (int, float)) or isinstance(level, bool) or not 0 <= level <= 1:
            raise ValueError("brightness must be 0-1")
        with self._lock:
            self._brightness = float(level)

    def push_key_event(self, event):
        """A lighting KeyEvent(key_id, down, t), or an inputs KeyEvent(usage, down, t) carrying a HID
        page-7 usage, which is mapped with keymap.by_hid_usage (usages not on the layout are ignored)."""
        if not hasattr(event, "key_id"):
            key_id = self.keymap.by_hid_usage(event.usage)
            if key_id is None:
                return
            event = KeyEvent(key_id, bool(event.down), float(event.t))
        with self._lock:
            self._events.append(event)
            del self._events[:-MAX_PENDING_EVENTS]
            if self._heat_enabled and event.down and event.key_id in self.keymap:
                self._heat[event.key_id] = self._heat.get(event.key_id, 0) + 1

    def set_audio(self, state):
        with self._lock:
            self._audio = state

    def set_heat_enabled(self, on):
        with self._lock:
            self._heat_enabled = bool(on)

    def set_heat(self, counts):
        with self._lock:
            self._heat = {int(k): int(v) for k, v in counts.items()}

    def reset_heat(self):
        with self._lock:
            self._heat = {}

    def heat_counts(self):
        with self._lock:
            return dict(self._heat)

    def on_frame(self, callback):
        """callback(frame) with the composed Frame (before gamma), at most PREVIEW_FPS times a second,
        only when it changed. Runs on the engine thread: keep it short."""
        self._previews.append(callback)

    # ---------- device ownership ----------

    def pause(self):
        """Stop sending (nests). Returns once the frame in flight, if any, has finished."""
        with self._send_lock:
            self._pause_count += 1

    def resume(self):
        with self._send_lock:
            self._pause_count = max(0, self._pause_count - 1)
            if self._pause_count == 0:  # the paused caller may have changed the effect: re-enter custom mode
                self._need_mode, self._last_rows = True, None

    @contextlib.contextmanager
    def paused(self):
        self.pause()
        try:
            yield
        finally:
            self.resume()

    # ---------- running ----------

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop_event.clear()
        with self._send_lock:
            self._need_mode, self._last_rows = True, None
        self._thread = threading.Thread(target=self._run, name="lighting-engine", daemon=True)
        self._thread.start()

    def stop(self, restore=True):
        """Stop the thread (waiting for the frame in flight), then restore the firmware lighting."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        with self._send_lock:
            self._kb, self._need_mode, self._last_rows = None, True, None
        if restore:
            self.restore_firmware()

    def restore_firmware(self):
        """Run the restore callback (the keyboard's own lighting back); errors go to on_error. Studio calls it
        after stop(restore=False) once its own lock is released, since the callback takes the app's lock."""
        if self._restore is not None:
            try:
                self._restore()
            except Exception as e:
                self._report(e)

    def _run(self):
        next_tick = self._clock()
        while not self._stop_event.is_set():
            self.step(self._clock())
            next_tick += 1.0 / self.fps
            delay = next_tick - self._clock()
            if delay < 0:  # running late: drop the missed ticks instead of bursting
                next_tick, delay = self._clock(), 0
            self._stop_event.wait(delay)

    def step(self, now=None):
        """Render one frame for time `now` and send it if it changed. Returns True when a frame was sent.
        The thread calls this every tick; tests call it directly with a fake time."""
        now = self._clock() if now is None else now
        with self._lock:
            preset, events, self._events = self._preset, self._events, []
            ctx = RenderContext(keymap=self.keymap, keys=self.keymap.ids, params={}, audio=self._audio,
                                events=events, heat=dict(self._heat))
            brightness = self._brightness
        if preset is None:
            return False
        try:
            frame = compose(preset.layers, now, ctx, brightness=brightness * preset.brightness)
        except Exception as e:  # a broken effect must not kill the thread
            self._report(e)
            return False
        self._preview(now, frame)
        rows = self._rows(frame)
        error = None
        with self._send_lock:
            stopping = self._stop_event.is_set() and threading.current_thread() is self._thread
            if self._pause_count or stopping:
                return False
            if self._retry_at is not None and now < self._retry_at:
                return False
            if rows == self._last_rows and not self._need_mode:
                return False
            try:
                if self._kb is None:
                    self._kb = self._factory()
                self._kb.send_frame_fast(rows)
                if self._need_mode:
                    self._kb.enter_custom_mode()
                    self._need_mode = False
                self._last_rows, self._retry_at, self._backoff = rows, None, None
            except Exception as e:
                self._kb, self._need_mode, self._last_rows = None, True, None
                self._backoff = (self._backoff_min if self._backoff is None
                                 else min(self._backoff_max, self._backoff * 2))
                self._retry_at = now + self._backoff
                error = e
        if error is not None:
            self._report(error)
            return False
        return True

    # ---------- helpers ----------

    def _rows(self, frame):
        lut = self._lut
        rows = [[[0, 0, 0] for _ in range(hc.FRAME_COLS)] for _ in range(hc.FRAME_ROWS)]
        for k, (r, g, b) in frame.items():
            row, col = self.keymap.key(k).led
            rows[row][col] = [lut[r], lut[g], lut[b]]
        return rows

    def _preview(self, now, frame):
        if not self._previews or frame == self._preview_frame:
            return
        if self._preview_at is not None and now - self._preview_at < 1.0 / PREVIEW_FPS - 1e-9:
            return
        self._preview_at, self._preview_frame = now, frame
        for cb in list(self._previews):
            try:
                cb(dict(frame))
            except Exception as e:
                self._report(e)

    def _report(self, error):
        if self._on_error is not None:
            try:
                self._on_error(error)
            except Exception:
                pass
