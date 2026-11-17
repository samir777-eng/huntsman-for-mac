# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Layer stacks: each layer renders one effect on a set of keys and blends onto the layers below.

Blending is plain 8-bit sRGB arithmetic (no linear-light conversion); gamma is applied later, once,
when the engine sends the frame.
"""
import json
from dataclasses import dataclass, field

from lighting import effects as fx
from lighting.frame import BLACK, Frame, clamp8

BLENDS = ("normal", "add", "screen", "multiply", "max")


def blend(dst, src, mode):
    if mode == "normal":
        return tuple(src)
    if mode == "add":
        return tuple(min(255, d + s) for d, s in zip(dst, src))
    if mode == "screen":
        return tuple(clamp8(255 - (255 - d) * (255 - s) / 255) for d, s in zip(dst, src))
    if mode == "multiply":
        return tuple(clamp8(d * s / 255) for d, s in zip(dst, src))
    if mode == "max":
        return tuple(max(d, s) for d, s in zip(dst, src))
    raise ValueError(f"unknown blend {mode!r}")


@dataclass
class Layer:
    """keys: "all" or a list of key ids. params may be partial (defaults fill the rest).
    The layer keeps its renderer between frames (reactions remember presses); changing effect or
    params gives it a fresh one."""
    id: str
    effect: str
    params: dict = field(default_factory=dict)
    keys: str | list[int] = "all"
    blend: str = "normal"
    opacity: float = 1.0
    enabled: bool = True
    _renderer: object = field(default=None, init=False, repr=False, compare=False)
    _renderer_key: str = field(default="", init=False, repr=False, compare=False)

    def validate(self):
        """Raise ValueError unless every field is valid; returns the validated effect params."""
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("layer id must be a non-empty string")
        if self.effect not in fx.REGISTRY:
            raise ValueError(f"unknown effect {self.effect!r}")
        params = fx.validate_params(self.effect, self.params)
        if self.keys != "all" and (not isinstance(self.keys, list) or not all(
                isinstance(k, int) and not isinstance(k, bool) for k in self.keys)):
            raise ValueError('layer keys must be "all" or a list of key ids')
        if self.blend not in BLENDS:
            raise ValueError(f"blend must be one of {', '.join(BLENDS)}")
        if (not isinstance(self.opacity, (int, float)) or isinstance(self.opacity, bool)
                or not 0 <= self.opacity <= 1):
            raise ValueError("opacity must be 0-1")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be true or false")
        return params

    def renderer(self):
        params = fx.validate_params(self.effect, self.params)
        key = json.dumps([self.effect, params], sort_keys=True, default=list)
        if self._renderer is None or key != self._renderer_key:
            self._renderer, self._renderer_key = fx.REGISTRY[self.effect].renderer(params), key
        return self._renderer

    def to_dict(self):
        return {"id": self.id, "effect": self.effect, "params": json.loads(json.dumps(self.params, default=list)),
                "keys": self.keys if self.keys == "all" else list(self.keys), "blend": self.blend,
                "opacity": self.opacity, "enabled": self.enabled}

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict):
            raise ValueError("a layer must be an object")
        unknown = set(d) - {"id", "effect", "params", "keys", "blend", "opacity", "enabled"}
        if unknown:
            raise ValueError(f"unknown layer field(s) {', '.join(sorted(unknown))}")
        try:
            layer = cls(id=d["id"], effect=d["effect"], params=dict(d.get("params", {})),
                        keys=d.get("keys", "all"), blend=d.get("blend", "normal"),
                        opacity=d.get("opacity", 1.0), enabled=d.get("enabled", True))
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"layer is missing or has a bad field: {e}") from e
        layer.validate()
        return layer


def compose(layers, t, ctx_base, brightness=1.0) -> Frame:
    """Render enabled layers bottom to top over black for every key in ctx_base.keys, then scale by brightness.
    ctx_base supplies keymap, keys, audio, events and heat; each layer gets its own keys and params."""
    km = ctx_base.keymap
    all_keys = [k for k in ctx_base.keys if k in km]
    out = {k: BLACK for k in all_keys}
    for layer in layers:
        if not layer.enabled:
            continue
        renderer = layer.renderer()
        keys = all_keys if layer.keys == "all" else [k for k in layer.keys if k in out]
        ctx = fx.RenderContext(keymap=km, keys=keys, params=renderer.params, audio=ctx_base.audio,
                               events=ctx_base.events, heat=ctx_base.heat)
        src = renderer.render(t, ctx)
        a = float(layer.opacity)
        for k in keys:
            if k not in src:
                continue
            d = out[k]
            b = blend(d, src[k], layer.blend)
            out[k] = b if a >= 1 else tuple(clamp8(dv + (bv - dv) * a) for dv, bv in zip(d, b))
    if brightness < 1:
        f = max(0.0, brightness)
        out = {k: (clamp8(c[0] * f), clamp8(c[1] * f), clamp8(c[2] * f)) for k, c in out.items()}
    return out
