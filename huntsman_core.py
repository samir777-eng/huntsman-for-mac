# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Razer Huntsman protocol on macOS (and, experimental, Windows), no Synapse. Verified on the Huntsman V3 Pro (1532:02A6); the other models in
models.py get the same commands, behind the experimental-support switch (gate()).

Sources: OpenRazer (packet, lighting), janeblower/easyrazer (analog, Rapid Trigger, Snap Tap,
per-key frame) and ohy1/SensorFinder (actuation/release semantics).

Profile 0 is the live copy the keyboard types with (RAM). The saved slot is the active onboard
profile (flash). Actuation and lighting go to both, so they apply now and survive a replug.
Each key has an actuation point (thr_l, byte 3) and a release point (thr_h, byte 4); the release
must sit below the actuation, and by default it follows it RELEASE_GAP units below, like Synapse.
Each model maps these bytes to mm on its own scale (models.Scale): the constants below are the V3 Pro's; the
V2 Analog's (experimental) is models.V2_ANALOG_SCALE.

Windows (experimental, untested on a Windows PC): the same protocol over hidapi (platforms/win_hid.py, chosen by
open_transport), and the gate treats every model as experimental there and never runs the key tester (platforms.py).
"""
import contextlib
import json
import os
import sys
import threading
import time

import models
import platforms

__version__ = "0.6.0"

VID, PID = 0x1532, 0x02A6   # PID: the verified model; the connected one is active_model().pid
TID = 0x1F
CONTROL_INTERFACE = 3
LIVE = 0
FULL_MM = 255 * 256 / 16380   # 3.985 mm at threshold 255
RT_UNITS_PER_MM = 16380.0
RELEASE_GAP = 6               # Synapse default: 1.2 mm press (76) / 1.1 mm release (70)
MIN_THR = RELEASE_GAP + 1     # 0.1 mm; 7 rather than 6 so the release point below it is at least 1, never 0
FACTORY_THR, FACTORY_REL = 76, 70   # Synapse's defaults: 1.2 mm press, 1.1 mm release
STATUS_NEW, STATUS_BUSY, STATUS_OK = 0x00, 0x01, 0x02
STATUS_NOT_SUPPORTED = 0x03
FRAME_ROWS, FRAME_COLS = 6, 22   # 02A6, verified: rows 6-7 and column 22 are refused (status 05). Others: models.py
FRAME_SIZE = 0x47
FAST_POLLS = 50                  # fast path: quick reply reads before pausing between reads (hardware: 294 fps)
FAST_BUSY_BUDGET = 0.025         # fast path: wait at most this long for a busy reply before skipping the frame
HERE = os.path.dirname(os.path.abspath(__file__))

EFFECTS = {
    "off": ("00 00 00 00", None),
    "static": ("01 00 00 01 {rgb1}", None),
    "breathing_one": ("02 01 00 01 {rgb1}", None),
    "breathing_two": ("02 02 00 02 {rgb1} {rgb2}", None),
    "breathing_random": ("02 00 00 00", None),
    "spectrum": ("03 00 00 00", None),
    "wave": ("04 {dir} {speed} 00", (1, 255)),
    "reactive_key_one": ("05 00 02 01 {rgb1}", None),
    "reactive_key_random": ("05 00 02 00", None),
    # Effect 06 ("ripple" in easyrazer) is accepted but only lights each pressed key in a random colour on
    # firmware 1.03 (checked on hardware); a real ripple is app-drawn (Studio: reactive_ripple), so it is not offered.
    "starlight_random": ("07 00 {speed} 00", (1, 3)),
    "starlight_one": ("07 00 {speed} 01 {rgb1}", (1, 3)),
    "starlight_two": ("07 00 {speed} 02 {rgb1} {rgb2}", (1, 3)),
    # "fire" (09) is listed by easyrazer for this model, but firmware 1.03 refuses it (status 03), checked on hardware.
}
CUSTOM_EFFECT = (0x0C, [0, 0, 0x08])  # OpenRazer form: size 0x0C, store 0, led 0, effect 08
WAVE_DIRS = {"left": 2, "right": 1}
LED_BACKLIGHT = 0x05


class DeviceError(RuntimeError):
    pass


class DeviceBusy(DeviceError):
    """The keyboard stayed busy (status 01) past the time budget, e.g. while sending keystrokes. Not a fault:
    the caller may simply skip this frame."""


class FeatureUnavailable(DeviceError):
    """The connected model doesn't have this feature, or the app never offers it there (key tester on an
    experimental model). Raised before anything is sent."""


class ExperimentalLocked(DeviceError):
    """A write to an experimental model while Experimental support is off. Raised before anything is sent."""


class SynapseRunning(ExperimentalLocked):
    """Windows: Razer Synapse is running, so every write is refused (platforms/win_guard.py), and the hidapi transport
    won't open the keyboard or exchange a report at all, reads included (platforms/win_hid.py). Raised before anything
    is sent. A kind of ExperimentalLocked so every path that handles "refused, still connected" handles it too."""


# ---------- models, detection and the experimental-support gate ----------

_active = models.DEFAULT


def active_model():
    """The connected model (set by detection in UsbTransport); the V3 Pro until one is found."""
    return _active


def set_active_model(model):
    """model: a models.Model or a product id."""
    global _active
    m = model if isinstance(model, models.Model) else models.by_pid(model)
    if m is None:
        raise DeviceError(f"product id {model!r} is not a supported Huntsman")
    _active = m
    return m


def detect(find):
    """find(vid, pid) -> device or None. Returns (model, device) for the first supported model found, in
    models.MODELS order (the verified V3 Pro first)."""
    for m in models.MODELS.values():
        dev = find(VID, m.pid)
        if dev is not None:
            return m, dev
    raise DeviceError("No supported Razer Huntsman found. Is it plugged in by USB?")


def frame_shape(model=None):
    """(rows, columns) of the per-key frame of model, default the active one."""
    return (model or _active).matrix


def _state_path():
    return os.path.join(data_dir(), "state.json")


_switch_cache = (None, None)   # ((path, inode, mtime, ctime, size) of state.json, the switch it held)
_switch_lock = threading.Lock()


def experimental_enabled():
    """Keyboard -> Experimental support (state.json "experimental"). Anything but a stored true is off.
    The gate asks on every write (each Studio frame), so state.json is parsed again only when it changed; a stat
    per check still sees a switch flipped by the app, the CLI or the service at once."""
    global _switch_cache
    path = _state_path()
    try:
        st = os.stat(path)
    except OSError:
        return False
    key = (path, st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)
    with _switch_lock:
        if _switch_cache[0] == key:
            return _switch_cache[1]
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return False
    on = isinstance(raw, dict) and raw.get("experimental") is True
    with _switch_lock:
        _switch_cache = (key, on)
    return on


def set_experimental(on):
    """Remember the switch in state.json, keeping everything else there (same lock as app.update_state)."""
    path = _state_path()
    with platforms.file_lock(os.path.join(os.path.dirname(path), "state.lock")):
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = None
        raw = raw if isinstance(raw, dict) else {}
        raw["experimental"] = bool(on)
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


FEATURE_NAMES = {"lighting": "Lighting", "per_key": "Per-key lighting", "studio": "Lighting Studio",
                 "actuation": "Actuation", "rapid": "Rapid Trigger", "snap_tap": "Snap Tap",
                 "key_tester": "The key tester"}

# Every write command the app sends, by the feature it belongs to. Keyboard.cmd checks these against the model,
# so nothing reaches an experimental keyboard without passing gate(), whoever sends it.
WRITE_COMMANDS = {(0x0F, 0x02): "lighting", (0x0F, 0x04): "lighting", (0x0F, 0x03): "per_key",
                  (0x02, 0x12): "actuation", (0x02, 0x1A): "rapid", (0x02, 0x20): "rapid",
                  (0x02, 0x21): "snap_tap", (0x00, 0x04): "key_tester"}
# Reads: always allowed, except ones that belong to a feature the model doesn't have.
READ_COMMANDS = {(0x00, 0x81): None, (0x05, 0x84): None, (0x0F, 0x82): None, (0x0F, 0x84): None,
                 (0x02, 0x92): "actuation", (0x00, 0x84): "key_tester"}


def gate(model, feature):
    """Raise unless a write for feature may go to model. The verified model is never restricted on the Mac (and the
    switch isn't even read for it). Experimental models, and on Windows every model: features they lack and the key
    tester always raise FeatureUnavailable; everything else raises ExperimentalLocked until Experimental support is
    on. On Windows, while Razer Synapse runs, every write raises SynapseRunning (platforms/win_guard.py); reads are
    stopped too, by the transport (platforms/win_hid.py)."""
    windows = platforms.is_windows()
    if model.verified and model.has(feature) and not windows:
        return
    if not model.has(feature):
        raise FeatureUnavailable(f"{FEATURE_NAMES[feature]} isn't available on the {model.name}.")
    if feature == "key_tester":
        if windows:
            raise FeatureUnavailable("The key tester isn't offered on Windows: Windows support is experimental.")
        raise FeatureUnavailable(f"The key tester isn't offered on the {model.name}: its support is experimental.")
    if windows:
        from platforms import win_guard
        reason = win_guard.write_block_reason()
        if reason:
            raise SynapseRunning(reason)
    if not experimental_enabled():
        if windows:
            raise ExperimentalLocked(f"Windows support is experimental (not yet tested on a Windows PC). Turn on "
                                     f"Keyboard, Experimental support to change the {model.name}'s settings.")
        raise ExperimentalLocked(f"Support for the {model.name} is experimental. Turn on Keyboard, Experimental "
                                 "support to change its settings.")


def synapse_block():
    """Windows: why the keyboard is left alone right now (Razer Synapse runs: no writes and no reads, since two
    programs on one HID interface swap replies), else None. The Mac never asks."""
    if not platforms.is_windows():
        return None
    from platforms import win_guard
    return win_guard.write_block_reason()


def model_info(model):
    """model.info() as the window should see it on this platform, plus "platform", "platform_experimental" and
    "model_status" (the table's own status). On Windows every model reports "experimental" and no key tester."""
    d = model.info()
    d["model_status"] = model.status
    if platforms.is_windows():
        d["status"] = models.EXPERIMENTAL
        d["features"] = {**d["features"], "key_tester": False}
    d.update(platforms.info())
    return d


# ---------- pure encoding (unit-tested) ----------

def build_report(cls, cid, args=(), size=None):
    args = bytes(args)
    if len(args) > 80:
        raise ValueError("arguments longer than 80 bytes")
    r = bytearray(90)
    r[1] = TID
    r[5] = len(args) if size is None else size
    r[6], r[7] = cls, cid
    r[8:8 + len(args)] = args
    r[88] = crc(r)
    return r


def crc(r):
    c = 0
    for b in r[2:88]:
        c ^= b
    return c


def check_reply(req, resp):
    """Raise unless resp is a finished, successful answer to req."""
    if len(resp) < 90:
        raise DeviceError("short reply from keyboard")
    if resp[1] != req[1] or resp[6] != req[6] or resp[7] != req[7]:
        raise DeviceError(f"reply does not match request {req[6]:02X}:{req[7]:02X}")
    if resp[88] != crc(resp):
        raise DeviceError(f"reply to {req[6]:02X}:{req[7]:02X} failed its checksum")
    if resp[0] != STATUS_OK:
        if resp[0] == STATUS_NOT_SUPPORTED:
            raise DeviceError(f"The keyboard doesn't support this (command {req[6]:02X}:{req[7]:02X}).")
        raise DeviceError(f"keyboard refused {req[6]:02X}:{req[7]:02X} (status {resp[0]:02X})")


def mm_to_threshold(mm, scale=None):
    """Actuation byte for mm on scale (a models.Scale), default the V3 Pro's: 0.1-4.0 mm, and 1.2 mm gives
    Synapse's factory 76 (the scale gives 77) so the preset and "factory" are identical."""
    return (scale or models.V3_SCALE).threshold(mm)


def threshold_to_mm(t, scale=None):
    return (scale or models.V3_SCALE).mm(t)


def release_for(thr, release_mm=None, scale=None):
    """Release byte for an actuation byte: explicit, or by default just above (RELEASE_GAP below on the V3 Pro).
    Never 0."""
    return (scale or models.V3_SCALE).release(thr, release_mm)


def rt_distance(mm):
    mm = round(float(mm), 2)
    if not 0.1 <= mm <= 2.5:
        raise ValueError(f"Rapid Trigger distance {mm} mm is outside 0.1-2.5")
    return max(1, min(0xFFFF, round(mm * RT_UNITS_PER_MM))).to_bytes(2, "big")


def rapid_packets(profile, keys):
    """keys: list of (key_id, (press_mm, release_mm) or None). Returns arg lists for 02:1A."""
    switch = bytes([0xFF, 1 if any(rt for _, rt in keys) else 0, 0, 0, 0, 0])
    entries = [switch]
    for k, rt in keys:
        if rt:
            press, release = rt
            entries.append(bytes([k, 1]) + rt_distance(release) + rt_distance(press))
        else:
            entries.append(bytes([k, 0, 0, 0, 0, 0]))
    per = (80 - 2) // 6
    return [bytes([0, profile]) + b"".join(entries[i:i + per]) for i in range(0, len(entries), per)]


def check_rgb(rgb):
    """Exactly three whole numbers 0-255, else ValueError (checked before anything is sent)."""
    if (not isinstance(rgb, (list, tuple)) or len(rgb) != 3
            or not all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in rgb)):
        raise ValueError(f"colour {rgb!r} must be three whole numbers 0-255")
    return list(rgb)


def gamma(rgb, g=2.2):
    """sRGB picker colour -> LED drive level. LEDs are linear, so mid values look too bright without it."""
    check_rgb(rgb)
    return [round(255 * (int(c) / 255) ** g) for c in rgb]


def encode_effect(name, rgb1=None, rgb2=None, speed=None, direction=None):
    if name not in EFFECTS:
        raise ValueError(f"unknown effect {name}")
    template, speed_range = EFFECTS[name]
    out = []
    for tok in template.split():
        if tok in ("{rgb1}", "{rgb2}"):
            rgb = rgb1 if tok == "{rgb1}" else rgb2
            if rgb is None or len(rgb) != 3 or not all(0 <= int(c) <= 255 for c in rgb):
                raise ValueError(f"{name} needs {tok[1:-1]} as three 0-255 values")
            out += [int(c) for c in rgb]
        elif tok == "{speed}":
            lo, hi = speed_range
            if speed is None or not lo <= int(speed) <= hi:
                raise ValueError(f"{name} needs speed {lo}-{hi}")
            out.append(int(speed))
        elif tok == "{dir}":
            if direction not in WAVE_DIRS:
                raise ValueError("wave needs direction left or right")
            out.append(WAVE_DIRS[direction])
        else:
            out.append(int(tok, 16))
    return out


def frame_rows(colors, layout, base=(0, 0, 0), shape=None):
    """colors: {key_id: [r,g,b]} -> rows x columns RGB cells (args for 0F:03 after the header). shape: (rows, cols),
    default the active model's matrix (6 x 22 on the V3 Pro)."""
    n_rows, n_cols = shape or frame_shape()
    rows = [[list(base) for _ in range(n_cols)] for _ in range(n_rows)]
    led = {k["id"]: k["led"] for k in layout}
    for kid, rgb in colors.items():
        if int(kid) in led:
            r, c = led[int(kid)]
            rows[r][c] = [int(v) for v in rgb]
    return rows


def parse_key_assignment(data, profile, key):
    fn_size = data[6]
    if data[0] != profile or data[1] != key or data[2] != 0 or 7 + fn_size > 80:
        raise DeviceError(f"unexpected key data for key {key} profile {profile}")
    return bytearray(data[:7 + fn_size])


# ---------- transport ----------

# One USB request/reply at a time for the whole process, kept for its lifetime: every UsbTransport
# (including ones made after a reconnect) shares it, and close() takes it so a handle is never
# disposed in the middle of an exchange.
_USB_LOCK = threading.RLock()


@contextlib.contextmanager
def usb_lock():
    """The process lock, plus a file lock so the app, the login agent and the CLI never interleave."""
    with _USB_LOCK:
        with platforms.file_lock(os.path.join(data_dir(), "usb.lock")):
            yield


def open_transport():
    """The keyboard transport for this platform: pyusb/libusb on the Mac, hidapi on Windows (experimental)."""
    if platforms.is_windows():
        from platforms import win_hid
        return win_hid.HidTransport()
    return UsbTransport()


HOMEBREW_LIBUSB = ("/opt/homebrew/lib/libusb-1.0.dylib", "/usr/local/lib/libusb-1.0.dylib")


def libusb_path():
    """The libusb to load: in the installed app (frozen, packaging/mac) the copy bundled next to its code
    (Contents/Frameworks, from the libusb-package wheel) first; then Homebrew's (a source install). None if none."""
    cands = []
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        cands.append(os.path.join(sys._MEIPASS, "libusb-1.0.dylib"))
    cands += HOMEBREW_LIBUSB
    return next((p for p in cands if os.path.exists(p)), None)


class UsbTransport:
    def __init__(self):
        import usb.core
        import usb.backend.libusb1
        lib = libusb_path()
        if lib is None:
            raise DeviceError("libusb is missing: run  brew install libusb")
        be = usb.backend.libusb1.get_backend(find_library=lambda _: lib)
        self.model, self.dev = detect(lambda vid, pid: usb.core.find(idVendor=vid, idProduct=pid, backend=be))
        set_active_model(self.model)

    def exchange(self, report):
        """Send once, then re-read while the keyboard says busy (never re-send a write)."""
        import usb.util
        with usb_lock():
            return self._exchange(report, usb.util)

    def _exchange(self, report, usb_util):
        try:
            self.dev.ctrl_transfer(0x21, 0x09, 0x300, CONTROL_INTERFACE, report)
            for _ in range(15):
                time.sleep(0.015)
                resp = bytes(self.dev.ctrl_transfer(0xA1, 0x01, 0x300, CONTROL_INTERFACE, 90))
                if resp[0] not in (STATUS_NEW, STATUS_BUSY):  # 00 = not started yet, 01 = working
                    return resp
            return resp
        finally:
            try:  # pyusb claims the interface per transfer; release so other tools can use the keyboard
                usb_util.release_interface(self.dev, CONTROL_INTERFACE)
            except Exception:
                pass

    def exchange_fast(self, reports):
        """Several requests under one lock acquisition, each reply polled at once (no 15 ms sleep).
        Stops at the first reply that is not OK, so nothing more is written to a busy or refusing keyboard;
        the caller checks every reply (check_reply) and treats a short list as a failure."""
        import usb.util
        with usb_lock():
            try:
                replies = []
                for report in reports:
                    self.dev.ctrl_transfer(0x21, 0x09, 0x300, CONTROL_INTERFACE, report)
                    # Poll by time, not count: while the user types the keyboard is busy longer (hardware).
                    deadline = time.monotonic() + FAST_BUSY_BUDGET
                    polls = 0
                    while True:
                        resp = bytes(self.dev.ctrl_transfer(0xA1, 0x01, 0x300, CONTROL_INTERFACE, 90))
                        polls += 1
                        if resp[0] not in (STATUS_NEW, STATUS_BUSY) or time.monotonic() > deadline:
                            break
                        if polls > FAST_POLLS:
                            time.sleep(0.0005)  # stop hammering after the quick reads
                    replies.append(resp)
                    if resp[0] != STATUS_OK:
                        break
                return replies
            finally:
                try:
                    usb.util.release_interface(self.dev, CONTROL_INTERFACE)
                except Exception:
                    pass

    def close(self):
        with _USB_LOCK:
            try:
                import usb.util
                usb.util.dispose_resources(self.dev)
            except Exception:
                pass


class Keyboard:
    def __init__(self, transport=None, model=None):
        self.t = transport or open_transport()
        detected = getattr(self.t, "model", None)
        self.model = model or (detected if isinstance(detected, models.Model) else None) or active_model()

    def check_write(self, feature):
        gate(self.model, feature)

    def allowed(self, feature):
        try:
            gate(self.model, feature)
            return True
        except DeviceError:
            return False

    def _check_command(self, cls, cid):
        if (cls, cid) in WRITE_COMMANDS:
            gate(self.model, WRITE_COMMANDS[(cls, cid)])
        elif (cls, cid) in READ_COMMANDS:
            feature = READ_COMMANDS[(cls, cid)]
            if feature and not self.model.has(feature):
                raise FeatureUnavailable(f"{FEATURE_NAMES[feature]} isn't available on the {self.model.name}.")
            if feature == "key_tester" and platforms.is_windows():   # driver mode is never used on Windows
                gate(self.model, feature)
        elif not self.model.verified or platforms.is_windows():
            raise FeatureUnavailable(f"command {cls:02X}:{cid:02X} is not sent to the {self.model.name}.")

    def cmd(self, cls, cid, args=(), size=None):
        self._check_command(cls, cid)
        req = build_report(cls, cid, args, size)
        resp = self.t.exchange(req)
        check_reply(req, resp)
        return resp[8:88]

    # info
    def firmware(self):
        a = self.cmd(0x00, 0x81, size=2)
        return f"{a[0]}.{a[1]:02d}"

    def active_profile(self):
        return self.cmd(0x05, 0x84, size=1)[0]

    @property
    def saved(self):
        """The flash slot the keyboard loads on replug. Read fresh every time (never cached), since the
        owner can switch profiles on the keyboard while the app runs; every write op reads it first."""
        p = self.active_profile()
        if not 1 <= p <= 5:
            raise DeviceError(f"unexpected active profile {p}")
        return p

    def both(self):
        return (LIVE, self.saved)

    # actuation
    def _need(self, feature):
        if not self.model.has(feature):
            raise FeatureUnavailable(f"{FEATURE_NAMES[feature]} isn't available on the {self.model.name}.")

    def read_key(self, profile, key):
        return parse_key_assignment(self.cmd(0x02, 0x92, [profile, key, 0], 80), profile, key)

    def read_points(self, key, profile=LIVE):
        """(actuation mm, release mm) the key acts on: on the V2 Analog the firmware clamps the stored bytes."""
        sc = self.model.scale
        a = self.read_key(profile, key)
        thr, rel = sc.effective(a[3], a[4])
        return sc.mm(thr), sc.mm(rel)

    def _write_points(self, keys, thr, rel):
        """Per key: saved (flash) first, then live (RAM), so a failure never leaves flash behind RAM.
        Read-modify-write: only the two threshold bytes change; the layer and the key's function (fnId, size,
        data) are written back as read (easyrazer actuation.rs update). A key whose saved write doesn't read back
        is reported and its live copy is left alone.
        Models other than the V3 family: keys already at the target are not written again, to spare flash. The V3
        family keeps its verified behaviour (always written)."""
        self.check_write("actuation")
        sc = self.model.scale
        v3 = sc is models.V3_SCALE
        saved = self.saved
        failed = []
        for k in keys:
            for p in (saved, LIVE):
                a = self.read_key(p, k)
                if not v3 and (a[3], a[4]) == (thr, rel):
                    continue
                a[3], a[4] = thr, rel
                self.cmd(0x02, 0x12, a, 80)
                if tuple(self.read_key(p, k)[3:5]) != (thr, rel):
                    failed.append(k)
                    break
        return sorted(set(failed))

    def set_actuation(self, keys, mm, release_mm=None):
        """mm (and release_mm) on the model's scale and range; out of range raises before anything is sent.
        Without release_mm the reset point follows the scale's default just above (the same in saved and live)."""
        sc = self.model.scale
        thr = sc.threshold(mm)
        return self._write_points(keys, thr, sc.release(thr, release_mm))

    def restore_snapshot(self, snap):
        """Write back a snapshot() taken earlier. Refuses a snapshot of another model (one without a PID was taken
        before v0.3.0, on the V3 Pro), and one taken while another saved profile was active."""
        pid = snap.get("pid", f"{PID:04X}")
        if pid != f"{self.model.pid:04X}":
            known = models.by_pid(int(pid, 16)) if isinstance(pid, str) and len(pid) == 4 else None
            raise DeviceError(f"the snapshot is from the {known.name if known else 'keyboard'} ({pid}), but the "
                              f"{self.model.name} ({self.model.pid:04X}) is connected; nothing was written")
        self.check_write("actuation")
        saved = self.saved
        if snap["saved_profile"] != saved:
            raise DeviceError(f"the snapshot is from profile {snap['saved_profile']}, but profile {saved} is active")
        entries = []
        for p, keys in snap["profiles"].items():
            for k, hexdata in keys.items():
                a = bytearray(bytes.fromhex(hexdata))
                # same checks as a read: right profile, right key, normal layer, sane length
                if len(a) < 7 or a[0] != int(p) or a[1] != int(k) or a[2] != 0 or 7 + a[6] != len(a) or len(a) > 80:
                    raise DeviceError(f"snapshot entry for key {k} profile {p} is damaged; nothing was written")
                entries.append((int(p), int(k), a))
        failed = []
        for p, k, a in entries:
            self.cmd(0x02, 0x12, a, 80)
            if self.read_key(p, k) != a:
                failed.append(k)
        return sorted(set(failed))

    # Rapid Trigger / Snap Tap: ON goes to the live profile only (as easyrazer does; unverified in flash),
    # OFF goes to both so nothing stale is left in flash.
    def set_rapid(self, keys):
        self.check_write("rapid")
        on = any(rt for _, rt in keys)
        both = self.both()  # read the saved profile even for ON: refuse to write if it looks wrong
        for p in ((LIVE,) if on else both):
            for args in rapid_packets(p, keys):
                self.cmd(0x02, 0x1A, args)

    def set_continuous(self, on):
        self.check_write("rapid")
        both = self.both()
        for p in ((LIVE,) if on else both):
            self.cmd(0x02, 0x20, [p, 1 if on else 0])

    def set_snap_tap(self, pair):
        self.check_write("snap_tap")
        a, b = pair if pair else (0, 0)
        both = self.both()
        for p in ((LIVE,) if pair else both):
            self.cmd(0x02, 0x21, [p, 1 if pair else 0, a, b])

    # lighting
    def set_effect(self, name, rgb1=None, rgb2=None, correct=True, store=1, **kw):
        """Built-in effect. store 1 saves it on the keyboard; store 0 shows it from RAM only (used to put back
        what flash already holds, without another flash write). Colours are gamma-corrected (verified to match
        on hardware)."""
        self.check_write("lighting")
        if name not in self.model.effects:
            raise FeatureUnavailable(f"The {name} effect isn't available on the {self.model.name}.")
        fix = gamma if correct else (lambda c: c)
        kw.update(rgb1=fix(rgb1) if rgb1 else None, rgb2=fix(rgb2) if rgb2 else None)
        self.cmd(0x0F, 0x02, [store, LED_BACKLIGHT] + encode_effect(name, **kw))

    def set_custom(self, colors, layout, base=(0, 0, 0), correct=True):
        """Per-key colours. The firmware keeps these in RAM only, so they are re-sent at app start/login."""
        self.check_write("per_key")
        for v in list(colors.values()) + [base]:  # all colours valid before the first frame goes out
            check_rgb(v)
        fix = gamma if correct else (lambda c: c)
        colors = {k: fix(v) for k, v in colors.items()}
        self._show_rows(frame_rows(colors, layout, fix(base), self.model.matrix))

    def _show_rows(self, rows):
        cols = self.model.cols
        for i, row in enumerate(rows):
            self.cmd(0x0F, 0x03, [0, 0, i, 0, cols - 1] + [v for cell in row for v in cell], self.model.frame_size)
        size, args = CUSTOM_EFFECT
        self.cmd(0x0F, 0x02, args, size)

    def light_cell(self, row, col, rgb=(255, 255, 255), base=(0, 0, 0)):
        """LED check: light one matrix cell (row, col) and nothing else, through the per-key frame path, so a
        tester can say which key it is. Same gate as per-key colours."""
        rows, cols = self.model.matrix
        for v, n, what in ((row, rows, "row"), (col, cols, "column")):
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v < n:
                raise ValueError(f"{what} {v!r} is outside the {rows}x{cols} matrix of the {self.model.name}")
        self.check_write("per_key")
        on, off = gamma(rgb), gamma(base)
        frame = [[list(off) for _ in range(cols)] for _ in range(rows)]
        frame[row][col] = list(on)
        self._show_rows(frame)
        return [row, col]

    def enter_custom_mode(self):
        """Show the per-key frame buffer (the custom effect). Needed once before streaming frames."""
        self.check_write("per_key")
        size, args = CUSTOM_EFFECT
        self.cmd(0x0F, 0x02, args, size)

    def send_frame_fast(self, rows):
        """One per-key frame: FRAME_ROWS rows of FRAME_COLS [r,g,b] cells, already gamma-corrected.
        Six 0F:03 packets in one locked batch (transport.exchange_fast) when the transport has one;
        every reply is CRC- and status-checked. Does not switch to the custom effect (enter_custom_mode)."""
        n_rows, n_cols = self.model.matrix
        if len(rows) != n_rows or any(len(row) != n_cols for row in rows):
            raise ValueError(f"a frame is {n_rows} rows of {n_cols} colours")
        self.check_write("per_key")
        reqs = []
        for i, row in enumerate(rows):
            cells = [v for cell in row for v in check_rgb(cell)]
            reqs.append(build_report(0x0F, 0x03, [0, 0, i, 0, n_cols - 1] + cells, self.model.frame_size))
        fast = getattr(self.t, "exchange_fast", None)
        resps = fast(reqs) if fast else [self.t.exchange(r) for r in reqs]
        for req, resp in zip(reqs, resps):
            if resp[0] in (STATUS_NEW, STATUS_BUSY) and len(resp) >= 90 and resp[6:8] == req[6:8]:
                raise DeviceBusy("keyboard busy; frame skipped")
            check_reply(req, resp)
        if len(resps) != len(reqs):
            raise DeviceError(f"frame cut short: {len(resps)} of {len(reqs)} rows answered")

    def get_effect_raw(self):
        return bytes(self.cmd(0x0F, 0x82, [1, LED_BACKLIGHT], 12)[:12])

    def set_brightness(self, percent, stores=(0, 1)):
        """stores: 0 = live only (while a slider drags), 1 = saved on the keyboard."""
        self.check_write("lighting")
        v = round(max(0, min(100, int(percent))) * 255 / 100)
        for store in stores:
            self.cmd(0x0F, 0x04, [store, LED_BACKLIGHT, v])

    def brightness(self):
        return round(self.cmd(0x0F, 0x84, [1, LED_BACKLIGHT], 3)[2] * 100 / 255)


    def restore_factory(self, keys):
        """Synapse's defaults: actuation 1.2 mm (76), release 1.1 mm (70). Refused on a model whose factory point
        isn't known (the V2 Analog), before anything is sent."""
        self.check_factory()
        return self._write_points(keys, *self.model.scale.factory)

    def check_factory(self):
        self._need("actuation")
        if self.model.scale.factory is None:
            raise FeatureUnavailable(f"The {self.model.name}'s factory depth isn't known, so it can't be restored. "
                                     "The first-launch snapshot (huntsman.py restore-snapshot) puts every key back "
                                     "as it was.")

    def snapshot(self, keys):
        """Every key's raw assignment in the live and saved profiles, for manual recovery.
        Keys the firmware refuses to read are listed under "skipped" instead of failing the whole copy."""
        self._need("actuation")
        saved = self.saved
        profiles, skipped = {}, []
        for p in (LIVE, saved):
            profiles[str(p)] = {}
            for k in keys:
                try:
                    profiles[str(p)][str(k)] = self.read_key(p, k).hex()
                except DeviceError:
                    skipped.append([p, k])
        return {"pid": f"{self.model.pid:04X}", "saved_profile": saved, "profiles": profiles, "skipped": skipped}


def data_dir():
    """Per-user settings live outside the code folder (platforms.data_dir: Application Support on the Mac,
    %APPDATA% on Windows)."""
    d = platforms.data_dir()
    os.makedirs(d, exist_ok=True)
    return d


def load_layout(model=None):
    """Keys of model (default the active one): layout.json for the V3 Pro, layouts/<PID>.json for the others."""
    with open(os.path.join(HERE, (model or _active).layout), encoding="utf-8") as f:
        return json.load(f)


def all_key_ids(model=None):
    """Keys whose actuation the app manages (everything on the layout except Fn)."""
    return sorted({k["id"] for k in load_layout(model) if k["name"] != "RIGHT_GUI"})


def every_key_id(model=None):
    """Every key id in the firmware's key map (from easyrazer), incl. keys not on this layout,
    used to clear per-key Rapid Trigger entries everywhere."""
    with open(os.path.join(HERE, "keymap.json"), encoding="utf-8") as f:
        return sorted(set(json.load(f).values()) | set(all_key_ids(model)))
