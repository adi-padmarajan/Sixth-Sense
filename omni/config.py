"""Versioned assistant settings; JSON paths are relative to the config file."""
from __future__ import annotations

from dataclasses import dataclass, fields
import json
import math
from pathlib import Path

from .client import ClientConfig


@dataclass(frozen=True)
class AssistantConfig:
    schema_version: int = 1
    cloud_enabled: bool = False
    omni_model: str = "qwen3.5-omni-flash"
    omni_base_url: str = "https://yibuapi.com/v1"
    omni_timeout_s: float = 6.0
    max_scene_age_ms: int = 500
    answer_within_ms: int = 6000
    frame_jpeg_width: int = 480
    max_tokens: int = 96
    audit_log: str | None = None
    describe_command: str = "describe"
    direct_question_command: str = "what's in front of me"
    direct_question_prompt: str = "What is in front of me in the camera view?"

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("schema_version must be 1")
        if type(self.cloud_enabled) is not bool:
            raise ValueError("cloud_enabled must be a boolean")
        for name in ("max_scene_age_ms", "answer_within_ms", "frame_jpeg_width", "max_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (type(self.omni_timeout_s) not in (int, float)
                or not math.isfinite(self.omni_timeout_s) or self.omni_timeout_s <= 0):
            raise ValueError("omni_timeout_s must be positive and finite")
        if self.answer_within_ms < self.max_scene_age_ms:
            raise ValueError("answer_within_ms must be >= max_scene_age_ms")
        if self.omni_timeout_s > self.answer_within_ms / 1000:
            raise ValueError("omni_timeout_s must be <= answer_within_ms / 1000")
        for name in ("omni_model", "omni_base_url", "describe_command",
                     "direct_question_command", "direct_question_prompt"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in ("describe_command", "direct_question_command"):
            object.__setattr__(self, name, getattr(self, name).strip().lower())
        commands = (self.describe_command, self.direct_question_command,
                    "device status", "stop speaking")
        if len(set(commands)) != len(commands):
            raise ValueError("assistant commands must be distinct from each other and status/stop")
        if self.audit_log is not None and (not isinstance(self.audit_log, str) or not self.audit_log.strip()):
            raise ValueError("audit_log must be a non-empty path string or null")
        self.client_config()  # Reuse the transport's endpoint validation.

    def client_config(self, *, cloud_enabled: bool | None = None) -> ClientConfig:
        return ClientConfig(
            cloud_enabled=self.cloud_enabled if cloud_enabled is None else cloud_enabled,
            model=self.omni_model, base_url=self.omni_base_url,
            timeout_s=self.omni_timeout_s, max_tokens=self.max_tokens, audit_log=self.audit_log,
        )

    @classmethod
    def load(cls, path: str | Path) -> AssistantConfig:
        path = Path(path).resolve()
        with path.open() as stream:
            raw = json.load(stream)
        if not isinstance(raw, dict):
            raise ValueError("assistant config top level must be an object")
        unknown = sorted(set(raw) - {field.name for field in fields(cls)})
        if unknown:
            raise ValueError(f"assistant config unknown key(s): {unknown}")
        audit_log = raw.get("audit_log")
        if isinstance(audit_log, str) and audit_log.strip():
            raw["audit_log"] = str((path.parent / audit_log).resolve())
        return cls(**raw)
