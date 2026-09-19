"""A deterministic, in-process stand-in for the QNX controller's telemetry/
config socket server -- lets the laptop-side client, and any voice-driven
config flow built on it, be developed and tested with no hardware attached.

Not a reference implementation of the controller: the real QNX side is
firmware-owned (see ../docs/controller_link_protocol.md for the exact wire
spec it must match). Every message this emits is tagged source_mode=
"simulated" so it can never be mistaken for a live sensor reading downstream.

Run standalone for manual testing against a real ControllerLinkClient:
    python -m controller_link.fake_server --port 8765
"""
from __future__ import annotations

import argparse
import socket
import threading
import time
from typing import Callable

from .protocol import (
    CHANNELS,
    SCHEMA_VERSION,
    ChannelState,
    ConfigAck,
    ConfigRequest,
    HealthEvent,
    decode,
    encode,
)

ReadingFn = Callable[[str, int], "tuple[int | None, str, str]"]


def default_reading(channel: str, tick: int) -> tuple[int | None, str, str]:
    """channel -> (distance_mm, band, health).

    'front' sweeps through every band in turn so a connected client can see
    band transitions without moving anything; 'left' always reports
    unknown/fault to exercise that path; every other channel holds a steady
    far reading.
    """
    if channel == "left":
        return None, "unknown", "fault"
    if channel == "front":
        cycle = ("far", "mid", "near", "urgent")
        band = cycle[tick % len(cycle)]
        distance = {"far": 2000, "mid": 1200, "near": 600, "urgent": 300}[band]
        return distance, band, "ok"
    return 2500, "far", "ok"


class FakeControllerServer:
    """One simulated controller process.

    Accepts one client connection at a time; a new connection replaces the
    previous one, since a real controller has no reason to refuse a
    reconnecting host. Config requests are validated against a single
    in-memory config_version, atomically accepted or rejected, matching
    CLAUDE.md §12's "reject atomically; retain the last accepted version".
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        source_id: str = "fake-controller",
        clock: Callable[[], float] = time.monotonic,
        telemetry_interval_s: float = 0.04,
        health_interval_s: float = 2.0,
        reading_fn: ReadingFn = default_reading,
    ) -> None:
        self._clock = clock
        self._source_id = source_id
        self._session_id = f"fake-{id(self)}-{int(clock() * 1000)}"
        self._telemetry_interval_s = telemetry_interval_s
        self._health_interval_s = health_interval_s
        self._reading_fn = reading_fn

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((host, port))
        self._socket.listen(1)
        self._socket.settimeout(0.5)

        self._sequence = 0
        self._sequence_lock = threading.Lock()
        self._config_version = 1
        self._config_lock = threading.Lock()

        self._conn: socket.socket | None = None
        self._conn_lock = threading.Lock()

        self._closing = threading.Event()
        self._accept_thread: threading.Thread | None = None
        self._sender_thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._socket.getsockname()[1]

    def start(self) -> None:
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True, name="fake-controller-accept")
        self._accept_thread.start()
        self._sender_thread = threading.Thread(target=self._send_loop, daemon=True, name="fake-controller-send")
        self._sender_thread.start()

    def close(self) -> None:
        self._closing.set()
        with self._conn_lock:
            conn = self._conn
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        try:
            self._socket.close()
        except OSError:
            pass
        for thread in (self._accept_thread, self._sender_thread):
            if thread is not None:
                thread.join(timeout=2)

    def drop_connection(self) -> None:
        """Forcibly close the current client connection without stopping the
        server, so a test or demo can exercise the client's reconnect path."""
        with self._conn_lock:
            conn = self._conn
            self._conn = None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass

    def _next_sequence(self) -> int:
        with self._sequence_lock:
            self._sequence += 1
            return self._sequence

    def _accept_loop(self) -> None:
        while not self._closing.is_set():
            try:
                conn, _addr = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            conn.settimeout(0.5)
            with self._conn_lock:
                old = self._conn
                self._conn = conn
            if old is not None:
                try:
                    old.close()
                except OSError:
                    pass
            reader = threading.Thread(target=self._read_loop, args=(conn,), daemon=True, name="fake-controller-read")
            reader.start()

    def _read_loop(self, conn: socket.socket) -> None:
        buf = b""
        while not self._closing.is_set():
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self._handle_line(conn, line)

    def _handle_line(self, conn: socket.socket, raw: bytes) -> None:
        try:
            msg = decode(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(msg, ConfigRequest):
            return  # wrong direction; ignore rather than raise
        with self._config_lock:
            if msg.base_config_version == self._config_version:
                self._config_version += 1
                result, reason = "accepted", None
            else:
                result, reason = "rejected", "version_conflict"
            active_version = self._config_version
        ack = ConfigAck(
            schema_version=SCHEMA_VERSION, msg_type="config_ack",
            source_id=self._source_id, session_id=self._session_id,
            sequence=self._next_sequence(), source_mode="simulated",
            ts_mono_ms=int(self._clock() * 1000),
            request_id=msg.request_id, result=result, reason=reason,
            active_config_version=active_version,
        )
        try:
            conn.sendall(encode(ack))
        except OSError:
            pass

    def _send_loop(self) -> None:
        tick = 0
        last_health = 0.0
        while not self._closing.is_set():
            with self._conn_lock:
                conn = self._conn
            now = self._clock()
            if conn is not None:
                for channel in CHANNELS:
                    distance, band, health = self._reading_fn(channel, tick)
                    with self._config_lock:
                        config_version = self._config_version
                    msg = ChannelState(
                        schema_version=SCHEMA_VERSION, msg_type="channel_state",
                        source_id=self._source_id, session_id=self._session_id,
                        sequence=self._next_sequence(), source_mode="simulated",
                        ts_mono_ms=int(now * 1000), channel=channel,
                        distance_mm=distance, age_ms=0, health=health, band=band,
                        config_version=config_version,
                    )
                    try:
                        conn.sendall(encode(msg))
                    except OSError:
                        break
                if now - last_health >= self._health_interval_s:
                    last_health = now
                    event = HealthEvent(
                        schema_version=SCHEMA_VERSION, msg_type="health_event",
                        source_id=self._source_id, session_id=self._session_id,
                        sequence=self._next_sequence(), source_mode="simulated",
                        ts_mono_ms=int(now * 1000), subsystem="controller",
                        state="ready", reason="", detected_age_ms=0, recovered=True,
                    )
                    try:
                        conn.sendall(encode(event))
                    except OSError:
                        pass
                tick += 1
            self._closing.wait(self._telemetry_interval_s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = FakeControllerServer(args.host, args.port)
    server.start()
    print(
        f"fake controller listening on {args.host}:{server.port} "
        f"(schema_version={SCHEMA_VERSION}, source_mode=simulated) -- Ctrl-C to stop"
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
