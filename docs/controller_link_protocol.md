# Controller link — wire protocol (schema_version 1)

**Audience:** whoever implements the QNX-side controller's telemetry/config
socket server. The companion-host (laptop) side is already implemented in
[`controller_link/`](../controller_link/) — `protocol.py` (message
definitions), `client.py` (the TCP client), and `fake_server.py` (a Python
stand-in for *this* spec, useful as a running reference implementation and
for testing the laptop side without QNX hardware).

**Read first:** repo root [`CLAUDE.md`](../CLAUDE.md) §4 (architecture and
ownership) and §7 (data contracts). This document is the wire-level
realization of the "Configuration and monitoring" path in §4. Nothing here
changes or overrides §8's proximity/haptic policy: this link is for
telemetry and config only and must have zero ability to affect motor
timing.

## 1. What this link is and isn't

- It carries **telemetry** (`ChannelState`, `HealthEvent`) from the
  controller to the laptop, and **config change requests/acks**
  (`ConfigRequest`/`ConfigAck`) from the laptop to the controller.
- It carries **no camera frames, no audio, no motor commands**. The laptop
  never tells the controller which motor to fire; it can only propose a
  bounded configuration change (e.g. alert distance), which the controller
  validates and may accept or reject.
- The controller's sensor-read → filter → band → haptic-command loop
  **must not** block on this link in any way — not on `accept()`, not on a
  slow/blocked TCP `send()`, not on JSON encoding. If the link is absent,
  slow, or disconnected, the controller's local loop is unaffected
  (CLAUDE.md §4: "Sensor acquisition and motor timing must not block on
  HTTP, speech synthesis, model inference, log writes, or UI connections").
  In practice this means: telemetry send failures/backpressure are dropped
  or handled on a separate thread/task from the sensor-scheduling loop, not
  inline with it.

## 2. Transport

- Plain TCP. The controller is the **server** (listens on a fixed port); the
  laptop is the **client** and initiates the connection, with its own
  reconnect/backoff already implemented in `controller_link/client.py`. This
  means the controller doesn't need to implement any retry logic — just
  accept connections and serve them.
- One accepted connection at a time is sufficient for the hackathon scope
  (one companion host). If a new connection arrives while one is open, it is
  fine (and simplest) to just accept it and drop the old one, mirroring
  `fake_server.py`'s behavior — the controller has no reason to refuse a
  reconnecting host.
- **Framing:** each message is one UTF-8 JSON object followed by `\n`
  (newline). No length prefix, no other delimiter. Read/parse until a `\n`,
  then parse everything before it as one JSON object.
- **Message size bound:** no line should exceed 4096 bytes
  (`MAX_LINE_BYTES` in `protocol.py`). Every message type here is small and
  flat, so this is generous headroom, not a tight constraint.
- **No handshake.** A message's own fields (`source_id`, `session_id`, …)
  carry everything needed; just start sending telemetry once a connection is
  accepted, and start parsing incoming lines for `config_request` messages.

## 3. Every message's common envelope

All four message types share these fields (flat on the same JSON object, not
nested):

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Always `1` for this spec. A receiver seeing a different value should treat the message as invalid. |
| `msg_type` | string | One of `"channel_state"`, `"health_event"`, `"config_request"`, `"config_ack"`. |
| `source_id` | string, non-empty | Identifies the sending process, e.g. `"qnx-controller-01"`. Stable for that process's lifetime. |
| `session_id` | string, non-empty | Identifies the sending process's **run**. Must change whenever the controller restarts (e.g. a UUID generated at process start), so the laptop can tell "the controller rebooted" from "just a normal reconnect". Must **not** change on every message. |
| `sequence` | int ≥ 0 | Increases by exactly 1 for every message this `source_id` sends within one `session_id` (a single counter shared across `channel_state`/`health_event`/`config_ack`, incrementing on each one — see `fake_server.py`'s `_next_sequence()`). Restart the counter (e.g. at 0 or 1) only when `session_id` changes. |
| `source_mode` | string | `"live"` (real hardware), `"simulated"`, or `"replay"`. Real controller firmware sends `"live"`. |
| `ts_mono_ms` | int ≥ 0 | The sender's own monotonic clock, milliseconds, at message construction. **The receiver must never subtract this from its own clock** — see §6. It exists for the controller's own diagnostics/logging correlation, not for the laptop to compute age. |

The laptop-side receiver rejects (drops, without crashing the connection) any
line that has an unknown `msg_type`, is missing a required field, has an
extra/unknown field, or fails a field's own validation (e.g. `sequence` is
negative). Build the sender to avoid ever emitting such a line, but design
the receiver on your side the same defensive way if you're also consuming
this link somewhere.

## 4. `channel_state` (controller → laptop)

One direction's current filtered reading. Send one of these per channel per
telemetry cycle — see §7 for the target rate.

| Field | Type | Notes |
| --- | --- | --- |
| `channel` | string | One of the 8 channel names below. |
| `distance_mm` | int > 0, or `null` | The **filtered** distance in millimetres. `null` for "no usable reading" — never `0`, `-1`, or a max-range sentinel (CLAUDE.md §7). |
| `age_ms` | int ≥ 0 | How old the underlying raw measurement was *at the moment this message was sent*, using the controller's own clock. Not the age at the moment the laptop reads it. |
| `health` | string | `"ok"`, `"fault"`, or `"unknown"` — this channel's own status, independent of `band`. |
| `band` | string | `"far"`, `"mid"`, `"near"`, `"urgent"`, `"beyond_alert_range"`, or `"unknown"`. Must be `"unknown"` whenever `distance_mm` is `null` — the two must not disagree (a `band` other than `"unknown"` implies a real `distance_mm`, and `"unknown"` must carry a `null` `distance_mm`). |
| `config_version` | int ≥ 0 | The calibration/configuration version this reading was produced under. |

Channel names, in the fixed wearer-relative order (repo root CLAUDE.md §5 —
this table must stay identical everywhere: firmware, this link, tests, the
monitor):

| `channel` | Bearing | Motor |
| --- | --- | --- |
| `front` | 0° | `motor_0` |
| `front_right` | 45° | `motor_1` |
| `right` | 90° | `motor_2` |
| `rear_right` | 135° | `motor_3` |
| `rear` | 180° | `motor_4` |
| `rear_left` | 225° | `motor_5` |
| `left` | 270° | `motor_6` |
| `front_left` | 315° | `motor_7` |

Example line (front channel, mid-range, healthy):

```json
{"schema_version":1,"msg_type":"channel_state","source_id":"qnx-controller-01","session_id":"3f1c...","sequence":842,"source_mode":"live","ts_mono_ms":1234567,"channel":"front","distance_mm":1200,"age_ms":18,"health":"ok","band":"mid","config_version":3}
```

A disconnected/faulted sensor (no fabricated distance, ever):

```json
{"schema_version":1,"msg_type":"channel_state","source_id":"qnx-controller-01","session_id":"3f1c...","sequence":843,"source_mode":"live","ts_mono_ms":1234571,"channel":"left","distance_mm":null,"age_ms":0,"health":"fault","band":"unknown","config_version":3}
```

## 5. `health_event` (controller → laptop)

A subsystem-level health transition (not per-channel — use `channel_state`'s
own `health` field for that). Send one whenever a subsystem's derived state
changes, plus optionally a periodic heartbeat (e.g. every 1–2 s) for
`subsystem="controller"` so the laptop can positively confirm the controller
process itself is alive and looping, not just that the TCP connection is up.

| Field | Type | Notes |
| --- | --- | --- |
| `subsystem` | string, non-empty | e.g. `"controller"`, `"sensor_front"`, `"motor_driver"`, `"power"`. |
| `state` | string | `"starting"`, `"ready"`, `"partial"`, `"paused"`, or `"fault"` (CLAUDE.md §12's derived states). |
| `reason` | string | Short reason code; `""` is fine when `state` doesn't need one (e.g. a routine `"ready"` heartbeat). |
| `detected_age_ms` | int ≥ 0 | How long ago (controller's own clock) this state was detected, at send time. |
| `recovered` | bool | `true` if this event reports recovery from a prior fault for this subsystem. |

## 6. Clocks — read this before implementing anything that computes an "age"

The controller's monotonic clock and the laptop's monotonic clock are two
different clocks with no shared epoch. **Never send an absolute timestamp
expecting the other side to diff it against its own clock.** This spec
avoids that entirely:

- Telemetry reports **its own age** (`age_ms` / `detected_age_ms`) computed
  entirely on the controller's clock, at send time. The laptop adds a
  receipt-to-now delta computed entirely on *its own* clock
  (`ControllerState.total_age_s()`) — two single-clock measurements added
  together, never a cross-clock subtraction.
- Config requests carry a **relative** `ttl_ms` (§7 below), not an absolute
  deadline, for the identical reason: the controller computes its own
  deadline as *(its own receipt time + ttl_ms)*, never by comparing to a
  timestamp the laptop generated on its own clock.

If you add any other time-bearing field to this protocol later, apply the
same rule.

## 7. `config_request` (laptop → controller) and `config_ack` (controller → laptop)

`config_request`:

| Field | Type | Notes |
| --- | --- | --- |
| `request_id` | string, non-empty | Opaque; echo it back unchanged in the `config_ack`. |
| `base_config_version` | int ≥ 0 | The config version the laptop believes is active. |
| `intent` | string | One of `set_alert_distance_mm`, `set_sensitivity_preset`, `set_haptic_comfort_level`, `pause_feedback`, `resume_feedback`. |
| `param_name` | string or `null` | e.g. `"alert_distance_mm"`. `null` when `intent` needs no parameter (e.g. `pause_feedback`). |
| `param_value_num` | number or `null` | The parameter's numeric value, if any. |
| `param_value_str` | string or `null` | The parameter's string value, if any (e.g. a named preset). |
| `ttl_ms` | int > 0 | Relative to this message's send time (see §6) — treat the request as expired if it wasn't processed within this window of your own receipt time. |

Required controller behavior on receiving a `config_request`:

1. **Validate atomically.** If `base_config_version` doesn't match your
   current version, or the value is out of the hardware/comfort-limit range,
   or `ttl_ms` has already elapsed since receipt, **reject** — never
   partially apply a change (CLAUDE.md §12: "Invalid configuration arrives →
   Reject it atomically; retain the last accepted version").
2. **Never let this block the sensor/haptic loop.** Apply an accepted change
   at a safe point in your own scheduling (e.g. between sensor cycles), not
   by pausing an in-flight sensor read.
3. **Always reply** with exactly one `config_ack` per `config_request`
   received (even a rejection — the laptop is waiting on this to report back
   to the user; CLAUDE.md §11: "Never announce an unacknowledged change").

`config_ack`:

| Field | Type | Notes |
| --- | --- | --- |
| `request_id` | string, non-empty | Must match the `config_request` this answers. |
| `result` | string | `"accepted"` or `"rejected"`. |
| `reason` | string or `null` | **Required** (non-empty) when `result` is `"rejected"` — e.g. `"version_conflict"`, `"out_of_range"`, `"expired"`, `"unknown_intent"`. `null` is fine on acceptance. |
| `active_config_version` | int ≥ 0 | The config version now in effect, whether or not this request changed it. |

Example accepted round trip:

```json
{"schema_version":1,"msg_type":"config_request","source_id":"companion-host","session_id":"a91e...","sequence":12,"source_mode":"live","ts_mono_ms":998877,"request_id":"7c2b...","base_config_version":3,"intent":"set_alert_distance_mm","param_name":"alert_distance_mm","param_value_num":2000.0,"param_value_str":null,"ttl_ms":1500}
```
```json
{"schema_version":1,"msg_type":"config_ack","source_id":"qnx-controller-01","session_id":"3f1c...","sequence":844,"source_mode":"live","ts_mono_ms":1234580,"request_id":"7c2b...","result":"accepted","reason":null,"active_config_version":4}
```

## 8. Target rates (goals to measure, not guarantees — CLAUDE.md §9)

- Aim to cycle all 8 channels within ≤ 200 ms (one `channel_state` line per
  channel per cycle), matching the per-channel revisit goal in CLAUDE.md §9.
  `fake_server.py`'s default (`telemetry_interval_s=0.04`, i.e. one channel
  every 40 ms) is a reasonable starting point.
- A `health_event` heartbeat for `subsystem="controller"` every 1–2 s is
  enough for the laptop to distinguish "controller alive but quiet" from
  "controller gone" — the latter is instead detected by the TCP connection
  itself dropping (see `controller_link/client.py`'s `stale_after_ms`
  handling for the former).
- None of this needs to be exact. Report actual measured rates once the real
  hardware exists rather than assuming these numbers hold (CLAUDE.md §9's
  general rule for every timing figure in this project).

## 9. Implementing the JSON on the QNX/C side

Every message here is a **flat** JSON object — no nested arrays or objects —
specifically so this is tractable without pulling in a heavy JSON library:

- **Sending** is simplest done by hand with `snprintf` into a fixed buffer,
  field by field, in any order (the receiver doesn't require field order).
  Watch out for the two "or null" fields (`distance_mm`, `param_name`, etc.)
  — write the literal `null` (no quotes) when absent, not an empty string or
  a sentinel number.
- **Receiving** (parsing `config_request` lines) does need real JSON
  parsing, since field order/whitespace from the sender isn't something you
  control. A single-header, allocation-free parser such as
  [`jsmn`](https://github.com/zserge/jsmn) (MIT-licensed, tokenizes; you
  still map tokens to fields yourself) is a good fit for a resource-managed
  QNX process and avoids pulling in a full JSON library. Validate every
  field the same way this spec's Python side does (§3–§7 tables) — reject
  and drop malformed input rather than crashing or guessing a default.
- Keep the accept/read/parse/reply loop off the sensor-scheduling thread —
  a dedicated thread or a QNX resource-manager-style async handler for this
  socket is consistent with CLAUDE.md §4's "one local coordinator" guidance
  and the non-blocking requirement in §1 above.

## 10. Reference implementation

`controller_link/fake_server.py` (Python) implements this exact spec end to
end — telemetry generation, `config_request` validation and atomic
accept/reject, `config_ack` replies — and is the thing
`controller_link/client.py` is tested against
(`controller_link/tests/test_client_fake_server.py`). Running it
(`python -m controller_link.fake_server --port 8765`) and pointing a real
`ControllerLinkClient` at it is a fast way to sanity-check a new QNX
implementation's output: the laptop-side client accepts and rejects lines
identically either way, since both go through the same `protocol.decode()`.
