# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The effect library. REGISTRY maps effect name -> EffectSpec; create(name, params) -> renderer."""
from lighting.effects import ambient, audio, basic, reactive  # noqa: F401  (registers the effects)
from lighting.effects.base import (REGISTRY, EffectSpec, ParamSpec, RenderContext, Renderer, check_param,
                                   create, validate_params)
from lighting.frame import AudioState, KeyEvent

__all__ = ["REGISTRY", "AudioState", "EffectSpec", "KeyEvent", "ParamSpec", "RenderContext", "Renderer",
           "check_param", "create", "validate_params"]
