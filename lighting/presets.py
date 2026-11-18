# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Presets: named layer stacks. User presets live in presets.json in huntsman_core.data_dir();
built-in presets are made in code and never written to the file."""
import json
import os
import threading
from dataclasses import dataclass, field

import huntsman_core as hc
from lighting.frame import Keymap
from lighting.layers import Layer

FILE_VERSION = 1


@dataclass
class Preset:
    name: str
    layers: list[Layer] = field(default_factory=list)
    brightness: float = 1.0

    def validate(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("a preset needs a name")
        if (not isinstance(self.brightness, (int, float)) or isinstance(self.brightness, bool)
                or not 0 <= self.brightness <= 1):
            raise ValueError("preset brightness must be 0-1")
        if not isinstance(self.layers, list) or not all(isinstance(layer, Layer) for layer in self.layers):
            raise ValueError("preset layers must be a list of layers")
        ids = [layer.id for layer in self.layers]
        if len(set(ids)) != len(ids):
            raise ValueError(f"preset {self.name!r} has two layers with the same id")
        for layer in self.layers:
            layer.validate()

    def to_dict(self):
        return {"name": self.name, "brightness": self.brightness, "layers": [layer.to_dict() for layer in self.layers]}

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict):
            raise ValueError("a preset must be an object")
        unknown = set(d) - {"name", "brightness", "layers"}
        if unknown:
            raise ValueError(f"unknown preset field(s) {', '.join(sorted(unknown))}")
        if "name" not in d or "layers" not in d:
            raise ValueError("a preset needs a name and a layer list")
        layers = d["layers"]
        if not isinstance(layers, list):
            raise ValueError("preset layers must be a list")
        p = cls(name=d.get("name"), brightness=d.get("brightness", 1.0), layers=[Layer.from_dict(x) for x in layers])
        p.validate()
        return p


def presets_path():
    return os.path.join(hc.data_dir(), "presets.json")


def load_presets():
    """User presets from presets.json; [] when there is no file. A damaged file raises ValueError."""
    try:
        with open(presets_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"presets.json could not be read: {e}") from e
    if not isinstance(raw, dict) or not isinstance(raw.get("presets"), list):
        raise ValueError("presets.json is not a preset list")
    presets = [Preset.from_dict(p) for p in raw["presets"]]
    _check_unique(presets)
    return presets


def save_presets(presets):
    """Validate everything, then replace presets.json atomically (temp file per process and thread)."""
    for p in presets:
        p.validate()
    _check_unique(presets)
    path = presets_path()
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": FILE_VERSION, "presets": [p.to_dict() for p in presets]}, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _check_unique(presets):
    names = [p.name for p in presets]
    if len(set(names)) != len(names):
        raise ValueError("two presets have the same name")


def builtin_presets(keymap=None):
    """Starter presets (fresh objects every call, so editing one never changes the originals)."""
    km = keymap or Keymap.load()
    wasd = [km.by_name(n).id for n in "WASD" if km.by_name(n)]
    return [
        Preset("Rainbow wave", [Layer("wave", "rainbow", {"speed": 0.4, "scale": 1.0})]),
        Preset("Aurora", [Layer("aurora", "aurora", {"speed": 0.4})]),
        Preset("Gaming WASD", [
            Layer("base", "solid", {"color": [20, 0, 60]}),
            Layer("wasd", "solid", {"color": [255, 0, 40]}, keys=wasd),
            Layer("ripple", "reactive_ripple", {"colors": [[0, 200, 255]], "speed": 14.0, "fade": 0.8}, blend="add"),
        ]),
        Preset("Typing glow", [
            Layer("base", "solid", {"color": [10, 10, 30]}),
            Layer("glow", "reactive_afterglow", {"color": [255, 140, 0], "fade": 1.2}, blend="screen"),
        ]),
        Preset("Music", [Layer("bars", "audio_spectrum", {"mirror": True})]),
        Preset("Fire", [Layer("fire", "fire", {})]),
        Preset("Matrix", [Layer("rain", "matrix", {})]),
        Preset("Calm breathing", [Layer("breathe", "breathing", {"colors": [[0, 120, 255], [120, 0, 255]],
                                                                  "period": 6.0})], brightness=0.8),
    ]
