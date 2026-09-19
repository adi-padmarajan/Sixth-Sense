"""
Single validated source for speech settings (CLAUDE.md §13).

`SpeechConfig` holds hardware selection (model paths, audio devices),
timing (blocksize, echo guard, command age), queue limits, and the wake
phrase policy. Load it from `configs/speech.json` with `SpeechConfig.load()`
or construct it directly (defaults only, no model paths) for fakes/tests.

Paths in the JSON file are resolved relative to the file's own directory.
The grammar comes from `grammar_path` (a JSON list of phrases) unless
`grammar` is given inline.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

SCHEMA_VERSION = 1

_PATH_FIELDS = ("tts_model_path", "tts_config_path", "stt_model_path", "grammar_path")


@dataclass(frozen=True)
class SpeechConfig:
    schema_version: int = SCHEMA_VERSION

    # Backends. All optional so a config with no models can drive fakes.
    tts_model_path: Optional[str] = None
    tts_config_path: Optional[str] = None
    stt_model_path: Optional[str] = None
    grammar_path: Optional[str] = None
    grammar: Tuple[str, ...] = ()
    tts_device: Optional[int] = None   # sounddevice index; None = default
    stt_device: Optional[int] = None

    # Capture timing (provisional bench values; see stt.py).
    samplerate: int = 16000
    blocksize: int = 4000

    # Echo guard / dispatch.
    echo_guard_seconds: float = 0.3
    max_command_age_seconds: float = 2.0

    # Speech queue.
    max_queue: int = 16
    dedup_window_seconds: float = 2.0

    # Wake phrase policy. None = every grammar phrase dispatches directly.
    wake_phrase: Optional[str] = None
    wake_window_seconds: float = 5.0
    always_on_commands: Tuple[str, ...] = ("stop speaking",)

    # Question capture for the assistant (raw mic audio after the wake
    # command, bypassing the recogniser). Provisional demo values.
    question_seconds: float = 3.0
    max_capture_seconds: float = 10.0
    listening_tone: bool = True

    def __post_init__(self):
        # Normalise list inputs to tuples and phrases to lower case.
        object.__setattr__(self, "grammar", tuple(_norm(p) for p in self.grammar))
        object.__setattr__(self, "always_on_commands", tuple(_norm(p) for p in self.always_on_commands))
        if self.wake_phrase is not None:
            object.__setattr__(self, "wake_phrase", _norm(self.wake_phrase))
        self.validate(require_models=False)

    # -- validation -----------------------------------------------------------

    def validate(self, require_models: bool) -> "SpeechConfig":
        """Raise ValueError on a bad config. With `require_models`, model
        paths must be set and exist (i.e. a real backend is requested)."""
        errors = []
        if self.schema_version != SCHEMA_VERSION:
            errors.append(f"schema_version must be {SCHEMA_VERSION}, got {self.schema_version!r}")

        for name, lo in (("samplerate", 8000), ("blocksize", 160), ("max_queue", 1)):
            v = getattr(self, name)
            if not isinstance(v, int) or isinstance(v, bool) or v < lo:
                errors.append(f"{name} must be an int >= {lo}, got {v!r}")
        for name in ("echo_guard_seconds", "max_command_age_seconds", "dedup_window_seconds", "wake_window_seconds",
                     "question_seconds", "max_capture_seconds"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0 or v > 60:
                errors.append(f"{name} must be a number in [0, 60], got {v!r}")
        if type(self.listening_tone) is not bool:
            errors.append("listening_tone must be boolean")
        if isinstance(self.question_seconds, (int, float)) and isinstance(self.max_capture_seconds, (int, float)):
            if not 0 < self.question_seconds <= self.max_capture_seconds:
                errors.append(
                    f"question_seconds must satisfy 0 < question_seconds <= max_capture_seconds "
                    f"({self.max_capture_seconds!r}), got {self.question_seconds!r}")
        for name in ("tts_device", "stt_device"):
            v = getattr(self, name)
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
                errors.append(f"{name} must be a non-negative int or null, got {v!r}")
        for name in _PATH_FIELDS:
            v = getattr(self, name)
            if v is not None and (not isinstance(v, str) or not v):
                errors.append(f"{name} must be a non-empty string or null, got {v!r}")

        if any(not p for p in self.grammar):
            errors.append("grammar contains an empty phrase")
        if len(set(self.grammar)) != len(self.grammar):
            errors.append("grammar contains duplicate phrases")
        if self.grammar:
            if self.wake_phrase is not None and self.wake_phrase not in self.grammar:
                errors.append(f"wake_phrase {self.wake_phrase!r} is not in the grammar")
            missing = [c for c in self.always_on_commands if c not in self.grammar]
            if missing:
                errors.append(f"always_on_commands not in the grammar: {missing}")
        if self.wake_phrase is not None and self.wake_window_seconds <= 0:
            errors.append("wake_window_seconds must be > 0 when wake_phrase is set")

        if require_models:
            for name in ("tts_model_path", "stt_model_path"):
                v = getattr(self, name)
                if v is None:
                    errors.append(f"{name} is required for a real backend")
                elif not os.path.exists(v):
                    errors.append(f"{name} does not exist: {v}")
            if self.tts_config_path is not None and not os.path.exists(self.tts_config_path):
                errors.append(f"tts_config_path does not exist: {self.tts_config_path}")
            if not self.grammar:
                errors.append("grammar is empty; set grammar_path or grammar")

        if errors:
            raise ValueError("invalid speech config: " + "; ".join(errors))
        return self

    # -- loading --------------------------------------------------------------

    @classmethod
    def load(cls, path: str, require_models: bool = True) -> "SpeechConfig":
        with open(path) as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: top level must be an object")
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"{path}: unknown key(s) {unknown}")

        base = os.path.dirname(os.path.abspath(path))
        data: Dict[str, Any] = dict(raw)
        for name in _PATH_FIELDS:
            v = data.get(name)
            if isinstance(v, str) and v and not os.path.isabs(v):
                data[name] = os.path.normpath(os.path.join(base, v))

        if "grammar" not in data and data.get("grammar_path"):
            with open(data["grammar_path"]) as f:
                grammar = json.load(f)
            if not isinstance(grammar, list) or not all(isinstance(p, str) for p in grammar):
                raise ValueError(f"{data['grammar_path']}: must be a JSON list of strings")
            data["grammar"] = grammar

        try:
            cfg = cls(**data)
        except TypeError as exc:  # wrong field types that dataclass itself rejects
            raise ValueError(f"{path}: {exc}") from exc
        return cfg.validate(require_models=require_models)

    def replace(self, **changes) -> "SpeechConfig":
        return dataclasses.replace(self, **changes)


def _norm(phrase: Any) -> Any:
    return phrase.strip().lower() if isinstance(phrase, str) else phrase
