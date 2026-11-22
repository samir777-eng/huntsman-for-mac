# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The Windows gate: on Windows every model is experimental (writes need the Experimental support switch, even on
the verified V3 Pro) and the key tester (driver mode 00:04, mode read 00:84) is never sent; the model info says
platform "windows" and platform_experimental true so the window can say so. On the Mac nothing changes (the golden
02A6 bytes in test_golden_02a6.py pin that). FakeTransport only; settings go to tmp_path."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import depth_stream  # noqa: E402
import huntsman_core as hc  # noqa: E402
import models  # noqa: E402
from test_core import FakeTransport  # noqa: E402
from test_models_wiring import V3, MINI, api_for, app, plug  # noqa: E402,F401 (fixtures)
from test_platforms import FakeMsvcrt  # noqa: E402

V3PRO = models.MODELS[V3]


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    return tmp_path


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt())   # state.lock goes through msvcrt.locking


# ---------- the gate ----------

@pytest.mark.parametrize("feature", ["lighting", "per_key", "studio", "actuation", "rapid", "snap_tap"])
def test_the_verified_v3_pro_needs_the_switch_on_windows(data, windows, feature):
    with pytest.raises(hc.ExperimentalLocked) as e:
        hc.gate(V3PRO, feature)
    assert "Windows" in str(e.value) and "Experimental support" in str(e.value)
    hc.set_experimental(True)
    hc.gate(V3PRO, feature)


def test_the_key_tester_is_refused_on_windows_even_with_the_switch(data, windows):
    hc.set_experimental(True)
    with pytest.raises(hc.FeatureUnavailable, match="Windows"):
        hc.gate(V3PRO, "key_tester")


def test_experimental_models_keep_their_rules_on_windows(data, windows):
    mini = models.MODELS[MINI]
    with pytest.raises(hc.ExperimentalLocked):
        hc.gate(mini, "lighting")
    hc.set_experimental(True)
    hc.gate(mini, "lighting")
    with pytest.raises(hc.FeatureUnavailable):
        hc.gate(mini, "key_tester")
    with pytest.raises(hc.FeatureUnavailable):
        hc.gate(models.MODELS[0x026C], "actuation")


def test_the_mac_gate_is_unchanged(data):
    for f in models.FEATURES:
        hc.gate(V3PRO, f)   # the verified model, switch off: never restricted
    with pytest.raises(hc.ExperimentalLocked):
        hc.gate(models.MODELS[MINI], "lighting")


# ---------- commands ----------

def test_driver_mode_and_its_read_are_never_sent_on_windows(data, windows):
    hc.set_experimental(True)
    t = FakeTransport()
    kb = hc.Keyboard(t, model=V3PRO)
    for cls, cid, args in ((0x00, 0x04, [3, 0]), (0x00, 0x84, [])):
        with pytest.raises(hc.FeatureUnavailable):
            kb.cmd(cls, cid, args, 2)
    with pytest.raises(hc.FeatureUnavailable):   # unknown commands too, as on an experimental model
        kb.cmd(0x07, 0x01)
    assert t.sent == []
    assert kb.firmware() and len(t.sent) == 1   # reads still go out
    assert depth_stream.recover_typing(kb) is False and len(t.sent) == 1


def test_locked_writes_send_nothing_on_windows(data, windows):
    t = FakeTransport()
    kb = hc.Keyboard(t, model=V3PRO)
    with pytest.raises(hc.ExperimentalLocked):
        kb.set_brightness(50)
    with pytest.raises(hc.ExperimentalLocked):
        kb.set_actuation([31], 2.0)
    assert [r for r in t.sent if (r[6], r[7]) in hc.WRITE_COMMANDS] == []
    assert kb.allowed("lighting") is False and kb.allowed("key_tester") is False


def test_writes_go_out_on_windows_once_the_switch_is_on(data, windows):
    hc.set_experimental(True)
    t = FakeTransport()
    kb = hc.Keyboard(t, model=V3PRO)
    kb.set_brightness(50)
    assert [(r[6], r[7]) for r in t.sent] == [(0x0F, 0x04), (0x0F, 0x04)]


# ---------- model info ----------

def test_model_info_on_windows(windows):
    d = hc.model_info(V3PRO)
    assert d["platform"] == "windows" and d["platform_experimental"] is True
    assert d["status"] == "experimental" and d["model_status"] == "verified"
    assert d["features"]["key_tester"] is False and d["features"]["actuation"] is True
    assert V3PRO.info()["features"]["key_tester"] is True   # the table itself is untouched


def test_model_info_on_the_mac():
    d = hc.model_info(V3PRO)
    assert d == {**V3PRO.info(), "model_status": "verified", "platform": "mac", "platform_experimental": False}


def test_the_window_sees_windows_as_experimental(app, plug, windows):
    plug(V3)
    api = api_for(app)
    d = api.model()["data"]
    assert d["platform"] == "windows" and d["platform_experimental"] is True
    assert d["status"] == "experimental" and d["locked"] is True and d["features"]["key_tester"] is False
    assert api.info()["data"]["model"]["platform"] == "windows"
    r = api.set_brightness(40)
    assert r["ok"] is False and r["reason"] == "experimental"
    api.set_experimental(True)
    assert api.model()["data"]["locked"] is False
    assert api.start_test()["reason"] == "unavailable"


def test_the_window_on_the_mac_reports_the_platform(app, plug):
    plug(V3)
    d = api_for(app).model()["data"]
    assert d["platform"] == "mac" and d["platform_experimental"] is False
    assert d["status"] == "verified" and d["locked"] is False and all(d["features"].values())
