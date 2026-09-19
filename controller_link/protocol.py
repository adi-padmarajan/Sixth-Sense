"""Wire protocol between the QNX controller and the companion-host laptop.

Every message is one newline-terminated, flat JSON object (no nested arrays or
objects) so a QNX-side C sender can format each field with snprintf instead of
depending on a JSON library. See ../docs/controller_link_protocol.md for the
full wire spec meant to be handed to whoever implements the controller side.

This module only encodes/decodes and validates one message at a time; it opens
no sockets. CLAUDE.md (repo root) §7 contract rules this enforces:
  - schema_version, source_id, session_id, sequence, source_mode, and a
    source-local monotonic timestamp are present on every message.
  - distance_mm is populated only for a usable numeric reading; 0/-1/NaN are
    never accepted as "missing" sentinels -- the type itself rejects them.
  - A message reports its own age (age_ms / detected_age_ms) using the
    sender's own clock. Receivers must never diff their own clock against
    another source's ts_mono_ms (see controller_link/state.py).
  - Config-change expiry is a relative ttl_ms, not an absolute deadline, for
    the same cross-clock reason.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
import json
import math
from typing import Literal, Union

SCHEMA_VERSION = 1

# Wearer-relative, clockwise-from-above bearings (repo root CLAUDE.md §5).
CHANNELS: tuple[str, ...] = (
    "front", "front_right", "right", "rear_right",
    "rear", "rear_left", "left", "front_left",
)
CHANNEL_BEARING_DEG: dict[str, int] = {c: i * 45 for i, c in enumerate(CHANNELS)}
CHANNEL_MOTOR: dict[str, str] = {c: f"motor_{i}" for i, c in enumerate(CHANNELS)}

BANDS: tuple[str, ...] = ("far", "mid", "near", "urgent", "beyond_alert_range", "unknown")
CHANNEL_HEALTH: tuple[str, ...] = ("ok", "fault", "unknown")
SUBSYSTEM_STATES: tuple[str, ...] = ("starting", "ready", "partial", "paused", "fault")
SOURCE_MODES: tuple[str, ...] = ("live", "simulated", "replay")
CONFIG_INTENTS: tuple[str, ...] = (
    "set_alert_distance_mm",
    "set_sensitivity_preset",
    "set_haptic_comfort_level",
    "pause_feedback",
    "resume_feedback",
)
CONFIG_RESULTS: tuple[str, ...] = ("accepted", "rejected")

# Bounded messages (CLAUDE.md §4): reject anything absurdly large before it
# reaches json.loads, so one malformed/hostile line cannot grow unbounded.
MAX_LINE_BYTES = 4096

SourceModeT = Literal["live", "simulated", "replay"]


def _validate_envelope(msg) -> None:
    if msg.schema_version != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}, got {msg.schema_version!r}")
    for name in ("source_id", "session_id"):
        value = getattr(msg, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    if type(msg.sequence) is not int or msg.sequence < 0:
        raise ValueError("sequence must be a non-negative int")
    if msg.source_mode not in SOURCE_MODES:
        raise ValueError(f"unknown source_mode {msg.source_mode!r}")
    if type(msg.ts_mono_ms) is not int or msg.ts_mono_ms < 0:
        raise ValueError("ts_mono_ms must be a non-negative int")


@dataclass(frozen=True, slots=True)
class ChannelState:
    """One direction's filtered reading, matching CLAUDE.md §7's ChannelState."""

    schema_version: int
    msg_type: Literal["channel_state"]
    source_id: str
    session_id: str
    sequence: int
    source_mode: str
    ts_mono_ms: int
    channel: str
    distance_mm: int | None
    age_ms: int
    health: str
    band: str
    config_version: int

    def __post_init__(self):
        _validate_envelope(self)
        if self.msg_type != "channel_state":
            raise ValueError("msg_type must be 'channel_state'")
        if self.channel not in CHANNELS:
            raise ValueError(f"unknown channel {self.channel!r}")
        if self.distance_mm is not None and (type(self.distance_mm) is not int or self.distance_mm <= 0):
            raise ValueError("distance_mm must be a positive int or null, never a sentinel")
        if type(self.age_ms) is not int or self.age_ms < 0:
            raise ValueError("age_ms must be a non-negative int")
        if self.health not in CHANNEL_HEALTH:
            raise ValueError(f"unknown channel health {self.health!r}")
        if self.band not in BANDS:
            raise ValueError(f"unknown band {self.band!r}")
        if self.band == "unknown" and self.distance_mm is not None:
            raise ValueError("band 'unknown' must not carry a distance_mm")
        if type(self.config_version) is not int or self.config_version < 0:
            raise ValueError("config_version must be a non-negative int")


@dataclass(frozen=True, slots=True)
class HealthEvent:
    """A subsystem health transition, matching CLAUDE.md §7's HealthEvent."""

    schema_version: int
    msg_type: Literal["health_event"]
    source_id: str
    session_id: str
    sequence: int
    source_mode: str
    ts_mono_ms: int
    subsystem: str
    state: str
    reason: str
    detected_age_ms: int
    recovered: bool

    def __post_init__(self):
        _validate_envelope(self)
        if self.msg_type != "health_event":
            raise ValueError("msg_type must be 'health_event'")
        if not isinstance(self.subsystem, str) or not self.subsystem.strip():
            raise ValueError("subsystem must be a non-empty string")
        if self.state not in SUBSYSTEM_STATES:
            raise ValueError(f"unknown subsystem state {self.state!r}")
        if not isinstance(self.reason, str):
            raise ValueError("reason must be a string")
        if type(self.detected_age_ms) is not int or self.detected_age_ms < 0:
            raise ValueError("detected_age_ms must be a non-negative int")
        if type(self.recovered) is not bool:
            raise ValueError("recovered must be a boolean")


@dataclass(frozen=True, slots=True)
class ConfigRequest:
    """Laptop -> controller. Matches CLAUDE.md §7's ConfigRequest.

    `ttl_ms` is relative to this message's own send time, not an absolute
    deadline: the controller has no way to compare the laptop's monotonic
    clock to its own (CLAUDE.md §7's clock-mapping rule), so it must compute
    its own deadline as (its own receipt time + ttl_ms).
    """

    schema_version: int
    msg_type: Literal["config_request"]
    source_id: str
    session_id: str
    sequence: int
    source_mode: str
    ts_mono_ms: int
    request_id: str
    base_config_version: int
    intent: str
    param_name: str | None
    param_value_num: float | None
    param_value_str: str | None
    ttl_ms: int

    def __post_init__(self):
        _validate_envelope(self)
        if self.msg_type != "config_request":
            raise ValueError("msg_type must be 'config_request'")
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("request_id must be a non-empty string")
        if type(self.base_config_version) is not int or self.base_config_version < 0:
            raise ValueError("base_config_version must be a non-negative int")
        if self.intent not in CONFIG_INTENTS:
            raise ValueError(f"unknown config intent {self.intent!r}")
        if self.param_name is not None and (not isinstance(self.param_name, str) or not self.param_name.strip()):
            raise ValueError("param_name must be a non-empty string or null")
        if self.param_value_num is not None and (
                type(self.param_value_num) not in (int, float) or not math.isfinite(self.param_value_num)):
            raise ValueError("param_value_num must be a finite number or null")
        if self.param_value_str is not None and not isinstance(self.param_value_str, str):
            raise ValueError("param_value_str must be a string or null")
        if type(self.ttl_ms) is not int or self.ttl_ms <= 0:
            raise ValueError("ttl_ms must be a positive int")


@dataclass(frozen=True, slots=True)
class ConfigAck:
    """Controller -> laptop. Matches CLAUDE.md §7's ConfigAck."""

    schema_version: int
    msg_type: Literal["config_ack"]
    source_id: str
    session_id: str
    sequence: int
    source_mode: str
    ts_mono_ms: int
    request_id: str
    result: str
    reason: str | None
    active_config_version: int

    def __post_init__(self):
        _validate_envelope(self)
        if self.msg_type != "config_ack":
            raise ValueError("msg_type must be 'config_ack'")
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("request_id must be a non-empty string")
        if self.result not in CONFIG_RESULTS:
            raise ValueError(f"unknown config result {self.result!r}")
        if self.result == "rejected" and not self.reason:
            raise ValueError("a rejected ConfigAck must carry a reason")
        if self.reason is not None and not isinstance(self.reason, str):
            raise ValueError("reason must be a string or null")
        if type(self.active_config_version) is not int or self.active_config_version < 0:
            raise ValueError("active_config_version must be a non-negative int")


Message = Union[ChannelState, HealthEvent, ConfigRequest, ConfigAck]

_MESSAGE_TYPES: dict[str, type] = {
    "channel_state": ChannelState,
    "health_event": HealthEvent,
    "config_request": ConfigRequest,
    "config_ack": ConfigAck,
}


def encode(message: Message) -> bytes:
    """One JSON object, one line, UTF-8. Raises ValueError over the size bound."""
    line = json.dumps(dataclasses.asdict(message), separators=(",", ":"), sort_keys=True)
    encoded = (line + "\n").encode("utf-8")
    if len(encoded) > MAX_LINE_BYTES:
        raise ValueError(f"encoded message exceeds {MAX_LINE_BYTES} bytes")
    return encoded


def decode(line: str) -> Message:
    """Parse one line into its typed message.

    Raises ValueError on anything malformed, unknown, oversized, or with an
    invalid field. Callers on a read loop must catch this, drop the line, and
    keep reading -- one bad line from a peer must never crash the link.
    """
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        raise ValueError("line exceeds maximum message size")
    raw = json.loads(line)
    if not isinstance(raw, dict):
        raise ValueError("message must be a JSON object")
    cls = _MESSAGE_TYPES.get(raw.get("msg_type"))
    if cls is None:
        raise ValueError(f"unknown msg_type {raw.get('msg_type')!r}")
    expected = {f.name for f in dataclasses.fields(cls)}
    unknown = sorted(set(raw) - expected)
    if unknown:
        raise ValueError(f"unknown field(s) for {raw['msg_type']}: {unknown}")
    missing = sorted(expected - set(raw))
    if missing:
        raise ValueError(f"missing field(s) for {raw['msg_type']}: {missing}")
    try:
        return cls(**raw)
    except TypeError as exc:
        raise ValueError(str(exc)) from exc
