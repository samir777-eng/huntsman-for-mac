# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The Synapse guard and the Dynamic Lighting notice on Windows (platforms/win_guard.py).

While Razer Synapse runs it owns the keyboard (it overwrites the live profile and two writers mix replies), so the
app and the lighting service only read, say why, and re-check every few seconds. Windows Dynamic Lighting on means
lighting commands may do nothing: the window says how to turn it off for this keyboard (the app never changes it).
Fake process lists, a fake clock and a fake winreg; the keyboard is FakeTransport."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import huntsman_core as hc  # noqa: E402
import models  # noqa: E402
from platforms import win_guard as wg  # noqa: E402
from test_core import FakeTransport  # noqa: E402
from test_platforms import FakeMsvcrt  # noqa: E402

V3PRO = models.MODELS[0x02A6]


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Procs:
    def __init__(self, *names):
        self.names, self.calls = list(names), 0

    def __call__(self):
        self.calls += 1
        if self.names == ["<fail>"]:
            raise OSError("snapshot failed")
        return list(self.names)


@pytest.fixture
def windows(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt())
    procs, clock = Procs("explorer.exe"), Clock()
    monkeypatch.setattr(wg, "_guard", wg.Guard(list_processes=procs, clock=clock))
    return procs, clock


# ---------- detection ----------

@pytest.mark.parametrize("name", ["RazerAppEngine.exe", "razerappengine.exe", "Razer Synapse Service.exe",
                                  "Razer Synapse 3.exe", "Razer Synapse Service Process.exe", "RzSynapse.exe"])
def test_synapse_processes_are_recognised(name):
    assert wg.synapse_process(["svchost.exe", name]) == name


def test_other_razer_or_unrelated_processes_are_not_synapse():
    assert wg.synapse_process(["svchost.exe", "Razer Central.exe", "RazerCortex.exe", "Huntsman.exe"]) is None
    assert wg.synapse_process([]) is None


def test_the_guard_says_why_and_rechecks_after_a_few_seconds():
    procs, clock = Procs("RazerAppEngine.exe"), Clock()
    g = wg.Guard(list_processes=procs, clock=clock)
    r = g.reason()
    assert "Razer Synapse" in r and "read" in r.lower() and "quit" in r.lower()
    assert g.reason() == r and procs.calls == 1            # cached
    procs.names = ["explorer.exe"]
    clock.t += wg.CHECK_EVERY - 0.1
    assert g.reason() == r                                   # not yet re-checked
    clock.t += 0.2
    assert g.reason() is None and procs.calls == 2           # Synapse quit: writes allowed again


def test_a_failed_process_check_counts_as_running():
    g = wg.Guard(list_processes=Procs("<fail>"), clock=Clock())
    assert "Razer Synapse" in g.reason()


def test_tasklist_output_is_parsed():
    out = '"System Idle Process","0","Services","0","8 K"\r\n"RazerAppEngine.exe","4242","Console","1","90,000 K"\r\n'
    assert wg.parse_tasklist(out) == ["System Idle Process", "RazerAppEngine.exe"]
    assert wg.parse_tasklist("INFO: No tasks are running which match the specified criteria.\r\n") == []


@pytest.mark.mac_only   # needs a host that is not Windows
def test_process_listing_off_windows_is_empty():
    assert wg.list_processes() == []   # this Mac: nothing to list (tests that pretend to be Windows stay usable)


# ---------- the gate ----------

def test_writes_are_refused_while_synapse_runs_even_with_experimental_on(windows):
    procs, clock = windows
    hc.set_experimental(True)
    procs.names = ["RazerAppEngine.exe"]
    t = FakeTransport()
    kb = hc.Keyboard(t, model=V3PRO)
    with pytest.raises(hc.SynapseRunning) as e:
        kb.set_brightness(50)
    assert "Razer Synapse" in str(e.value)
    assert [r for r in t.sent if (r[6], r[7]) in hc.WRITE_COMMANDS] == []
    assert kb.allowed("lighting") is False
    assert kb.firmware() and len(t.sent) == 1    # reads still go out
    procs.names = []
    clock.t += wg.CHECK_EVERY
    kb.set_brightness(50)                        # re-checked: Synapse is gone
    assert kb.allowed("lighting") is True


def test_synapse_counts_as_a_refusal_before_anything_was_sent(windows):
    procs, _ = windows
    procs.names = ["RazerAppEngine.exe"]
    with pytest.raises(hc.ExperimentalLocked):   # so every "refused, still connected" path handles it
        hc.gate(V3PRO, "lighting")
    import app as appmod
    try:
        hc.gate(V3PRO, "lighting")
    except hc.DeviceError as e:
        r = appmod.refused(e)
    assert r["ok"] is False and r["reason"] == "synapse" and "Razer Synapse" in r["error"]


def test_missing_features_are_still_reported_as_missing(windows):
    procs, _ = windows
    procs.names = ["RazerAppEngine.exe"]
    with pytest.raises(hc.FeatureUnavailable):
        hc.gate(V3PRO, "key_tester")


def test_the_mac_never_asks_about_synapse(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    procs = Procs("RazerAppEngine.exe")
    monkeypatch.setattr(wg, "_guard", wg.Guard(list_processes=procs, clock=Clock()))
    for f in models.FEATURES:
        hc.gate(V3PRO, f)
    assert procs.calls == 0


def test_the_lighting_service_keeps_studio_off_with_the_reason(windows):
    import service
    procs, _ = windows
    hc.set_experimental(True)
    procs.names = ["RazerAppEngine.exe"]
    svc = service.LightingService()
    svc._kb = hc.Keyboard(FakeTransport(), model=V3PRO)
    assert "Razer Synapse" in svc.studio_blocked()


def test_the_window_gets_the_reason_and_the_notices(windows, monkeypatch):
    from test_models_wiring import FakeService, make_api
    import app as appmod
    procs, _ = windows
    monkeypatch.setattr(appmod, "STATE_FILE", os.path.join(hc.data_dir(), "state.json"))
    monkeypatch.setattr(wg, "notices", lambda winreg=None: ["Dynamic Lighting is on"])
    procs.names = ["RazerAppEngine.exe"]
    api = make_api(appmod, FakeService())
    api._kb = hc.Keyboard(FakeTransport(), model=V3PRO)
    d = api.model()["data"]
    assert "Razer Synapse" in d["blocked"] and d["locked"] is True and d["notices"] == ["Dynamic Lighting is on"]


def test_the_mac_window_gets_no_guard_fields(tmp_path, monkeypatch):
    from test_models_wiring import FakeService, make_api
    import app as appmod
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(appmod, "STATE_FILE", str(tmp_path / "state.json"))
    api = make_api(appmod, FakeService())
    api._kb = hc.Keyboard(FakeTransport(), model=V3PRO)
    d = api.model()["data"]
    assert "blocked" not in d and "notices" not in d


# ---------- Dynamic Lighting ----------

class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 0x20019

    def __init__(self, value=None):
        self.value = value

    def OpenKey(self, root, path, reserved=0, access=0x20019):
        assert root == "HKCU" and path == r"Software\Microsoft\Lighting"
        if self.value is None:
            raise FileNotFoundError(path)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def QueryValueEx(self, key, name):
        assert name == "AmbientLightingEnabled"
        if self.value == "missing":
            raise FileNotFoundError(name)
        return self.value, 4


def test_dynamic_lighting_on_is_read_from_the_registry():
    assert wg.dynamic_lighting_on(FakeWinreg(1)) is True
    assert wg.dynamic_lighting_on(FakeWinreg(0)) is False
    assert wg.dynamic_lighting_on(FakeWinreg("missing")) is False
    assert wg.dynamic_lighting_on(FakeWinreg(None)) is False   # older Windows: no Lighting key


def test_the_notice_says_how_to_turn_it_off_and_nothing_is_written():
    reg = FakeWinreg(1)
    (msg,) = wg.notices(reg)
    assert "Dynamic Lighting" in msg and "Settings" in msg and "Personalization" in msg
    assert not hasattr(reg, "SetValueEx")
    assert wg.notices(FakeWinreg(0)) == []
