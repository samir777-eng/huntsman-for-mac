"""app.py and huntsman.py against FakeTransport. Every test redirects the state files to tmp_path,
so the owner's real ~/Library/Application Support folder is never touched."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import huntsman_core as hc  # noqa: E402
from test_core import FakeTransport  # noqa: E402

FN = 59
REAL_KEYBOARD = hc.Keyboard


@pytest.fixture
def app(tmp_path, monkeypatch):
    import app as appmod
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(appmod, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(appmod, "SNAPSHOT_FILE", str(tmp_path / "first-launch-snapshot.json"))
    return appmod


@pytest.fixture
def fake(monkeypatch):
    """hc.Keyboard() builds a keyboard on one shared FakeTransport (never the USB device)."""
    t = FakeTransport()
    monkeypatch.setattr(hc, "Keyboard", lambda transport=None: REAL_KEYBOARD(transport or t))
    return t


def write_state(app, data):
    with open(app.STATE_FILE, "w") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


# ---------- state ----------

@pytest.mark.parametrize("raw", ["{not json", "[]", "null", '"text"'])
def test_corrupt_state_gives_defaults(app, raw):
    write_state(app, raw)
    assert app.load_state() == app.DEFAULT_STATE


def test_bad_fields_fall_back_one_by_one(app):
    write_state(app, {
        "rapid": {"enabled": "yes", "press": 9, "release": 0.5, "keys": [31, FN, "x"], "continuous": True},
        "snap": [31, FN],
        "effect": {"name": "nope"},
        "custom": {"base": [1, 2, 3], "keys": {"31": [4, 5, 6], "32": [999, 0, 0], "abc": [1, 1, 1]}},
        "ui": {"accent": "red", "accentMatch": True},
    })
    st = app.load_state()
    d = app.DEFAULT_STATE["rapid"]
    assert st["rapid"] == {"enabled": d["enabled"], "press": d["press"], "release": 0.5,
                           "keys": d["keys"], "continuous": True}
    assert st["snap"] is None and st["effect"] is None
    assert st["custom"] == {"base": [1, 2, 3], "keys": {"31": [4, 5, 6]}}
    assert st["ui"] == {"accentMatch": True}


def test_good_state_survives(app):
    good = {"rapid": {"enabled": True, "press": 0.4, "release": 0.6, "keys": [31, 32], "continuous": False},
            "snap": [31, 33], "effect": {"name": "static", "rgb1": [1, 2, 3]},
            "custom": None, "ui": {"accent": "#3ddc84", "accentMatch": False}}
    write_state(app, good)
    assert app.load_state() == good


def test_save_state_leaves_no_tmp(app, tmp_path):
    app.save_state(app.load_state())
    assert sorted(os.listdir(tmp_path)) in (["state.json"], ["state.json", "state.lock"])


def test_update_state_holds_the_file_lock(app, tmp_path):
    import fcntl
    with app.update_state() as st:
        st["snap"] = [31, 33]
        with open(tmp_path / "state.lock", "a") as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert app.load_state()["snap"] == [31, 33]


# ---------- first-launch snapshot ----------

def test_snapshot_written_once_and_never_overwritten(app, fake):
    kb = hc.Keyboard()
    app.ensure_snapshot(kb)
    first = open(app.SNAPSHOT_FILE).read()
    kb.set_actuation([31], 3.0)
    app.ensure_snapshot(kb)
    assert open(app.SNAPSHOT_FILE).read() == first
    assert json.loads(first)["profiles"]["0"]["31"] == "00 1f 00 4c 46 02 02 00 04".replace(" ", "")


def test_snapshot_failure_leaves_no_file(app, fake, monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(app.json, "dump", boom)
    with pytest.raises(OSError):
        app.ensure_snapshot(hc.Keyboard())
    assert not any(n.startswith("first-launch") for n in os.listdir(tmp_path))


def test_snapshot_records_refused_keys(app, fake, monkeypatch):
    fake.refuse = lambda r: (r[6], r[7]) == (2, 0x92) and r[9] == 40
    app.ensure_snapshot(hc.Keyboard())
    snap = json.load(open(app.SNAPSHOT_FILE))
    assert [0, 40] in snap["skipped"] and "40" not in snap["profiles"]["0"]


# ---------- connecting ----------

def test_connect_survives_bad_state_and_refusals(app, fake):
    write_state(app, {"custom": {"base": [0, 0, 0], "keys": {"31": [1, 2, 3]}},
                      "rapid": {"enabled": True}, "snap": [31, 33]})
    fake.refuse = lambda r: (r[6], r[7]) in ((0x0F, 0x03), (0x02, 0x1A)) or ((r[6], r[7]) == (2, 0x92) and r[9] == 40)
    api = app.Api()
    assert api.startup()["ok"] is True
    assert api.reapplied == ["Snap Tap"]  # the refused items are logged, the rest still goes out
    assert os.path.exists(app.SNAPSHOT_FILE)


def test_connect_switches_a_stuck_keyboard_back_to_typing(app, fake):
    fake.mode = 3  # left in driver mode by a crash during a key test
    assert app.Api().startup()["ok"] is True
    assert fake.mode == 0


def test_cli_switches_a_stuck_keyboard_back_to_typing(app, fake):
    import huntsman
    fake.mode = 3
    huntsman.main(["apply-saved"])
    assert fake.mode == 0


# ---------- input validation ----------

def test_set_depth_rejects_fn_and_unknown_ids(app, fake):
    api = app.Api()
    api.startup()
    fake.sent.clear()
    for keys in ([FN], [31, FN], [9999], ["x"]):
        r = api.set_depth(keys, 2.0)
        assert r["ok"] is False
    assert fake.writes() == []
    assert api._kb is not None  # bad input doesn't drop the connection


def test_set_depth_empty_means_every_key_but_fn(app, fake):
    api = app.Api()
    r = api.set_depth([], 2.0)
    assert r["ok"] is True and r["data"]["count"] == len(hc.all_key_ids())
    written = {r[9] for r in fake.writes()}
    assert written == set(hc.all_key_ids()) and FN not in written


def test_cli_depth_rejects_fn(app, fake):
    import huntsman
    with pytest.raises(ValueError):
        huntsman.main(["depth", "2.0", "FN"])
    assert fake.writes() == []


@pytest.mark.parametrize("base,keys", [
    ([0, 0], {}), ([0, 0, 256], {}), ([0, 0, 0], {"31": [1, 2]}), ([0, 0, 0], {"31": [1, 2, -1]}),
    ([0, 0, 0], {"31": [1.5, 2, 3]}), ([0, 0, 0], {"31": [True, 2, 3]}), ([0, 0, 0], {"9999": [1, 2, 3]}),
    ([0, 0, 0], {"x": [1, 2, 3]}),
])
def test_set_custom_rejects_bad_input(app, fake, base, keys):
    api = app.Api()
    api.startup()
    fake.sent.clear()
    assert api.set_custom(base, keys)["ok"] is False
    assert fake.writes(0x0F, 0x03) == [] and app.load_state()["custom"] is None


def test_set_custom_accepts_every_lit_key(app, fake):
    api = app.Api()
    r = api.set_custom([0, 0, 0], {"31": [1, 2, 3], str(FN): [4, 5, 6]})  # Fn has an LED of its own
    assert r["ok"] is True and app.load_state()["custom"]["keys"] == {"31": [1, 2, 3], str(FN): [4, 5, 6]}


@pytest.mark.parametrize("prefs", [{"accent": "red"}, {"accent": "#12345"}, {"accent": "#1234567"},
                                   {"accent": "javascript:x"}, {"accentMatch": "yes"}])
def test_set_prefs_rejects_bad_input(app, prefs):
    assert app.Api().set_prefs(prefs)["ok"] is False
    assert app.load_state()["ui"] == {}


def test_set_prefs_saves_good_input(app):
    assert app.Api().set_prefs({"accent": "#3DDC84", "accentMatch": True, "junk": 1})["ok"] is True
    assert app.load_state()["ui"] == {"accent": "#3DDC84", "accentMatch": True}


# ---------- writes ----------

def test_rapid_apply_all_excludes_fn(app, fake):
    app.rapid_apply(hc.Keyboard(), {"enabled": True, "press": 0.3, "release": 0.3, "keys": "all"})
    on = set()
    for r in fake.writes(0x02, 0x1A):
        body = r[10:8 + r[5]]
        for i in range(0, len(body), 6):
            if body[i] != 0xFF and body[i + 1] == 1:
                on.add(body[i])
    assert on == set(hc.all_key_ids()) and FN not in on


def test_restore_factory_failure_still_clears_state(app, fake):
    write_state(app, {"rapid": {"enabled": True, "press": 0.3, "release": 0.3, "keys": "all", "continuous": True},
                      "snap": [31, 33]})
    fake.refuse = lambda r: (r[6], r[7]) == (0x02, 0x1A)
    with pytest.raises(hc.DeviceError):
        app.restore_factory(hc.Keyboard())
    st = app.load_state()
    assert st["rapid"] == app.DEFAULT_STATE["rapid"] and st["snap"] is None
    assert fake.writes(0x02, 0x21)  # the later steps were still tried


def test_brightness_drag_is_live_only_and_release_saves(app, fake):
    api = app.Api()
    api.set_brightness(40)
    api.save_brightness(40)
    assert [r[8] for r in fake.writes(0x0F, 0x04)] == [0, 1]


# ---------- key tester vs reconnect ----------

class _Test:
    def __init__(self):
        self.running, self.stops = True, 0

    def stop(self, reason=None):
        self.stops += 1
        self.running = False
        return True


def test_reconnect_stops_a_running_test_before_closing(app, fake):
    api = app.Api()
    api.startup()
    order = []
    api._test = _Test()
    orig_stop = api._test.stop
    api._test.stop = lambda reason=None: (order.append("stop"), orig_stop())[1]
    fake.close = lambda: order.append("close")
    api.reconnect()
    assert order[:2] == ["stop", "close"]


def test_device_failure_stops_a_running_test_before_dropping(app, fake):
    api = app.Api()
    api.startup()
    api._test = test = _Test()

    def boom(kb):
        raise OSError("unplugged")
    assert api._run(boom)["ok"] is False
    assert test.stops == 1 and api._kb is None


def test_set_rapid_rejects_fn_in_key_list(app, fake):
    api = app.Api()
    api.startup()
    fake.sent.clear()
    r = api.set_rapid({"enabled": True, "press": 0.3, "release": 0.3, "keys": [31, FN], "continuous": False})
    assert r["ok"] is False and fake.writes(0x02, 0x1A) == [] and app.load_state()["rapid"]["enabled"] is False
