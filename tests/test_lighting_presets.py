# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Presets: JSON round-trip in data_dir (redirected to tmp_path), validation, built-ins."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import huntsman_core as hc  # noqa: E402
from lighting import effects as fx  # noqa: E402
from lighting import presets as pr  # noqa: E402
from lighting.frame import KeyEvent, Keymap  # noqa: E402
from lighting.layers import Layer, compose  # noqa: E402

KM = Keymap.load()


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    return tmp_path


def sample():
    return pr.Preset(name="Mine", brightness=0.8, layers=[
        Layer(id="a", effect="rainbow", params={"speed": 1.5}),
        Layer(id="b", effect="solid", params={"color": [1, 2, 3]}, keys=[18, 31], blend="add", opacity=0.5),
    ])


def test_missing_file_means_no_user_presets(tmp_data):
    assert pr.load_presets() == []
    assert pr.presets_path() == os.path.join(str(tmp_data), "presets.json")


def test_round_trip(tmp_data):
    pr.save_presets([sample()])
    again = pr.load_presets()
    assert [p.to_dict() for p in again] == [sample().to_dict()]
    assert sorted(os.listdir(tmp_data)) == ["presets.json"]  # no tmp file left behind
    with open(tmp_data / "presets.json") as f:
        assert json.load(f)["version"] == 1


def test_save_refuses_invalid_and_keeps_the_old_file(tmp_data):
    pr.save_presets([sample()])
    bad = sample()
    bad.layers[0].effect = "nope"
    with pytest.raises(ValueError):
        pr.save_presets([bad])
    assert [p.name for p in pr.load_presets()] == ["Mine"]


def test_save_refuses_duplicate_names():
    with pytest.raises(ValueError):
        pr.save_presets([sample(), sample()])


@pytest.mark.parametrize("data", [
    {"name": "", "brightness": 1, "layers": []},
    {"name": "x", "brightness": 2, "layers": []},
    {"name": "x", "brightness": 1, "layers": "no"},
    {"name": "x", "brightness": 1, "layers": [{"id": "a", "effect": "nope", "params": {}}]},
    {"name": "x", "brightness": 1, "layers": [{"id": "a", "effect": "solid", "params": {"color": [1, 2]}}]},
    {"name": "x", "brightness": 1, "layers": [{"id": "a", "effect": "rainbow", "params": {"speed": 1000}}]},
    {"name": "x", "brightness": 1, "layers": [{"id": "a", "effect": "solid", "params": {}, "blend": "burn"}]},
    {"name": "x", "brightness": 1, "layers": [{"id": "a", "effect": "solid", "params": {}},
                                               {"id": "a", "effect": "solid", "params": {}}]},
    "not a dict",
])
def test_from_dict_validation(data):
    with pytest.raises(ValueError):
        pr.Preset.from_dict(data)


def test_load_rejects_a_corrupt_file(tmp_data):
    (tmp_data / "presets.json").write_text("{not json")
    with pytest.raises(ValueError):
        pr.load_presets()
    (tmp_data / "presets.json").write_text(json.dumps({"version": 1, "presets": [{"name": "x"}]}))
    with pytest.raises(ValueError):
        pr.load_presets()


def test_builtins_are_valid_and_render():
    names = [p.name for p in pr.builtin_presets(KM)]
    for want in ("Rainbow wave", "Aurora", "Gaming WASD", "Typing glow", "Music", "Fire", "Matrix", "Calm breathing"):
        assert want in names
    assert len(set(names)) == len(names)
    base = fx.RenderContext(keymap=KM, keys=KM.ids, params={}, audio=None, events=[], heat={})
    for p in pr.builtin_presets(KM):
        p.validate()
        assert pr.Preset.from_dict(json.loads(json.dumps(p.to_dict()))).to_dict() == p.to_dict()
        f = compose(p.layers, 5.0, base, brightness=p.brightness)
        assert set(f) == set(KM.ids)


def test_gaming_wasd_highlights_wasd_and_ripples():
    p = next(p for p in pr.builtin_presets(KM) if p.name == "Gaming WASD")
    assert any(layer.effect == "reactive_ripple" for layer in p.layers)
    wasd = {KM.by_name(n).id for n in "WASD"}
    assert any(layer.keys != "all" and set(layer.keys) == wasd for layer in p.layers)
    base = fx.RenderContext(keymap=KM, keys=KM.ids, params={}, audio=None, events=[], heat={})
    f = compose(p.layers, 1.0, base)
    assert f[KM.by_name("W").id] != f[KM.by_name("Q").id]
    ev = fx.RenderContext(keymap=KM, keys=KM.ids, params={}, audio=None,
                          events=[KeyEvent(KM.by_name("G").id, True, 1.0)], heat={})
    assert compose(p.layers, 1.1, ev) != f
