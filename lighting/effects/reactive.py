# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Typing effects: heatmap and the reactions (ripple, afterglow, explosion, trail).

Reactions remember key presses from ctx.events (each event once, however often it is passed) and forget
them when their fade time is over. Keys with no light are returned black, so a reaction layer usually
sits above its base with the "add", "screen" or "max" blend.
"""
from lighting.effects.base import ParamSpec, Renderer, effect, keys_of, rand
from lighting.frame import BLACK, PALETTES, dist, sample, scale


@effect("heatmap", "Typing heatmap", "reactive", [
    ParamSpec("colors", "Palette (cold to hot)", "colors", PALETTES["heat"], 2, 8),
], needs=("keys",))
class Heatmap(Renderer):
    """Per-key press counts (ctx.heat) scaled so the most-pressed key gets the hottest colour."""

    def render(self, t, ctx):
        top = max(ctx.heat.values(), default=0) or 1
        return {k: sample(self.params["colors"], ctx.heat.get(k, 0) / top) for k in keys_of(ctx)}


class Reaction(Renderer):
    """Keeps the key-down events that are still fading in self.active (oldest first)."""

    def __init__(self, params):
        super().__init__(params)
        self.active = []
        self._seen = set()

    def lifetime(self):
        return self.params["fade"]

    def ingest(self, t, ctx):
        for e in ctx.events:
            if e.down and e not in self._seen and e.key_id in ctx.keymap:
                self._seen.add(e)
                self.active.append(e)
        life = self.lifetime()
        self.active = sorted((e for e in self.active if t - e.t <= life), key=lambda e: (e.t, e.key_id))
        self._seen = set(self.active)
        return [(e, t - e.t) for e in self.active if t >= e.t]

    def event_colour(self, e, colors):
        return colors[int(rand(e.key_id, round(e.t * 1000)) * len(colors))]

    def render(self, t, ctx):
        live = self.ingest(t, ctx)
        best = {k: (0.0, BLACK) for k in keys_of(ctx)}
        for e, age in live:
            for k, level, colour in self.light(e, age, ctx):
                if k in best and level > best[k][0]:
                    best[k] = (level, colour)
        return {k: scale(c, level) for k, (level, c) in best.items()}

    def light(self, e, age, ctx):
        """Yield (key, level 0..1, colour) for one event of this age."""
        raise NotImplementedError


REACT_COLORS = ParamSpec("colors", "Colours", "colors", [(0, 200, 255)], 1, 8)


@effect("reactive_ripple", "Ripple", "reactive", [
    REACT_COLORS,
    ParamSpec("speed", "Speed (keys per second)", "float", 12.0, 2, 40),
    ParamSpec("width", "Ring width (keys)", "float", 1.5, 0.5, 5),
    ParamSpec("fade", "Fade time (seconds)", "float", 1.0, 0.2, 5),
], needs=("keys",))
class Ripple(Reaction):
    def light(self, e, age, ctx):
        p = self.params
        radius, fade = age * p["speed"], 1 - age / p["fade"]
        colour = self.event_colour(e, p["colors"])
        origin = ctx.keymap.center(e.key_id)
        for k in keys_of(ctx):
            ring = 1 - abs(dist(ctx.keymap.center(k), origin) - radius) / p["width"]
            if ring > 0:
                yield k, ring * fade, colour


@effect("reactive_afterglow", "Afterglow", "reactive", [
    ParamSpec("color", "Colour", "color", (255, 120, 0)),
    ParamSpec("fade", "Fade time (seconds)", "float", 0.8, 0.1, 5),
], needs=("keys",))
class Afterglow(Reaction):
    def light(self, e, age, ctx):
        yield e.key_id, 1 - age / self.params["fade"], self.params["color"]


@effect("reactive_explosion", "Explosion", "reactive", [
    ParamSpec("colors", "Colours (centre to edge)", "colors", [(255, 255, 255), (255, 140, 0), (255, 0, 0)], 1, 8),
    ParamSpec("radius", "Radius (keys)", "float", 4.0, 1, 10),
    ParamSpec("fade", "Fade time (seconds)", "float", 0.8, 0.2, 5),
], needs=("keys",))
class Explosion(Reaction):
    def light(self, e, age, ctx):
        p = self.params
        reach = max(0.6, p["radius"] * min(1.0, age / (p["fade"] * 0.35)))
        fade = 1 - age / p["fade"]
        origin = ctx.keymap.center(e.key_id)
        for k in keys_of(ctx):
            d = dist(ctx.keymap.center(k), origin)
            if d < reach:
                yield k, (1 - d / reach) * fade, sample(p["colors"], d / p["radius"])


@effect("reactive_trail", "Trail", "reactive", [
    ParamSpec("color", "Colour", "color", (0, 255, 180)),
    ParamSpec("length", "Length (keys)", "float", 6.0, 1, 22),
    ParamSpec("fade", "Fade time (seconds)", "float", 0.6, 0.1, 5),
], needs=("keys",))
class Trail(Reaction):
    """Two light fronts run outward from the pressed key along its row, leaving a fading tail."""

    def light(self, e, age, ctx):
        p = self.params
        front = age / p["fade"] * p["length"]
        tail = max(1.0, p["length"] * 0.5)
        fade = 1 - age / p["fade"]
        row = ctx.keymap.key(e.key_id).row
        ox = ctx.keymap.center(e.key_id)[0]
        for k in keys_of(ctx):
            if ctx.keymap.key(k).row != row:
                continue
            dx = abs(ctx.keymap.center(k)[0] - ox)
            if dx <= front + 0.5:
                level = max(0.0, 1 - max(0.0, front - dx) / tail) * fade
                if level > 0:
                    yield k, level, p["color"]

