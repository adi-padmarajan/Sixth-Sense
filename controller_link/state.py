"""Thread-safe latest controller telemetry: one writer (the link's reader
thread), many readers (voice status, a future live monitor).

Modeled on computer-vision/scene_state.py's SceneState: latest-only, no
queue, readers never block a writer. Unlike SceneState there are several
independent keys (one per channel, one per subsystem), so a lock guards a
small dict swap rather than a single reference assignment.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
import time
from typing import Callable

from .protocol import CHANNELS, ChannelState, HealthEvent


@dataclass(frozen=True, slots=True)
class ChannelReading:
    state: ChannelState
    received_at: float  # laptop-local monotonic, set on receipt


@dataclass(frozen=True, slots=True)
class HealthReading:
    event: HealthEvent
    received_at: float


class ControllerState:
    """Latest per-channel state and per-subsystem health for one controller
    session. A new session_id (controller restart, or first message after a
    reconnect to a different process) clears prior readings and sequence
    bookkeeping -- it never carries a stale reading forward under a new
    session's identity (CLAUDE.md §4: "Reconnects reset session-specific
    state; never replay expired commands").
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = Lock()
        self._session_id: str | None = None
        self._channels: dict[str, ChannelReading] = {}
        self._health: dict[str, HealthReading] = {}
        self._last_sequence: dict[tuple[str, str], int] = {}

    def _accept_sequence_locked(self, session_id: str, source_id: str, sequence: int) -> bool:
        if session_id != self._session_id:
            self._session_id = session_id
            self._channels.clear()
            self._health.clear()
            self._last_sequence.clear()
        key = (session_id, source_id)
        last = self._last_sequence.get(key)
        if last is not None and sequence <= last:
            return False  # stale, duplicate, or out-of-order: reject, don't apply
        self._last_sequence[key] = sequence
        return True

    def apply_channel_state(self, msg: ChannelState) -> bool:
        """Ingest one telemetry message. False means it was rejected as
        out-of-order/duplicate; callers may count/log this but must not raise."""
        with self._lock:
            if not self._accept_sequence_locked(msg.session_id, msg.source_id, msg.sequence):
                return False
            self._channels[msg.channel] = ChannelReading(msg, self._clock())
            return True

    def apply_health_event(self, msg: HealthEvent) -> bool:
        with self._lock:
            if not self._accept_sequence_locked(msg.session_id, msg.source_id, msg.sequence):
                return False
            self._health[msg.subsystem] = HealthReading(msg, self._clock())
            return True

    def channel(self, channel: str) -> ChannelReading | None:
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}")
        with self._lock:
            return self._channels.get(channel)

    def channels(self) -> dict[str, ChannelReading]:
        """Snapshot of channels reported so far this session. A channel with
        no entry is unknown -- never assume it means 'far' or 'clear'."""
        with self._lock:
            return dict(self._channels)

    def health(self) -> dict[str, HealthReading]:
        with self._lock:
            return dict(self._health)

    def total_age_s(self, reading: ChannelReading | HealthReading) -> float:
        """Source-reported age plus receipt-to-now delay. Both terms are
        computed on a single clock each (the source's own, and ours); this
        never diffs the controller's monotonic clock against the laptop's
        (CLAUDE.md §7's clock-mapping rule)."""
        source_age_ms = reading.state.age_ms if isinstance(reading, ChannelReading) else reading.event.detected_age_ms
        since_receipt_s = max(0.0, self._clock() - reading.received_at)
        return source_age_ms / 1000 + since_receipt_s

    def reset(self) -> None:
        """Drop all cached telemetry, e.g. when the link disconnects -- callers
        must not keep showing the last-known reading as if it were current."""
        with self._lock:
            self._session_id = None
            self._channels.clear()
            self._health.clear()
            self._last_sequence.clear()
