"""Companion-host side of the controller link.

This is the "Configuration and monitoring" path from the repo root
CLAUDE.md §4: small, infrequent telemetry and config-change messages between
the laptop (vision/speech/assistant) and the QNX controller (sensors/haptics).
It never carries camera frames or audio, and the controller's local
proximity-to-haptic loop must keep working with this link absent entirely.

See ../docs/controller_link_protocol.md for the wire spec the QNX-side
controller must implement to interoperate with `ControllerLinkClient`.
"""
from .client import ConfigOutcome, ControllerLinkClient, LinkStatus
from .config import ControllerLinkConfig
from .protocol import (
    CHANNEL_BEARING_DEG,
    CHANNEL_MOTOR,
    CHANNELS,
    SCHEMA_VERSION,
    ChannelState,
    ConfigAck,
    ConfigRequest,
    HealthEvent,
    decode,
    encode,
)
from .state import ChannelReading, ControllerState, HealthReading

__all__ = [
    "SCHEMA_VERSION", "CHANNELS", "CHANNEL_BEARING_DEG", "CHANNEL_MOTOR",
    "ChannelState", "HealthEvent", "ConfigRequest", "ConfigAck", "encode", "decode",
    "ControllerLinkConfig",
    "ControllerState", "ChannelReading", "HealthReading",
    "ControllerLinkClient", "ConfigOutcome", "LinkStatus",
]
