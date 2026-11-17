# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Sound level and 16 frequency bands from an input device, for audio-reactive lighting.

The device is a microphone, or a loopback device (BlackHole, Loopback, Soundflower) to light up to the Mac's
own sound. Audio is analysed in memory block by block and never recorded or stored.

analyse() is pure apart from the state it updates: mono mix, a rolling 4096-sample Hann-windowed rfft, the peak
of each of 16 log-spaced bands (40 Hz to 16 kHz) in dB, auto-gain (the loudest recent band maps to 1, a 40 dB
range below it to 0, never boosting sound quieter than -50 dBFS), then fast attack / slower decay smoothing.
"""
import threading
import time
import traceback
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd

from inputs.types import BANDS, AudioState, InputError, InputPermissionError

FMIN, FMAX = 40.0, 16000.0
FFT_SIZE = 4096          # ~11.7 Hz per bin at 48 kHz, so the 40-58 Hz band has a bin of its own
RANGE_DB = 40.0          # dB below the auto-gain reference that maps to 0
BAND_FLOOR_DB = -50.0    # the reference never drops below this, so hiss and silence stay dark
LEVEL_FLOOR_DB = -40.0
GAIN_FALL_DB_S = 3.0     # how fast the auto-gain reference relaxes after loud passages
LOOPBACK_WORDS = ("blackhole", "loopback", "soundflower", "background music", "ishowu", "virtual")


class AudioError(InputError):
    """The audio input can't start; the message is written for the user."""


class AudioPermissionError(AudioError, InputPermissionError):
    """macOS refused Microphone access (PortAudio reports it as an internal error, -9986)."""


def band_edges(n=BANDS, fmin=FMIN, fmax=FMAX):
    """n + 1 log-spaced edges from fmin to fmax."""
    return [float(x) for x in np.geomspace(fmin, fmax, n + 1)]


def is_loopback_name(name):
    low = name.lower()
    return any(w in low for w in LOOPBACK_WORDS)


@dataclass(frozen=True)
class InputDevice:
    name: str
    index: int
    channels: int
    is_loopback: bool


def list_input_devices(query=None):
    """Input-capable devices, in sounddevice's order (index is what AudioListener's device takes)."""
    devices = (query or sd.query_devices)()
    return [InputDevice(d["name"], i, int(d["max_input_channels"]), is_loopback_name(d["name"]))
            for i, d in enumerate(devices) if d.get("max_input_channels", 0) > 0]


@dataclass
class AnalyserState:
    sensitivity: float = 1.0       # multiplies the 0..1 values (0.5 = half as bright for the same sound)
    attack: float = 0.03           # seconds to rise ~63 % of the way
    decay: float = 0.25            # seconds to fall ~63 % of the way
    bands: np.ndarray = field(default_factory=lambda: np.zeros(BANDS))
    level: float = 0.0
    band_ref_db: float = BAND_FLOOR_DB
    level_ref_db: float = LEVEL_FLOOR_DB
    buffer: np.ndarray = field(default_factory=lambda: np.zeros(FFT_SIZE, dtype=np.float64))
    _cache: dict = field(default_factory=dict)  # samplerate -> (window, window sum, bin -> band masks)


def _layout(state, samplerate):
    lay = state._cache.get(samplerate)
    if lay is None:
        win = np.hanning(FFT_SIZE)
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / samplerate)
        edges = band_edges()
        picks = []
        for i in range(BANDS):
            idx = np.nonzero((freqs >= edges[i]) & (freqs < edges[i + 1]))[0]
            if idx.size == 0:  # band narrower than a bin: use the bin nearest its centre
                centre = (edges[i] * edges[i + 1]) ** 0.5
                idx = np.array([int(np.argmin(np.abs(freqs - centre)))])
            picks.append(idx)
        lay = state._cache[samplerate] = (win, float(win.sum()), picks)
    return lay


def _smooth(current, target, dt, attack, decay):
    rise = 1.0 - np.exp(-dt / attack)
    fall = 1.0 - np.exp(-dt / decay)
    coef = np.where(target > current, rise, fall)
    return current + (target - current) * coef


def analyse(block, samplerate, state):
    """Feed one block (frames, or frames x channels, floats -1..1); returns the updated AudioState."""
    x = np.asarray(block, dtype=np.float64)
    if x.ndim == 2:
        x = x.mean(axis=1)
    n = x.size
    if n == 0:
        return AudioState(float(state.level), [float(b) for b in state.bands])
    dt = n / float(samplerate)
    if n >= FFT_SIZE:
        state.buffer = x[-FFT_SIZE:].copy()
    else:
        state.buffer = np.concatenate([state.buffer[n:], x])

    win, wsum, picks = _layout(state, samplerate)
    amp = np.abs(np.fft.rfft(state.buffer * win)) * 2.0 / wsum  # a full-scale sine reads 1.0
    band_db = np.array([20.0 * np.log10(max(float(amp[idx].max()), 1e-12)) for idx in picks])
    rms = float(np.sqrt(np.mean(x * x)))
    level_db = 20.0 * np.log10(max(rms, 1e-12))

    fall = GAIN_FALL_DB_S * dt
    state.band_ref_db = max(state.band_ref_db - fall, float(band_db.max()), BAND_FLOOR_DB)
    state.level_ref_db = max(state.level_ref_db - fall, level_db, LEVEL_FLOOR_DB)

    k = state.sensitivity
    band_t = np.clip((band_db - (state.band_ref_db - RANGE_DB)) / RANGE_DB * k, 0.0, 1.0)
    level_t = float(np.clip((level_db - (state.level_ref_db - RANGE_DB)) / RANGE_DB * k, 0.0, 1.0))

    state.bands = np.clip(_smooth(state.bands, band_t, dt, state.attack, state.decay), 0.0, 1.0)
    state.level = float(np.clip(_smooth(np.array(state.level), np.array(level_t), dt, state.attack, state.decay),
                                0.0, 1.0))
    return AudioState(state.level, [float(b) for b in state.bands])


class SilenceWatch:
    """True once when the input has been digital silence (exact zeros) for `seconds`.

    That is what macOS delivers when Microphone access is denied, and what a loopback device gives
    when no sound is routed to it.
    """

    def __init__(self, seconds=3.0):
        self.seconds = seconds
        self._since = None
        self._reported = False

    def feed(self, block, now):
        if np.any(np.asarray(block) != 0):
            self._since, self._reported = None, False
            return False
        if self._since is None:
            self._since = now
        if not self._reported and now - self._since >= self.seconds:
            self._reported = True
            return True
        return False


SILENT_MESSAGE = ("No sound is arriving from this input. For a microphone, allow Microphone access for Huntsman "
                  "for Mac in System Settings, Privacy & Security, Microphone. For a loopback device such as "
                  "BlackHole, route the Mac's sound output to it.")


class AudioListener:
    """Streams an input device and calls callback(AudioState) for every analysed block (~47 per second).

    device: a sounddevice index or name, or None for the system default input. on_error(message) is called
    (from the audio thread) when only digital silence arrives for a few seconds, and when the stream stops
    with an error. start() raises AudioError (AudioPermissionError, also an InputPermissionError, if access is refused).
    """

    def __init__(self, device, callback, sensitivity=1.0, on_error=None, blocksize=1024):
        self.device, self.callback, self.on_error = device, callback, on_error
        self.blocksize = blocksize
        self.state = AnalyserState(sensitivity=sensitivity)
        self.watch = SilenceWatch()
        self._stream = None
        self._lock = threading.Lock()
        self.running = False

    def set_sensitivity(self, value):
        self.state.sensitivity = max(0.0, float(value))

    def start(self):
        with self._lock:
            if self.running:
                return
            try:
                info = sd.query_devices(self.device, "input")
                channels = max(1, min(2, int(info["max_input_channels"])))
                samplerate = float(info.get("default_samplerate") or 48000.0)
                stream = sd.InputStream(device=self.device, channels=channels, samplerate=samplerate,
                                        blocksize=self.blocksize, dtype="float32", callback=self._on_block)
                stream.start()
            except (sd.PortAudioError, ValueError) as e:
                raise _open_error(e) from e
            self._stream, self._rate = stream, samplerate
            self.running = True

    def stop(self):
        with self._lock:
            stream, self._stream = self._stream, None
            self.running = False
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except sd.PortAudioError:
                traceback.print_exc()

    def _on_block(self, indata, _frames, _time, status):
        try:
            if self.watch.feed(indata, time.monotonic()) and self.on_error:
                self.on_error(SILENT_MESSAGE)
            self.callback(analyse(indata, self._rate, self.state))
        except Exception:
            traceback.print_exc()  # never raise into PortAudio's thread


def _open_error(e):
    text = str(e)
    if "-9986" in text or "permission" in text.lower() or "not authorized" in text.lower():
        return AudioPermissionError("macOS blocked the audio input. Allow Microphone access for Huntsman for Mac "
                                    "in System Settings, Privacy & Security, Microphone, then try again.")
    return AudioError(f"Couldn't open the audio input: {text}. Check the device in Sound settings, or pick "
                      "another one.")
