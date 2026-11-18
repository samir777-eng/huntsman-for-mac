# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Windows transport: HID feature reports through the hidapi package (`import hid`), the keyboard's normal Windows
driver, no driver swap. Experimental: written from janeblower/easyrazer (crates/core/src/hid.rs, transport.rs:
control interface MI_03, a 91-byte buffer = report ID 00 + the 90-byte packet, the reply readable right after
SET_REPORT, re-read on busy 15 ms apart, at most 10 times) and never run on a Windows PC.

Same interface as huntsman_core.UsbTransport: .model (the detected models.Model, also made the active one),
exchange(report) -> 90-byte reply, exchange_fast(reports) -> replies, close(). Every exchange holds
huntsman_core.usb_lock() (process + file lock), like the Mac's. hid errors become DeviceError, so the app drops the
handle and reconnects. hid is imported only when a transport is made, behind HidApi, so this module imports on macOS
and tests pass a fake hid module.

While Razer Synapse runs (platforms/win_guard.py) nothing reaches the keyboard, not even a read: two programs on the
same HID interface swap each other's replies. Making a transport raises huntsman_core.SynapseRunning before hid is
imported or the device opened, and an open transport raises it before each exchange (the guard is cached, so this
costs a clock read per exchange)."""
import importlib
import time

import huntsman_core as hc
from platforms import win_guard

REPORT_ID = 0x00
PACKET = 90
BUFFER = PACKET + 1
MAX_POLLS = 10            # easyrazer transport.rs MAX_POLLS
POLL_DELAY = 0.015        # easyrazer transport.rs POLL_DELAY
_sleep = time.sleep       # tests replace these
_monotonic = time.monotonic


def _refuse_while_synapse_runs():
    reason = win_guard.write_block_reason()
    if reason:
        raise hc.SynapseRunning(reason)


def _err(e):
    return hc.DeviceError(f"HID: {e}")


class HidDevice:
    """One open hid.device(): 90-byte packets in, 90-byte replies out (report ID framing handled here)."""

    def __init__(self, dev, path):
        self._dev, self.path = dev, path

    def send(self, report):
        report = bytes(report)
        if len(report) != PACKET:
            raise ValueError(f"a report is {PACKET} bytes, not {len(report)}")
        try:
            n = self._dev.send_feature_report(bytes([REPORT_ID]) + report)
        except (OSError, ValueError) as e:
            raise _err(e) from e
        if n is not None and 0 <= n < BUFFER:
            raise hc.DeviceError(f"HID: short write ({n} bytes)")
        if n is not None and n < 0:
            raise hc.DeviceError("HID: write failed")

    def receive(self):
        try:
            r = bytes(self._dev.get_feature_report(REPORT_ID, BUFFER))
        except (OSError, ValueError) as e:
            raise _err(e) from e
        if len(r) < BUFFER:   # hidapi on Windows returns the report ID first, then the packet
            raise hc.DeviceError(f"HID: short reply from keyboard ({len(r)} bytes)")
        return r[1:BUFFER]

    def close(self):
        try:
            self._dev.close()
        except Exception:
            pass


class HidApi:
    """The parts of the hidapi package the transport uses. module: a stand-in for `hid` (tests)."""

    def __init__(self, module=None):
        if module is None:
            try:
                module = importlib.import_module("hid")
            except ImportError as e:
                raise hc.DeviceError("hidapi is missing: pip install -r requirements-win.txt") from e
        self.hid = module

    def enumerate(self, vid):
        try:
            return [dict(d) for d in self.hid.enumerate(vid, 0)]
        except (OSError, ValueError) as e:
            raise _err(e) from e

    def open(self, path):
        dev = self.hid.device()
        try:
            dev.open_path(path)
        except (OSError, ValueError) as e:
            raise hc.DeviceError(f"HID: couldn't open the keyboard's control interface: {e}") from e
        return HidDevice(dev, path)


class HidTransport:
    def __init__(self, hid_module=None):
        _refuse_while_synapse_runs()
        self._api = HidApi(hid_module)
        entries = self._api.enumerate(hc.VID)

        def find(vid, pid):   # every interface-3 entry of pid (Windows lists one per top-level collection)
            return [e for e in entries if e.get("vendor_id") == vid and e.get("product_id") == pid
                    and e.get("interface_number") == hc.CONTROL_INTERFACE] or None
        self.model, found = hc.detect(find)
        self.dev = self._pick(found)
        hc.set_active_model(self.model)

    def _pick(self, candidates):
        """The collection that answers a firmware read (00:81, a read every model gets): feature report 0 belongs to
        only one of the interface's collections, and which one isn't documented."""
        errors = []
        for e in candidates:
            try:
                dev = self._api.open(e["path"])
            except hc.DeviceError as err:
                errors.append(str(err))
                continue
            self.dev = dev
            try:
                req = hc.build_report(0x00, 0x81, size=2)
                hc.check_reply(req, self.exchange(req))
                return dev
            except hc.DeviceError as err:
                errors.append(str(err))
                dev.close()
            finally:
                self.dev = None
        raise hc.DeviceError("couldn't reach the keyboard's control interface: " + "; ".join(errors))

    def _device(self):
        if self.dev is None:
            raise hc.DeviceError("HID: the keyboard connection is closed")
        return self.dev

    def exchange(self, report):
        """Send once, read the reply at once, and re-read while the keyboard says busy (never re-send a write)."""
        _refuse_while_synapse_runs()
        with hc.usb_lock():
            dev = self._device()
            dev.send(report)
            for i in range(MAX_POLLS):
                resp = dev.receive()
                if resp[0] not in (hc.STATUS_NEW, hc.STATUS_BUSY):
                    return resp
                if i < MAX_POLLS - 1:
                    _sleep(POLL_DELAY)
            return resp

    def exchange_fast(self, reports):
        """Several requests under one lock acquisition, each reply polled at once (no 15 ms sleep), as on the Mac:
        by time (FAST_BUSY_BUDGET), pausing briefly after FAST_POLLS quick reads; stops at the first reply that is
        not OK. The caller checks every reply and treats a short list as a failure."""
        _refuse_while_synapse_runs()
        with hc.usb_lock():
            dev = self._device()
            replies = []
            for report in reports:
                dev.send(report)
                deadline = _monotonic() + hc.FAST_BUSY_BUDGET
                polls = 0
                while True:
                    resp = dev.receive()
                    polls += 1
                    if resp[0] not in (hc.STATUS_NEW, hc.STATUS_BUSY) or _monotonic() > deadline:
                        break
                    if polls > hc.FAST_POLLS:
                        _sleep(0.0005)
                replies.append(resp)
                if resp[0] != hc.STATUS_OK:
                    break
            return replies

    def close(self):
        with hc._USB_LOCK:
            dev, self.dev = self.dev, None
            if dev is not None:
                dev.close()
