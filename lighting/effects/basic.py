# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Basic effects: solid, gradient, rainbow, colour cycle, breathing."""
import math

from lighting.effects.base import ParamSpec, Renderer, effect, keys_of, projection
from lighting.frame import PALETTES, dist, sample, scale

SPEED_HELP = "cycles per second"


@effect("solid", "Solid colour", "basic", [ParamSpec("color", "Colour", "color", (0, 200, 255))], needs=())
class Solid(Renderer):
    def render(self, t, ctx):
        c = self.params["color"]
        return {k: c for k in keys_of(ctx)}


@effect("gradient", "Gradient", "basic", [
    ParamSpec("colors", "Colours", "colors", [(255, 0, 80), (0, 120, 255)], 2, 5),
    ParamSpec("mode", "Shape", "choice", "linear", choices=("linear", "radial")),
    ParamSpec("angle", "Angle (degrees)", "float", 0.0, 0, 360),
    ParamSpec("speed", f"Scroll speed ({SPEED_HELP})", "float", 0.0, -5, 5),
])
class Gradient(Renderer):
    def render(self, t, ctx):
        p = self.params
        if p["mode"] == "radial":
            w, h = ctx.keymap.bounds
            mid, far = (w / 2, h / 2), dist((0, 0), (w / 2, h / 2)) or 1.0
            pos = {k: dist(ctx.keymap.center(k), mid) / far for k in keys_of(ctx)}
        else:
            pos = projection(ctx, p["angle"])
        if p["speed"]:
            return {k: sample(p["colors"], v - t * p["speed"], loop=True) for k, v in pos.items()}
        return {k: sample(p["colors"], v) for k, v in pos.items()}


@effect("rainbow", "Rainbow wave", "basic", [
    ParamSpec("colors", "Palette", "colors", PALETTES["rainbow"], 2, 8),
    ParamSpec("speed", f"Speed ({SPEED_HELP})", "float", 0.5, -5, 5),
    ParamSpec("angle", "Direction (degrees)", "float", 0.0, 0, 360),
    ParamSpec("scale", "Repeats across the keyboard", "float", 1.0, 0.1, 5),
])
class Rainbow(Renderer):
    def render(self, t, ctx):
        p = self.params
        return {k: sample(p["colors"], v * p["scale"] - t * p["speed"], loop=True)
                for k, v in projection(ctx, p["angle"]).items()}


@effect("colour_cycle", "Colour cycle", "basic", [
    ParamSpec("colors", "Palette", "colors", PALETTES["rainbow"], 2, 8),
    ParamSpec("speed", f"Speed ({SPEED_HELP})", "float", 0.1, 0.01, 5),
])
class ColourCycle(Renderer):
    def render(self, t, ctx):
        c = sample(self.params["colors"], t * self.params["speed"], loop=True)
        return {k: c for k in keys_of(ctx)}


@effect("breathing", "Breathing", "basic", [
    ParamSpec("colors", "Colours (one per breath)", "colors", [(0, 180, 255)], 1, 5),
    ParamSpec("period", "Breath length (seconds)", "float", 4.0, 1, 20),
])
class Breathing(Renderer):
    def render(self, t, ctx):
        colors, period = self.params["colors"], self.params["period"]
        phase = t / period
        n = math.floor(phase)
        level = (1 - math.cos(2 * math.pi * (phase - n))) / 2
        c = scale(colors[n % len(colors)], level)
        return {k: c for k in keys_of(ctx)}
