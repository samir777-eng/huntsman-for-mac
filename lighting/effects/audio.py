# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Sound-reactive effects: audio spectrum, audio pulse."""
from lighting.effects.base import ParamSpec, Renderer, effect, keys_of
from lighting.frame import PALETTES, sample, scale

BANDS = 16


@effect("audio_spectrum", "Audio spectrum", "audio", [
    ParamSpec("colors", "Palette (bottom to top)", "colors", PALETTES["spectrum"], 1, 8),
    ParamSpec("mirror", "Bass in the middle", "bool", False),
], needs=("audio",))
class AudioSpectrum(Renderer):
    """16 bands across the keyboard (low on the left, or in the middle when mirrored); a band's level
    lights that many of the keyboard's rows (6, or 5 on a Mini) from the bottom."""

    def render(self, t, ctx):
        p = self.params
        bands = list(ctx.audio.bands) if ctx.audio else []
        w = ctx.keymap.bounds[0] or 1.0
        rows = ctx.keymap.rows
        out = {}
        for k in keys_of(ctx):
            u = ctx.keymap.center(k)[0] / w
            if p["mirror"]:
                u = abs(2 * u - 1)
            band = min(BANDS - 1, int(u * BANDS))
            value = bands[band] if band < len(bands) else 0.0
            height = max(0.0, min(1.0, value)) * rows
            level = rows - 1 - ctx.keymap.key(k).row  # 0 = bottom row
            lit = max(0.0, min(1.0, height - level))
            out[k] = scale(sample(p["colors"], level / max(1, rows - 1)), lit)
        return out


@effect("audio_pulse", "Audio pulse", "audio", [
    ParamSpec("colors", "Palette (quiet to loud)", "colors", [(0, 160, 255), (255, 0, 160)], 1, 8),
    ParamSpec("sensitivity", "Sensitivity", "float", 1.5, 0.1, 5),
], needs=("audio",))
class AudioPulse(Renderer):
    def render(self, t, ctx):
        level = (ctx.audio.level if ctx.audio else 0.0) * self.params["sensitivity"]
        level = max(0.0, min(1.0, level))
        c = scale(sample(self.params["colors"], level), level)
        return {k: c for k in keys_of(ctx)}

