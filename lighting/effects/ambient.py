# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Ambient effects: aurora, matrix rain, plasma, fire, starfield."""
import math

from lighting.effects.base import ParamSpec, Renderer, effect, keys_of, noise1, rand
from lighting.frame import PALETTES, WHITE, lerp, sample, scale, smoothstep

SEED = ParamSpec("seed", "Pattern seed", "int", 1, 0, 2**31 - 1)
ROWS = 6


@effect("aurora", "Aurora", "ambient", [
    ParamSpec("colors", "Palette", "colors", PALETTES["aurora"], 2, 8),
    ParamSpec("speed", "Speed", "float", 0.5, 0.05, 5),
    ParamSpec("scale", "Band size", "float", 1.0, 0.2, 5),
])
class Aurora(Renderer):
    """Slow flowing bands: two interfering sine fields warped by each other."""

    def render(self, t, ctx):
        p = self.params
        w, h = ctx.keymap.bounds
        s = t * p["speed"]
        out = {}
        for k in keys_of(ctx):
            cx, cy = ctx.keymap.center(k)
            u, v = cx / w, cy / h
            band = 0.5 + 0.5 * math.sin(u * 6 * p["scale"] + s * 1.3 + 2.0 * math.sin(v * 3 + s * 0.7))
            drift = 0.5 + 0.5 * math.sin(u * 3.1 * p["scale"] - s * 0.9 + v * 4)
            colour = sample(p["colors"], u * 0.5 * p["scale"] + s * 0.1 + drift * 0.3, loop=True)
            out[k] = scale(colour, 0.15 + 0.85 * smoothstep(band * (0.6 + 0.6 * drift)))
        return out


@effect("matrix", "Matrix rain", "ambient", [
    ParamSpec("color", "Colour", "color", (0, 255, 70)),
    ParamSpec("density", "Density", "float", 0.5, 0.05, 1),
    ParamSpec("speed", "Speed (rows per second)", "float", 8.0, 1, 30),
    SEED,
])
class Matrix(Renderer):
    """Drops fall down each LED column; each pass a column rains with probability `density`."""
    TAIL = 3
    PERIOD = ROWS + TAIL + 4

    def render(self, t, ctx):
        p = self.params
        seed, colour = p["seed"], p["color"]
        out = {}
        for k in keys_of(ctx):
            key = ctx.keymap.key(k)
            col = key.led[1]
            speed = p["speed"] * (0.7 + 0.6 * rand(seed, col, 1))
            pos = t * speed + rand(seed, col, 0) * self.PERIOD
            cycle = math.floor(pos / self.PERIOD)
            head = pos - cycle * self.PERIOD - 1
            d = head - key.row
            if rand(seed, col, cycle, 2) >= p["density"] or not 0 <= d < self.TAIL:
                out[k] = (0, 0, 0)
                continue
            c = lerp(colour, WHITE, 0.6) if d < 1 else colour
            out[k] = scale(c, 1 - d / self.TAIL)
        return out


@effect("plasma", "Plasma", "ambient", [
    ParamSpec("colors", "Palette", "colors", PALETTES["synthwave"], 2, 8),
    ParamSpec("speed", "Speed", "float", 1.0, 0.05, 5),
    ParamSpec("scale", "Pattern size", "float", 1.0, 0.2, 5),
])
class Plasma(Renderer):
    def render(self, t, ctx):
        p = self.params
        s = t * p["speed"]
        out = {}
        for k in keys_of(ctx):
            cx, cy = ctx.keymap.center(k)
            x, y = cx * 0.5 * p["scale"], cy * 0.5 * p["scale"]
            v = (math.sin(x + s) + math.sin(y * 1.3 + s * 1.1) + math.sin((x + y) * 0.7 + s * 0.7)
                 + math.sin(math.hypot(x - 5, y - 1.5) + s * 1.5))
            out[k] = sample(p["colors"], (v + 4) / 8 + s * 0.05, loop=True)
        return out


@effect("fire", "Fire", "ambient", [
    ParamSpec("colors", "Palette (cool to hot)", "colors", PALETTES["fire"], 2, 8),
    ParamSpec("intensity", "Intensity", "float", 0.8, 0.1, 1),
    ParamSpec("speed", "Flicker speed", "float", 1.0, 0.1, 5),
    SEED,
])
class Fire(Renderer):
    """Heat rises from the bottom row; flicker is noise that drifts upward over time."""

    def render(self, t, ctx):
        p = self.params
        out = {}
        for k in keys_of(ctx):
            key = ctx.keymap.key(k)
            depth = key.row / (ROWS - 1)  # 0 at the top row, 1 at the bottom
            flicker = noise1(p["seed"], key.led[1], t * p["speed"] * 3 + key.row * 0.8)
            heat = depth ** 1.6 * (0.55 + 0.6 * flicker) * p["intensity"] * 1.3
            heat = min(1.0, max(0.0, heat))
            out[k] = scale(sample(p["colors"], heat), smoothstep(heat * 1.6))
        return out


@effect("starfield", "Starfield", "ambient", [
    ParamSpec("color", "Colour", "color", (255, 255, 255)),
    ParamSpec("density", "Density", "float", 0.25, 0.01, 1),
    ParamSpec("speed", "Twinkle speed (per second)", "float", 1.0, 0.1, 5),
    SEED,
])
class Starfield(Renderer):
    def render(self, t, ctx):
        p = self.params
        out = {}
        for k in keys_of(ctx):
            phase = t * p["speed"] + rand(p["seed"], k, 0)
            cycle = math.floor(phase)
            lit = rand(p["seed"], k, cycle) < p["density"]
            out[k] = scale(p["color"], math.sin(math.pi * (phase - cycle))) if lit else (0, 0, 0)
        return out
