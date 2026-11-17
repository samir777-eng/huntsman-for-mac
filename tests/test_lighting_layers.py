# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Layer composition: blends, opacity, key masks, order, enabled, brightness."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lighting import effects as fx  # noqa: E402
from lighting.frame import Keymap  # noqa: E402
from lighting.layers import BLENDS, Layer, blend, compose  # noqa: E402

KM = Keymap.load()
W, A = KM.by_name("W").id, KM.by_name("A").id
BASE = fx.RenderContext(keymap=KM, keys=KM.ids, params={}, audio=None, events=[], heat={})


def solid(rgb, **kw):
    kw.setdefault("id", "l")
    return Layer(effect="solid", params={"color": list(rgb)}, **kw)


@pytest.mark.parametrize("mode,dst,src,out", [
    ("normal", (10, 20, 30), (200, 100, 0), (200, 100, 0)),
    ("add", (200, 100, 0), (100, 100, 10), (255, 200, 10)),
    ("screen", (128, 0, 255), (128, 255, 0), (192, 255, 255)),
    ("multiply", (255, 128, 0), (128, 128, 255), (128, 64, 0)),
    ("max", (10, 200, 30), (100, 100, 100), (100, 200, 100)),
])
def test_blend_math(mode, dst, src, out):
    assert blend(dst, src, mode) == out


def test_blends_listed():
    assert BLENDS == ("normal", "add", "screen", "multiply", "max")


def test_empty_stack_is_black_on_every_key():
    assert compose([], 0, BASE) == {k: (0, 0, 0) for k in KM.ids}


def test_layers_compose_bottom_to_top():
    f = compose([solid((255, 0, 0), id="a"), solid((0, 0, 255), id="b")], 0, BASE)
    assert set(f.values()) == {(0, 0, 255)}


def test_opacity_mixes_with_below():
    f = compose([solid((0, 0, 0), id="a"), solid((200, 100, 50), id="b", opacity=0.5)], 0, BASE)
    assert f[W] == (100, 50, 25)


def test_key_mask_limits_a_layer():
    f = compose([solid((10, 10, 10), id="a"), solid((255, 0, 0), id="b", keys=[W, 99999])], 0, BASE)
    assert f[W] == (255, 0, 0) and f[A] == (10, 10, 10) and 99999 not in f


def test_disabled_layer_is_skipped():
    f = compose([solid((10, 10, 10), id="a"), solid((255, 0, 0), id="b", enabled=False)], 0, BASE)
    assert f[W] == (10, 10, 10)


def test_blend_modes_apply_in_compose():
    f = compose([solid((100, 100, 100), id="a"), solid((100, 0, 200), id="b", blend="add")], 0, BASE)
    assert f[W] == (200, 100, 255)


def test_brightness_scales_the_result():
    f = compose([solid((200, 100, 50))], 0, BASE, brightness=0.5)
    assert f[W] == (100, 50, 25)
    assert compose([solid((200, 100, 50))], 0, BASE, brightness=0)[W] == (0, 0, 0)


def test_layer_keeps_its_renderer_between_frames_and_rebuilds_on_param_change():
    from lighting.frame import KeyEvent
    layer = Layer(id="r", effect="reactive_afterglow", params={"color": [255, 255, 255], "fade": 1})
    ctx = fx.RenderContext(keymap=KM, keys=KM.ids, params={}, audio=None, events=[KeyEvent(W, True, 0.0)], heat={})
    compose([layer], 0.0, ctx)
    assert compose([layer], 0.5, BASE)[W] != (0, 0, 0)  # remembered the press
    layer.params["color"] = [255, 0, 0]
    assert compose([layer], 0.5, BASE)[W] == (0, 0, 0)  # new params: fresh renderer


@pytest.mark.parametrize("kw", [
    {"blend": "overlay"}, {"opacity": 1.5}, {"opacity": -0.1}, {"keys": "some"}, {"keys": [1.5]},
    {"enabled": "yes"}, {"effect": "nope"}, {"params": {"bogus": 1}},
])
def test_layer_validation(kw):
    args = {"id": "x", "effect": "solid", "params": {}}
    args.update(kw)
    with pytest.raises(ValueError):
        Layer(**args).validate()


def test_layer_dict_round_trip():
    layer = Layer(id="x", effect="rainbow", params={"speed": 2}, keys=[W, A], blend="screen", opacity=0.4, enabled=False)
    again = Layer.from_dict(layer.to_dict())
    assert again.to_dict() == layer.to_dict()
    assert again.to_dict()["keys"] == [W, A] and again.blend == "screen"
