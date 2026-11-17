# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Effect specs, parameter validation, the registry and helpers shared by the renderers.

Renderers are deterministic: the same t, params and events give the same frame. Randomness comes from
rand(), an integer hash of (seed, ...) values, never from the random module.
"""
import math
from dataclasses import dataclass, field

from lighting.frame import AudioState, Frame, KeyEvent, Keymap, smoothstep

KINDS = {"color", "colors", "float", "int", "choice", "bool"}
CATEGORIES = {"basic", "ambient", "audio", "reactive"}
NEEDS = {"keys", "audio", "time"}


@dataclass(frozen=True)
class ParamSpec:
    """kind "colors": min/max bound the number of colours. "float"/"int": value range. "choice": choices."""
    name: str
    label: str
    kind: str
    default: object
    min: float | None = None
    max: float | None = None
    choices: tuple | None = None


@dataclass(frozen=True)
class EffectSpec:
    name: str
    label: str
    category: str
    params: list[ParamSpec]
    needs: set[str]
    renderer: type = None  # the Renderer subclass; create() instantiates it with validated params


@dataclass
class RenderContext:
    keymap: Keymap
    keys: list[int]
    params: dict
    audio: AudioState | None = None
    events: list[KeyEvent] = field(default_factory=list)
    heat: dict[int, int] = field(default_factory=dict)


REGISTRY: dict[str, EffectSpec] = {}


def effect(name, label, category, params, needs=("time",)):
    """Class decorator: register a Renderer under name."""
    needs = set(needs)
    assert category in CATEGORIES and needs <= NEEDS and all(p.kind in KINDS for p in params)

    def deco(cls):
        REGISTRY[name] = EffectSpec(name, label, category, list(params), needs, cls)
        return cls
    return deco


# ---------- parameter validation ----------

def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _color(v, label):
    if (not isinstance(v, (list, tuple)) or len(v) != 3
            or not all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in v)):
        raise ValueError(f"{label}: colour must be three whole numbers 0-255")
    return tuple(v)


def check_param(spec: ParamSpec, v):
    """Validated, normalised value for one parameter, else ValueError."""
    label = spec.name
    if spec.kind == "color":
        return _color(v, label)
    if spec.kind == "colors":
        if not isinstance(v, (list, tuple)):
            raise ValueError(f"{label}: expected a list of colours")
        if not spec.min <= len(v) <= spec.max:
            raise ValueError(f"{label}: needs {spec.min}-{spec.max} colours")
        return [_color(c, label) for c in v]
    if spec.kind == "float":
        if not _is_num(v) or not spec.min <= v <= spec.max:
            raise ValueError(f"{label}: must be a number {spec.min}-{spec.max}")
        return float(v)
    if spec.kind == "int":
        if not isinstance(v, int) or isinstance(v, bool) or not spec.min <= v <= spec.max:
            raise ValueError(f"{label}: must be a whole number {spec.min}-{spec.max}")
        return v
    if spec.kind == "choice":
        if v not in spec.choices:
            raise ValueError(f"{label}: must be one of {', '.join(spec.choices)}")
        return v
    if spec.kind == "bool":
        if not isinstance(v, bool):
            raise ValueError(f"{label}: must be true or false")
        return v
    raise ValueError(f"{label}: unknown kind {spec.kind}")


def validate_params(name, params) -> dict:
    """Every parameter of effect `name`, defaults filled in; unknown effects or parameters raise ValueError."""
    if name not in REGISTRY:
        raise ValueError(f"unknown effect {name!r}")
    if not isinstance(params, dict):
        raise ValueError("effect parameters must be an object")
    specs = {p.name: p for p in REGISTRY[name].params}
    unknown = set(params) - set(specs)
    if unknown:
        raise ValueError(f"{name}: unknown parameter(s) {', '.join(sorted(map(str, unknown)))}")
    return {n: check_param(p, params.get(n, p.default)) for n, p in specs.items()}


def create(name, params=None):
    """A fresh renderer for effect `name` (params validated; missing ones take their defaults)."""
    p = validate_params(name, params or {})
    return REGISTRY[name].renderer(p)


# ---------- renderer base and helpers ----------

class Renderer:
    """Renders with the parameters it was created with (self.params); ctx gives keys, audio, events, heat."""

    def __init__(self, params):
        self.params = params

    def render(self, t: float, ctx: RenderContext) -> Frame:
        raise NotImplementedError


def keys_of(ctx):
    return [k for k in ctx.keys if k in ctx.keymap]


_MASK = (1 << 64) - 1


def rand(*values) -> float:
    """Deterministic pseudo-random float in [0, 1) from integers (splitmix64-style mixing)."""
    h = 0x9E3779B97F4A7C15
    for v in values:
        h = (h ^ (int(v) & _MASK)) & _MASK
        h = (h * 0xBF58476D1CE4E5B9) & _MASK
        h ^= h >> 31
        h = (h * 0x94D049BB133111EB) & _MASK
        h ^= h >> 29
    return (h >> 11) / float(1 << 53)


def noise1(seed, lane, x) -> float:
    """Smooth 1-D value noise in [0, 1): one independent curve per (seed, lane)."""
    i = math.floor(x)
    a, b = rand(seed, lane, i), rand(seed, lane, i + 1)
    return a + (b - a) * smoothstep(x - i)


def projection(ctx, angle_deg):
    """Per-key position 0..1 along a direction (0 deg = left to right, 90 = top to bottom)."""
    a = math.radians(angle_deg)
    dx, dy = math.cos(a), math.sin(a)
    w, h = ctx.keymap.bounds
    corners = [x * dx + y * dy for x in (0, w) for y in (0, h)]
    lo, hi = min(corners), max(corners)
    span = (hi - lo) or 1.0
    out = {}
    for k in keys_of(ctx):
        cx, cy = ctx.keymap.center(k)
        out[k] = (cx * dx + cy * dy - lo) / span
    return out
