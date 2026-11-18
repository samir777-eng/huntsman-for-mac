# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Effect registry, parameter validation and every renderer (pure: no device, no clock)."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lighting import effects as fx  # noqa: E402
from lighting.frame import AudioState, KeyEvent, Keymap  # noqa: E402

EXPECTED = {
    "solid", "gradient", "rainbow", "colour_cycle", "breathing", "aurora", "matrix", "plasma", "fire",
    "starfield", "audio_spectrum", "audio_pulse", "heatmap", "reactive_ripple", "reactive_afterglow",
    "reactive_explosion", "reactive_trail",
}
KM = Keymap.load()
W, A, S, D = (KM.by_name(n).id for n in "WASD")
AUDIO = AudioState(level=0.6, bands=[i / 15 for i in range(16)])


def ctx(name, keys=None, params=None, events=(), audio=AUDIO, heat=None):
    p = fx.validate_params(name, params or {})
    return fx.RenderContext(keymap=KM, keys=list(KM.ids if keys is None else keys), params=p,
                            audio=audio, events=list(events), heat=dict(heat or {}))


def render(name, t, **kw):
    params = kw.pop("params", None)
    return fx.create(name, params or {}).render(t, ctx(name, params=params, **kw))


def test_registry_has_every_effect_with_specs():
    assert set(fx.REGISTRY) == EXPECTED
    for name, spec in fx.REGISTRY.items():
        assert spec.name == name and spec.label and spec.category in {"basic", "ambient", "audio", "reactive"}
        assert spec.needs <= {"keys", "audio", "time"}
        for p in spec.params:
            assert p.kind in {"color", "colors", "float", "int", "choice", "bool"}
        fx.validate_params(name, {})  # defaults are valid


def test_needs_flags():
    assert "audio" in fx.REGISTRY["audio_spectrum"].needs and "audio" in fx.REGISTRY["audio_pulse"].needs
    for n in ("reactive_ripple", "reactive_afterglow", "reactive_explosion", "reactive_trail", "heatmap"):
        assert "keys" in fx.REGISTRY[n].needs


@pytest.mark.parametrize("name", sorted(EXPECTED))
@pytest.mark.parametrize("t", [0.0, 1.37, 12345.6])
def test_renderers_cover_only_requested_keys_with_valid_rgb(name, t):
    keys = [W, A, S, D, KM.by_name("ESC").id, KM.by_name("NUMPAD_0").id]
    ev = [KeyEvent(W, True, t - 0.1)]
    out = render(name, t, keys=keys, events=ev, heat={W: 5, A: 1})
    assert set(out) <= set(keys)
    for rgb in out.values():
        assert len(rgb) == 3 and all(isinstance(c, int) and 0 <= c <= 255 for c in rgb)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_renderers_are_deterministic(name):
    ev = [KeyEvent(W, True, 9.8), KeyEvent(D, True, 9.9)]
    a = render(name, 10.0, events=ev, heat={W: 3})
    b = render(name, 10.0, events=ev, heat={W: 3})
    assert a == b


@pytest.mark.parametrize("name", ["rainbow", "aurora", "plasma", "fire", "matrix", "starfield", "colour_cycle"])
def test_animated_effects_change_over_time(name):
    assert render(name, 1.0) != render(name, 1.7)


def test_seed_changes_random_effects():
    for name in ("matrix", "starfield"):
        assert render(name, 3.0, params={"seed": 1}) != render(name, 3.0, params={"seed": 2})


def test_solid_and_gradient():
    assert set(render("solid", 0, params={"color": [10, 20, 30]}).values()) == {(10, 20, 30)}
    g = render("gradient", 0, params={"colors": [[255, 0, 0], [0, 0, 255]], "angle": 0})
    esc, num = g[KM.by_name("ESC").id], g[KM.by_name("NUMPAD_PLUS").id]
    assert esc[0] > esc[2] and num[2] > num[0]  # left is red, right is blue
    r = render("gradient", 0, params={"colors": [[255, 255, 255], [0, 0, 0]], "mode": "radial"})
    centre = min(KM.ids, key=lambda k: (KM.center(k)[0] - 11.25) ** 2 + (KM.center(k)[1] - 3.125) ** 2)
    assert sum(r[centre]) > sum(r[KM.by_name("ESC").id])


def test_breathing_fades_to_black_and_peaks():
    p = {"colors": [[200, 0, 0]], "period": 4}
    assert set(render("breathing", 0, params=p).values()) == {(0, 0, 0)}
    assert set(render("breathing", 2, params=p).values()) == {(200, 0, 0)}


def test_audio_spectrum_lights_from_the_bottom():
    loud = AudioState(level=1, bands=[1.0] * 16)
    quiet = AudioState(level=0, bands=[0.0] * 16)
    half = AudioState(level=0.5, bands=[0.5] * 16)
    assert all(c == (0, 0, 0) for c in render("audio_spectrum", 0, audio=quiet).values())
    assert all(c != (0, 0, 0) for c in render("audio_spectrum", 0, audio=loud).values())
    h = render("audio_spectrum", 0, audio=half)
    assert h[KM.by_name("SPACEBAR").id] != (0, 0, 0) and h[KM.by_name("F5").id] == (0, 0, 0)
    assert all(c == (0, 0, 0) for c in render("audio_spectrum", 0, audio=None).values())


def test_audio_spectrum_mirror_puts_bass_in_the_middle():
    bass = AudioState(level=1, bands=[1.0] + [0.0] * 15)
    plain = render("audio_spectrum", 0, audio=bass, params={"mirror": False})
    mirror = render("audio_spectrum", 0, audio=bass, params={"mirror": True})
    lctrl = KM.by_name("LEFT_CTRL").id
    mid = min((k.id for k in KM.keys if k.row == 5), key=lambda k: abs(KM.center(k)[0] - KM.bounds[0] / 2))
    assert plain[lctrl] != (0, 0, 0) and plain[mid] == (0, 0, 0)
    assert mirror[mid] != (0, 0, 0) and mirror[lctrl] == (0, 0, 0)


def test_audio_pulse_follows_level():
    p = {"colors": [[255, 255, 255]], "sensitivity": 1}
    lo = render("audio_pulse", 0, params=p, audio=AudioState(0.1, [0] * 16))
    hi = render("audio_pulse", 0, params=p, audio=AudioState(0.9, [0] * 16))
    assert sum(hi[W]) > sum(lo[W])


def test_heatmap_normalises_counts():
    p = {"colors": [[0, 0, 255], [255, 0, 0]]}
    h = render("heatmap", 0, params=p, heat={W: 10, A: 5})
    assert h[W] == (255, 0, 0) and h[S] == (0, 0, 255) and h[A] == (128, 0, 128)
    assert set(render("heatmap", 0, params=p, heat={}).values()) == {(0, 0, 255)}


def test_afterglow_fades_after_a_press():
    p = {"color": [255, 255, 255], "fade": 1.0}
    r = fx.create("reactive_afterglow", p)
    c = ctx("reactive_afterglow", params=p, events=[KeyEvent(W, True, 10.0)])
    first = r.render(10.0, c)
    assert first[W] == (255, 255, 255) and first[A] == (0, 0, 0)
    c2 = ctx("reactive_afterglow", params=p)  # the event is remembered without being passed again
    assert 0 < sum(r.render(10.5, c2)[W]) < 765
    assert r.render(11.1, c2)[W] == (0, 0, 0)


def test_reactive_renderers_prune_old_events():
    for name in ("reactive_ripple", "reactive_afterglow", "reactive_explosion", "reactive_trail"):
        r = fx.create(name, {})
        r.render(0.0, ctx(name, events=[KeyEvent(W, True, 0.0)]))
        r.render(100.0, ctx(name))
        assert r.active == []
        # the same event passed twice counts once
        r.render(1.0, ctx(name, events=[KeyEvent(W, True, 1.0), KeyEvent(W, True, 1.0), KeyEvent(W, False, 1.05)]))
        assert len(r.active) == 1


def test_ripple_expands_outward():
    p = {"speed": 10, "width": 1, "fade": 2, "colors": [[255, 255, 255]]}
    r = fx.create("reactive_ripple", p)
    ev = [KeyEvent(S, True, 0.0)]
    near = r.render(0.1, ctx("reactive_ripple", params=p, events=ev))  # radius 1: neighbours lit
    far_key = min(KM.ids, key=lambda k: abs(math.dist(KM.center(k), KM.center(S)) - 15))
    assert sum(near[W]) > 0 and near[far_key] == (0, 0, 0)
    late = r.render(1.5, ctx("reactive_ripple", params=p))  # radius 15
    assert sum(late[far_key]) > 0 and late[S] == (0, 0, 0)


def test_explosion_centre_brightest():
    p = {"radius": 4, "fade": 1, "colors": [[255, 255, 255]]}
    out = render("reactive_explosion", 0.2, params=p, events=[KeyEvent(S, True, 0.0)])
    assert sum(out[S]) >= sum(out[W]) > 0 and out[KM.by_name("ESC").id] == (0, 0, 0)


def test_trail_stays_on_the_key_row():
    p = {"color": [255, 0, 0], "length": 6, "fade": 1}
    out = render("reactive_trail", 0.3, params=p, events=[KeyEvent(S, True, 0.0)])
    lit = {k for k, c in out.items() if c != (0, 0, 0)}
    assert lit and all(KM.key(k).row == KM.key(S).row for k in lit)


@pytest.mark.parametrize("name,params", [
    ("nope", {}),
    ("solid", {"colour": [1, 2, 3]}),             # unknown param
    ("solid", {"color": [1, 2]}),
    ("solid", {"color": [1, 2, 300]}),
    ("solid", {"color": "red"}),
    ("gradient", {"colors": [[1, 2, 3]]}),        # fewer than 2 stops
    ("gradient", {"colors": [[1, 2, 3]] * 6}),    # more than 5 stops
    ("gradient", {"mode": "spiral"}),
    ("rainbow", {"speed": 99}),
    ("rainbow", {"speed": "fast"}),
    ("rainbow", {"speed": True}),
    ("matrix", {"seed": 1.5}),
    ("audio_spectrum", {"mirror": 1}),
])
def test_bad_params_are_rejected(name, params):
    with pytest.raises(ValueError):
        fx.validate_params(name, params)
    with pytest.raises(ValueError):
        fx.create(name, params)


def test_validate_params_fills_defaults_and_normalises():
    p = fx.validate_params("rainbow", {"speed": 2})
    assert p["speed"] == 2.0 and set(p) == {s.name for s in fx.REGISTRY["rainbow"].params}
    assert fx.validate_params("solid", {"color": (1, 2, 3)})["color"] == (1, 2, 3)
    assert fx.validate_params("rainbow", {"colors": [[1, 2, 3], [4, 5, 6]]})["colors"] == [(1, 2, 3), (4, 5, 6)]


# ---------- smaller layouts: the row count comes from the keymap (the V3 Pro Mini has 5 LED rows) ----------

def _mini():
    import huntsman_core as hc
    import models
    return Keymap(hc.load_layout(models.MODELS[0x02B0]))


def test_keymap_knows_its_row_count():
    assert KM.rows == 6 and _mini().rows == 5


def test_audio_spectrum_fills_all_five_rows_of_the_mini():
    km = _mini()
    bottom = [k.id for k in km.keys if k.row == 4]
    top = [k.id for k in km.keys if k.row == 0]

    def spectrum(level):
        c = fx.RenderContext(keymap=km, keys=km.ids, params={}, audio=AudioState(level=level, bands=[level] * 16))
        return fx.create("audio_spectrum").render(0, c)
    quiet = spectrum(0.19)   # just under a fifth: the bottom row only, almost fully lit
    assert all(quiet[k] != (0, 0, 0) for k in bottom) and all(quiet[k] == (0, 0, 0) for k in top)
    loud = spectrum(1.0)     # every row of the Mini lit, the top in the palette's last colour
    assert all(loud[k] != (0, 0, 0) for k in km.ids)
    palette = fx.REGISTRY["audio_spectrum"].params[0].default
    assert loud[top[0]] == tuple(palette[-1]) and loud[bottom[0]] == tuple(palette[0])
    assert max(quiet[bottom[0]]) >= 0.9 * max(loud[bottom[0]])


def test_fire_is_hottest_on_the_bottom_row_of_the_mini(monkeypatch):
    from lighting.effects import ambient
    monkeypatch.setattr(ambient, "noise1", lambda *a: 1.0)
    km = _mini()
    frame = fx.create("fire").render(0, fx.RenderContext(keymap=km, keys=km.ids, params={}))
    hottest = tuple(fx.REGISTRY["fire"].params[0].default[-1])
    assert all(frame[k.id] == hottest for k in km.keys if k.row == 4)
