"""Laptop-side client for the controller link.

Runs its own background thread; never blocks the caller beyond a bounded
wait. Connection loss must never affect vision/speech -- callers read
`status`/`state` defensively and degrade a status line, nothing more
(CLAUDE.md §12: "Network or cloud API fails -> retain local sensing; expose
only the voice/vision capabilities that still work" applies symmetrically
here to the controller link from the host's side).
"""
from __future__ import annotations

from dataclasses import dataclass
import socket
import threading
import time
from typing import Callable, Literal
import uuid

from .config import ControllerLinkConfig
from .protocol import (
    SCHEMA_VERSION,
    MAX_LINE_BYTES,
    ChannelState,
    ConfigAck,
    ConfigRequest,
    HealthEvent,
    decode,
    encode,
)
from .state import ControllerState

LinkStatus = Literal["disconnected", "ready", "stale"]
ConfigOutcomeStatus = Literal["acked", "timeout", "link_unavailable"]


@dataclass(frozen=True, slots=True)
class ConfigOutcome:
    status: ConfigOutcomeStatus
    ack: ConfigAck | None


class _Pending:
    __slots__ = ("event", "ack")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.ack: ConfigAck | None = None


class ControllerLinkClient:
    def __init__(
        self,
        config: ControllerLinkConfig,
        state: ControllerState | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        socket_factory: Callable[..., socket.socket] = socket.create_connection,
        source_mode: str = "live",
    ) -> None:
        self._config = config
        self.state = state if state is not None else ControllerState(clock=clock)
        self._clock = clock
        self._socket_factory = socket_factory
        self._source_mode = source_mode
        self._session_id = uuid.uuid4().hex
        self._sequence = 0
        self._seq_lock = threading.Lock()

        self._socket: socket.socket | None = None
        self._socket_lock = threading.Lock()
        self._write_lock = threading.Lock()

        self._pending: dict[str, _Pending] = {}
        self._pending_lock = threading.Lock()

        self._status: LinkStatus = "disconnected"
        self._status_lock = threading.Lock()

        self._closing = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self._closing.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="controller-link")
        self._thread.start()

    def close(self) -> None:
        self._closing.set()
        sock = self._current_socket()
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=self._config.connect_timeout_s + 1)
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for p in pending:
            p.event.set()

    # -- status -------------------------------------------------------------

    @property
    def status(self) -> LinkStatus:
        with self._status_lock:
            connection_status = self._status
        if connection_status != "ready":
            return connection_status
        newest = self._newest_age_s()
        if newest is not None and newest * 1000 > self._config.stale_after_ms:
            return "stale"
        return "ready"

    def _newest_age_s(self) -> float | None:
        readings = [*self.state.channels().values(), *self.state.health().values()]
        if not readings:
            return None
        return min(self.state.total_age_s(r) for r in readings)

    def _set_status(self, status: LinkStatus) -> None:
        with self._status_lock:
            self._status = status

    def _current_socket(self) -> socket.socket | None:
        with self._socket_lock:
            return self._socket

    # -- outgoing: config requests -------------------------------------------

    def send_config_request(
        self,
        intent: str,
        *,
        base_config_version: int,
        param_name: str | None = None,
        param_value_num: float | None = None,
        param_value_str: str | None = None,
        ttl_ms: int | None = None,
    ) -> ConfigOutcome:
        """Send one config change and wait up to ttl_ms (+ margin) for its ack.

        Never blocks indefinitely and never fabricates an ack: a dropped link
        or an expired wait both come back as an explicit non-"acked" status,
        never silently applied (CLAUDE.md §11: "Never announce an unacknowledged
        change").
        """
        ttl_ms = ttl_ms if ttl_ms is not None else self._config.default_config_request_ttl_ms
        sock = self._current_socket()
        if sock is None:
            return ConfigOutcome("link_unavailable", None)

        request_id = uuid.uuid4().hex
        with self._seq_lock:
            self._sequence += 1
            sequence = self._sequence
        msg = ConfigRequest(
            schema_version=SCHEMA_VERSION,
            msg_type="config_request",
            source_id=self._config.source_id,
            session_id=self._session_id,
            sequence=sequence,
            source_mode=self._source_mode,
            ts_mono_ms=int(self._clock() * 1000),
            request_id=request_id,
            base_config_version=base_config_version,
            intent=intent,
            param_name=param_name,
            param_value_num=param_value_num,
            param_value_str=param_value_str,
            ttl_ms=ttl_ms,
        )
        pending = _Pending()
        with self._pending_lock:
            self._pending[request_id] = pending
        try:
            with self._write_lock:
                sock.sendall(encode(msg))
        except (OSError, ValueError):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            return ConfigOutcome("link_unavailable", None)

        acked = pending.event.wait(ttl_ms / 1000 + self._config.read_idle_timeout_s)
        with self._pending_lock:
            self._pending.pop(request_id, None)
        if not acked:
            return ConfigOutcome("timeout", None)
        return ConfigOutcome("acked", pending.ack)

    # -- connection thread ----------------------------------------------------

    def _run(self) -> None:
        # No separate "connecting" status: a link that isn't up yet or has
        # dropped is "disconnected" the whole time it's retrying, so that
        # status a caller reads never flickers to something else in between.
        backoff = self._config.reconnect_backoff_min_s
        while not self._closing.is_set():
            try:
                sock = self._socket_factory(
                    (self._config.host, self._config.port), timeout=self._config.connect_timeout_s
                )
            except OSError:
                self._set_status("disconnected")
                self._closing.wait(backoff)
                backoff = min(backoff * 2, self._config.reconnect_backoff_max_s)
                continue

            backoff = self._config.reconnect_backoff_min_s
            sock.settimeout(self._config.read_idle_timeout_s)
            with self._socket_lock:
                self._socket = sock
            self._set_status("ready")
            try:
                self._read_loop(sock)
            finally:
                with self._socket_lock:
                    if self._socket is sock:
                        self._socket = None
                try:
                    sock.close()
                except OSError:
                    pass
                # A dropped link is a new session from the client's point of
                # view: stale readings must not linger as if still current.
                self.state.reset()
                self._set_status("disconnected")

    def _read_loop(self, sock: socket.socket) -> None:
        buf = b""
        while not self._closing.is_set():
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return  # peer closed the connection
            buf += chunk
            if len(buf) > MAX_LINE_BYTES * 4:
                return  # peer is misbehaving; drop rather than grow unboundedly
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self._handle_line(line)

    def _handle_line(self, raw: bytes) -> None:
        try:
            msg = decode(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return  # one bad line from the peer must not drop the connection
        if isinstance(msg, ChannelState):
            self.state.apply_channel_state(msg)
        elif isinstance(msg, HealthEvent):
            self.state.apply_health_event(msg)
        elif isinstance(msg, ConfigAck):
            with self._pending_lock:
                pending = self._pending.get(msg.request_id)
            if pending is not None:
                pending.ack = msg
                pending.event.set()
        # A ConfigRequest received here would be the wrong direction; ignore
        # rather than raise, matching the "one bad message" tolerance above.
