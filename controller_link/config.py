"""Versioned settings for the laptop-side controller-link client (CLAUDE.md §13).

Load from configs/controller_link.json with ControllerLinkConfig.load(), or
construct directly (defaults only) for tests. Unknown keys and invalid values
fail at startup rather than silently falling back.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import json
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ControllerLinkConfig:
    schema_version: int = SCHEMA_VERSION

    # Placeholder host: replace with the controller's actual address on the
    # dedicated demo network (not the venue Wi-Fi) before the demo.
    host: str = "192.0.2.10"
    port: int = 8765
    source_id: str = "companion-host"

    connect_timeout_s: float = 3.0
    # Socket read timeout: how often the reader thread wakes to check for
    # shutdown/backoff, independent of whether data has arrived.
    read_idle_timeout_s: float = 1.0
    reconnect_backoff_min_s: float = 0.5
    reconnect_backoff_max_s: float = 5.0
    # Telemetry older than this (source-reported age + receipt delay) is
    # treated as stale by ControllerState consumers, not as a fresh unknown.
    stale_after_ms: int = 1000
    default_config_request_ttl_ms: int = 1500

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}, got {self.schema_version!r}")
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError("host must be a non-empty string")
        if type(self.port) is not int or not (0 < self.port < 65536):
            raise ValueError("port must be an int in (0, 65536)")
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("source_id must be a non-empty string")
        for name in ("connect_timeout_s", "read_idle_timeout_s",
                     "reconnect_backoff_min_s", "reconnect_backoff_max_s"):
            value = getattr(self, name)
            if type(value) not in (int, float) or value <= 0:
                raise ValueError(f"{name} must be a positive number")
        if self.reconnect_backoff_min_s > self.reconnect_backoff_max_s:
            raise ValueError("reconnect_backoff_min_s must be <= reconnect_backoff_max_s")
        for name in ("stale_after_ms", "default_config_request_ttl_ms"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive int")

    @classmethod
    def load(cls, path: str | Path) -> ControllerLinkConfig:
        path = Path(path).resolve()
        with path.open() as stream:
            raw = json.load(stream)
        if not isinstance(raw, dict):
            raise ValueError("controller-link config top level must be an object")
        unknown = sorted(set(raw) - {field.name for field in fields(cls)})
        if unknown:
            raise ValueError(f"controller-link config unknown key(s): {unknown}")
        return cls(**raw)
