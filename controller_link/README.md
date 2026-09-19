# controller_link/

Companion-host (laptop) side of the link to the QNX controller. This is the
"Configuration and monitoring" path from the repo root
[`CLAUDE.md`](../CLAUDE.md) §4 -- small, infrequent telemetry and
config-change messages between the laptop (vision/speech/assistant) and the
QNX controller (sensors/haptics). It carries no camera frames or audio, and
the controller's local proximity-to-haptic loop is unaffected by this link
being absent, slow, or entirely down.

The QNX-side server is **not implemented here** -- it's firmware-owned. See
[`../docs/controller_link_protocol.md`](../docs/controller_link_protocol.md)
for the exact wire spec it needs to implement to interoperate with this
package. [`fake_server.py`](fake_server.py) is a Python stand-in for that
server so this side, and anything built on top of it, can be developed and
tested without any hardware.

## Contents

| File | Role |
| --- | --- |
| `protocol.py` | Message types (`ChannelState`, `HealthEvent`, `ConfigRequest`, `ConfigAck`), `encode`/`decode`, all field validation |
| `config.py` | `ControllerLinkConfig`, loaded from `configs/controller_link.json` |
| `state.py` | `ControllerState`: thread-safe latest per-channel/per-subsystem telemetry, session- and sequence-aware |
| `client.py` | `ControllerLinkClient`: background-thread TCP client with reconnect/backoff, bounded config-request/ack correlation |
| `fake_server.py` | Deterministic simulated controller for local dev/tests (`python -m controller_link.fake_server`) |
| `tests/` | Protocol validation, state aggregation, and a real-socket integration suite against the fake server |

## Quick use

```python
from controller_link import ControllerLinkClient, ControllerLinkConfig

cfg = ControllerLinkConfig.load("configs/controller_link.json")
link = ControllerLinkClient(cfg)
link.start()

# Somewhere in a status handler (e.g. main.py's "device status" command):
print(link.status)                      # "disconnected" | "ready" | "stale"
front = link.state.channel("front")     # ChannelReading | None
if front is not None:
    print(front.state.distance_mm, front.state.band, link.state.total_age_s(front))

# Somewhere in a voice-driven config handler:
outcome = link.send_config_request(
    "set_alert_distance_mm", base_config_version=3,
    param_name="alert_distance_mm", param_value_num=2000.0,
)
print(outcome.status, outcome.ack)      # "acked" | "timeout" | "link_unavailable"

link.close()
```

Try it against the fake controller in another terminal:

```bash
python -m controller_link.fake_server --port 8765
```

(and point `configs/controller_link.json`'s `host`/`port` at `127.0.0.1:8765`
for that manual test).

## Design notes

- **Latest-only, not a queue.** `ControllerState` mirrors
  `computer-vision/scene_state.py`'s `SceneState`: one writer (the client's
  reader thread), many readers, no backlog. A channel or subsystem with no
  entry is unknown -- callers must not assume "far" or "clear" from silence.
- **Any disconnect resets state.** `ControllerLinkClient` calls
  `state.reset()` whenever a connection ends, for any reason, so a stale
  reading can never be displayed as current across an outage (CLAUDE.md §4:
  "Reconnects reset session-specific state").
- **Sequence and session bookkeeping live in `ControllerState`, not the
  socket layer.** A `session_id` change (the controller restarted, or this
  is genuinely a different process) clears prior sequence counters; within a
  session, an out-of-order or duplicate `sequence` is rejected rather than
  applied (CLAUDE.md §7: "Reject buffered, expired, repeated, or
  out-of-order observations").
- **No cross-clock math.** Every message reports its own age
  (`age_ms`/`detected_age_ms`) using the sender's own clock.
  `ControllerState.total_age_s()` adds that to a receipt-to-now delta
  measured entirely on the reader's own clock -- it never diffs the
  controller's monotonic clock against the laptop's (CLAUDE.md §7's
  clock-mapping rule). The same reasoning is why `ConfigRequest.ttl_ms` is
  relative, not an absolute deadline.
- **Bounded and non-blocking for callers.** `send_config_request()` waits at
  most `ttl_ms` plus a small margin and always returns a `ConfigOutcome`
  (`"acked"`, `"timeout"`, or `"link_unavailable"`) -- never blocks
  indefinitely, and never fabricates an ack (CLAUDE.md §11: "Never announce
  an unacknowledged change").
- **One bad line never drops the link.** `decode()` raises `ValueError` on
  anything malformed, oversized, or with an unknown/missing field; both the
  client's read loop and the fake server's catch this per line and keep
  going, so a single corrupt or unexpected message from a peer can't tear
  down the connection.

## Tests

```bash
python3 -m unittest discover -s controller_link/tests -p 'test_*.py' -v
```

All offline: no camera, mic, sensors, or external network -- the integration
suite talks to `fake_server.py` over real loopback TCP sockets, which
exercises the actual socket code path without needing hardware.

## Not done here (by design, per current scope)

- The actual QNX-side server. `docs/controller_link_protocol.md` specifies
  exactly what it must send/accept to work with this client; the fake server
  is a reference for behavior, not for its C/QNX implementation.
- Wiring this client into `main.py`'s orchestrator (e.g. extending the
  `"device status"` voice command to report link/channel health, or a live
  monitor view). Both are straightforward additions once the QNX side exists
  to test against.
