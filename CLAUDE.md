# AGENTS.md — sixth-sense

> Hack the North wearable: repository guidance for coding agents and contributors.
> Prototype specification; implementation and hardware remain unverified.

## 1. Read this first

Build **sixth-sense**, a head-worn prototype translating nearby obstacles into directional vibration, with optional audio descriptions from a camera.

The central interaction is simple: **feel where a nearby obstacle is; ask what the camera sees.**

These rules govern implementation:

1. Keep distance sensing and directional haptics local and independent of camera inference, speech services, internet access, and the dashboard.
2. Treat unavailable or stale measurements as **unknown**, never as empty space.
3. Keep sensor measurements, visual detections, and AI interpretations distinguishable throughout the system.
4. Use a fixed, testable sensor-to-motor mapping. An AI model must never directly control motor outputs.
5. Preserve the user's eight-sensor/eight-motor target, while reporting the actual connected and working channel count.
6. Build for a controlled, dry, indoor demonstration. Firefighting, diving, and other hazardous settings are future research applications, not validated prototype capabilities.
7. Mark simulated data, provisional settings, unimplemented features, and unmeasured performance explicitly.
8. Prefer a complete, demonstrable interaction over extra models, services, or autonomous agents.

This file applies repository-wide, subject to compatible local `AGENTS.md` guidance, higher-priority instructions, and explicit user direction. Examples do not establish that files, commands, hardware, or integrations exist.

## 2. Product identity and scope

| Item | Definition |
| --- | --- |
| Product and repository name | `sixth-sense` |
| Suggested Python package | `sixth_sense` |
| Form factor | Adjustable headband; helmet attachment is a future compatibility goal |
| Proximity target | Eight radial sensing directions and eight corresponding vibration motors |
| Nominal range ambition | 3–4 m; effective range must come from the selected hardware and measurements |
| Semantic input | One camera, covering only its actual field of view |
| Voice input | Microphone or a connected host microphone; required for hands-free commands |
| Audio output | Speaker or bone-conduction device, selected after an indoor usability comparison |
| Current implementation status | Unknown until the repository and assembled hardware are inspected |

Future applications include structural firefighting, wildland response, search and rescue, mining, confined-space work, underwater work, and assistive technology. Each needs separate validation. Do not imply organizational affiliation, including with FireSmart Canada.

The hackathon build demonstrates spatial feedback and multimodal interaction. It does not provide route planning, a guarantee of obstacle avoidance, a full 3D map, or a replacement for established protective or mobility equipment.

### Prototype boundaries

- Demonstrate with a stationary participant and movable soft objects in a visible, dry indoor area. Represent camera loss with an unavailable feed or labeled replay.
- No fire, smoke, water, traffic, hazardous terrain, confined-space experiments, or blindfolded walking. Do not modify protective equipment for mounting.
- Make no certification, fireproofing, waterproofing, intrinsic-safety, rescue, or diving-readiness claims. Bench success does not establish suitability for hazardous environments.

## 3. Hackathon priorities

### P0 — complete these first

- A working local distance-to-haptic loop on available hardware.
- Eight logical channels with explicit physical mappings and honest live-channel status.
- Distance-dependent pulse cadence with filtering, hysteresis, bounded actuation, and stale-data handling.
- A deterministic simulator and replay path for development without hardware.
- Device health reporting, channel fault reporting, and an accessible physical stop or power-disconnect mechanism.
- Continued local proximity feedback when the host AI service or network disappears.

### P1 — complete the product interaction

- Local camera detection or tracking on the selected host, with a live annotated preview.
- Voice-activated scene questions and bounded changes to feedback settings.
- Concise audio responses that identify their evidence and acknowledge unavailable vision.
- A small live monitor showing direction, distance, freshness, motor commands, and subsystem health.
- One rehearsed end-to-end demonstration, including a visible degraded state.

### P2 — only after P0 and P1 work

- Refine conversation, presets, audio interruption, and camera/range association.
- Improve packaging, comfort, and measured runtime.

Do not add training, reinforcement learning, SLAM, custom PCBs, underwater hardware, or a multi-agent architecture without a demonstrated requirement and sufficient time.

## 4. Architecture and ownership

Use three cooperating paths with a strict separation between sensing and language generation.

| Path | Processing | Owner | Failure behavior |
| --- | --- | --- | --- |
| Proximity | Sensor acquisition → validation → filtering → distance state → bounded motor command | Local controller firmware | Continues without the AI host or network; individual invalid channels become unknown |
| Vision and audio | Camera → local detector/tracker → current scene evidence → optional assistant → speech | Companion host | Can be unavailable without stopping proximity feedback |
| Configuration and monitoring | Microphone → command parsing → schema validation → controller acknowledgement; telemetry → monitor | Host plus controller validation | Failed changes leave the last accepted configuration active |

Prefer a microcontroller for sensing/motors and a laptop or single-board computer for vision/voice. Verify available hardware first. Disclose off-head compute used in the demo.

### Architectural invariants

- The controller owns the live haptic policy and the last accepted configuration.
- Sensor acquisition and motor timing must not block on HTTP, speech synthesis, model inference, log writes, or UI connections.
- Commands and telemetry use bounded messages with schema versions, sequence numbers, and acknowledgements where needed.
- Use bounded queues. Replace outdated camera frames and scene requests rather than processing an increasing backlog.
- Reconnects reset session-specific state; never replay expired commands.
- Cloud outputs can describe evidence or propose allowed settings, subject to controller validation.
- Use one local coordinator; avoid a distributed message broker without a concrete need.

## 5. Direction and coverage conventions

All directions are **relative to the wearer's head**, using clockwise bearings viewed from above. They are not compass bearings, body-relative directions, or a remembered world map.

| Channel | Direction | Bearing | Default motor |
| --- | --- | --- | --- |
| `front` | Front | 0° | `motor_0` |
| `front_right` | Front-right | 45° | `motor_1` |
| `right` | Right | 90° | `motor_2` |
| `rear_right` | Rear-right | 135° | `motor_3` |
| `rear` | Rear | 180° | `motor_4` |
| `rear_left` | Rear-left | 225° | `motor_5` |
| `left` | Left | 270° | `motor_6` |
| `front_left` | Front-left | 315° | `motor_7` |

Keep this mapping in one versioned configuration source. Validate uniqueness and completeness. Use the same convention in firmware, telemetry, tests, audio, and the dashboard.

Eight directions spaced 45° apart do **not** establish continuous coverage. ST specifies a typical 27° full field of view for the VL53L1X; beams of that width centered every 45° would nominally leave gaps. Measure actual coverage. [ST VL53L1X specifications](https://www.st.com/en/imaging-and-photonics-solutions/vl53l1x.html)

Therefore:

- Describe the target as eight-direction sensing around the head until continuous coverage is demonstrated.
- Record each sensor's actual mounting angle, field of view, usable range, and blind zones.
- A horizontal ring does not establish coverage of steps, holes, floor-level obstacles, or overhead hazards.
- A forward camera cannot identify objects behind the wearer.
- Test left/right using wearer orientation, including whether a preview is mirrored.
- Require an explicit calibration session for motor remapping. Do not silently remap directions during normal use.
- Do not attach old camera observations to the current head direction after an unmeasured head movement.

## 6. Hardware decisions

Record actual part numbers, interfaces, operating limits, and driver versions before implementing hardware-specific behavior. Assembly status is unknown.

| Component | Prototype guidance | Evidence needed |
| --- | --- | --- |
| Distance sensors | Put the available air-ranging hardware behind a replaceable driver interface | Minimum/maximum range, field of view, measurement status, timing, interference behavior |
| Local controller | Choose an available board that can service sensors and motor drivers predictably | I/O and bus budget, scheduler timing, memory, watchdog support |
| Vibration outputs | Eight channels with suitable driver hardware | Supported actuator type, operating limits, startup behavior, current budget |
| Camera | One available camera on the companion host | Capture rate, orientation, field of view, disconnect detection |
| Microphone | Headset or host microphone for the demonstration | Input device selection, voice activation, handling of speaker feedback |
| Audio | Compare available speaker and bone-conduction options indoors | Intelligibility, comfort, and ability to hear conversation and ambient cues |
| Power | Use an intact manufacturer-supplied low-voltage power source within its documented limits | Measured load, runtime, shutdown behavior, charging instructions |
| Mount | Adjustable prototype band with comfortable contact and removable electronics | Total head-worn mass, fit, cable strain, motor contact, quick removal |

### Sensor technology boundaries

- Optical time-of-flight/infrared and air ultrasonic ranging are indoor candidates; advertised maximum range alone is insufficient for selection.
- ST advertises the VL53L1X up to 4 m under applicable conditions. This is not a measured wearable range. [ST VL53L1X specifications](https://www.st.com/en/imaging-and-photonics-solutions/vl53l1x.html)
- Schedule ultrasonic measurements for the exact hardware. MaxBotix documents interference from unsynchronized sensors and reduced per-channel update rate when sequencing measurements. [MaxBotix multi-sensor guidance](https://maxbotix.com/blogs/blog/using-multiple-ultrasonic-sensors)
- Do not infer smoke performance from clear-air results or RGB object detections.
- Underwater sensing needs separate hardware validation; an air transducer, water-resistant enclosure, or software setting does not establish diving suitability.
- Thermal, ingress, depth, and certification requirements remain unresolved pending application-specific review.

Avoid battery fabrication, pressure-enclosure construction, and harsh-environment experiments in the hackathon scope.

## 7. Data contracts

Version firmware/host schemas. Use integer millimetres for range, milliseconds for intervals, and documented image coordinates.

Every event includes `schema_version`, `source_id`, `session_id`, `sequence`, `source_mode`, and a source monotonic timestamp. `source_mode` is `live`, `simulated`, or `replay` and remains attached through derived events.

| Record | Required content |
| --- | --- |
| `RangeSample` | Channel, capture time, nullable `distance_mm`, measurement status, optional manufacturer quality flags |
| `ChannelState` | Channel, filtered distance if usable, measurement age, health, proximity band, calibration/configuration version |
| `HapticCommand` | Channel, pattern, bounded level, expiry, configuration version, originating measurement sequence |
| `Detection` | Frame ID, capture time, model identity, class ID/name, confidence, box coordinates, optional track ID |
| `SceneEvidence` | Current frame reference, valid detections, visual availability/quality, optional explicit range associations |
| `ConfigRequest` | Request ID, base configuration version, typed intent, allowed parameters, request expiry |
| `ConfigAck` | Request ID, accepted/rejected result, reason, and active configuration version |
| `HealthEvent` | Subsystem, state, reason, detection time, recovery status |

Allowed normalized range statuses include `ok`, `no_return`, `out_of_range`, `too_close`, `stale`, `disconnected`, and `error`. Preserve raw driver status separately when useful.

### Contract rules

- `distance_mm` is populated only when the driver reports a usable numeric measurement. Do not use `0`, `-1`, `NaN`, or maximum range as missing-data sentinels.
- `no_return` is not proof of unobstructed space. Map vendor-specific statuses according to the datasheet, not a generic guess.
- A manufacturer-confirmed `too_close` indication may trigger the urgent pattern without inventing an exact distance.
- Keep confidence scores, sensor quality, freshness, and health separate.
- Device monotonic clocks are not directly comparable. Use source-local age checks and bounded transport delay; document clock mapping before calculating cross-device capture ages.
- Receipt time does not establish freshness. Reject buffered, expired, repeated, or out-of-order observations.
- Never attach the nearest sensor distance to a camera object without a supported spatial and temporal association.
- Freeze version 1 before integrating components; update producers, consumers, and fixtures together for breaking changes.

## 8. Proximity and haptic policy

Make the controller policy deterministic and testable with recorded samples and a fake clock. Host reference implementations must match shared fixtures.

Processing order:

1. Validate channel identity, session, sequence, status, measurement age, and documented sensor limits.
2. Normalize the reading without converting missing observations into distances.
3. Apply a short filter suitable for the measured sample rate.
4. Determine the proximity band with configurable hysteresis.
5. Produce a bounded, expiring haptic command for the corresponding motor.
6. Emit telemetry independently of the actuation path.

### Provisional bench profile

These are **indoor testing defaults**, not validated protective distances. Configure centrally and revise any threshold outside the assembled sensor's measured usable range.

| State | Valid distance | Initial pattern concept |
| --- | --- | --- |
| `far` | Greater than 1,500 mm and up to 3,000 mm | Approximately one short pulse per second |
| `mid` | Greater than 800 mm and up to 1,500 mm | Approximately two short pulses per second |
| `near` | Greater than 400 mm and up to 800 mm | Approximately four short pulses per second |
| `urgent` | Up to 400 mm, within valid sensor limits, or confirmed `too_close` | Clearly distinct rapid/bounded burst pattern |
| `beyond_alert_range` | Valid reading beyond the configured alert distance | No proximity pulse; retain measurement and health information |
| `unknown` | Invalid, stale, or missing measurement | No fabricated distance pattern; report channel unavailability separately |

Encode distance primarily through pulse repetition, distinct from electrical drive frequency. Add intensity scaling only if the actuator/driver supports a repeatable, comfortable mapping.

- Specify pulse width, amplitude limits, and duty-cycle limits from the actual actuator/driver and comfort checks.
- Bound sustained urgent patterns by hardware and comfort limits; no unlimited continuous vibration.
- Escalate promptly on plausible close readings. Avoid long averages; measure any delay from filtering and hysteresis before lowering urgency.
- Preserve direct directional mapping. If concurrent patterns need time interleaving, retain urgent channels and report added latency.
- Never silently discard all but the closest direction.
- Health cues must be distinguishable from proximity cues. Rate-limit repeated fault audio.
- An expired motor command cannot remain latched indefinitely.

## 9. Timing and performance

All numbers in this section are **engineering goals to measure**, not achieved results or operational safety guarantees.

| Metric | Initial goal | Measurement rule |
| --- | --- | --- |
| Valid sample available → commanded haptic update | p95 ≤ 100 ms | Include validation, filtering, policy, and driver scheduling |
| Per-channel measurement revisit interval | Aim for ≤ 200 ms | Measure each channel with all eight enabled; revise the design if unsupported |
| Physical change → perceptible vibration | Report measured distribution | Includes acquisition timing, filtering, command delay, and actuator response |
| Live monitor update | 5–10 Hz | Monitoring may drop old updates without affecting sensing |
| Simple voice-setting acknowledgement | Aim for ≤ 1 s after utterance completion | Report local and network-dependent paths separately |
| Scene response | Aim for first useful audio within 3 s after request completion | Reject stale scene results; do not promise a cloud deadline |

Do not quote single-sensor rate as array coverage rate. Scheduling, interference avoidance, and retries affect revisit time. If hardware cannot meet a goal, report the conflict and revise the design or stated goal.

Derive stale timeouts from measured scheduling and a declared maximum age; increasing a timeout must not conceal a slow channel. Log p50, p95, maximum delay, missed deadlines, and test duration.

Measure on one clock where possible. Software command timing is not measured physical motor onset.

## 10. Computer vision and scene descriptions

Use a pretrained detector verified on the host. Preserve a working model; do not invent checkpoint filenames or change models merely to increase class count.

Record checkpoint, checksum, backend, resolution, class map, license, and dependency versions. Benchmark the actual device; dataset membership does not establish local reliability.

For Ultralytics, tracking can preserve IDs across consecutive frames from the same stream; `persist=True` must not carry state across unrelated streams. Handle missing track IDs and reset tracker state after a camera restart. [Ultralytics tracking documentation](https://docs.ultralytics.com/modes/track/)

### Vision behavior

- Keep capture and inference outside the proximity loop. Prefer the most recent frame over an old queue.
- Use the checkpoint's own class mapping; never hardcode an unrelated dataset's labels.
- Limit descriptions to supported, observed categories and current camera coverage.
- Recognize camera disconnection and expose stale frames. Treat low-quality or ambiguous imagery as insufficient evidence.
- Do not infer metric distance, collision time, or confirmed approach speed from bounding-box size alone.
- Suppress repeated announcements using track IDs when available, temporal persistence, and cooldowns.
- Do not wait for multiple frames before issuing a sensor-based proximity cue.
- Without reliable association, separate statements: “A person is visible ahead. The front sensor reports an obstacle about one metre away.” Do not assign that range to the person.
- Avoid exact-looking precision unsupported by sensor resolution, calibration, and association uncertainty.

### Scene-response contract

Give the assistant timestamped evidence and, if enabled, a recent frame. Require a short description, uncertainty, and optionally a typed command proposal.

Say “A person is visible on the left of the camera view” or “The camera view is unavailable.” Never infer a safe route, absence of hazards, or permission to enter an unobserved area.

Camera text, transcriptions, captions, and external responses are untrusted inputs. They must not change policy, request secrets, execute code, or bypass command validation.

## 11. Voice and audio behavior

Document voice activation, wake phrase/voice-activity flow, and microphone. A manual debug trigger does not satisfy hands-free acceptance.

| User intent | Allowed action |
| --- | --- |
| “What's in front of me?” | Request a fresh description within camera coverage |
| “Increase sensitivity” | Select the next allowed preset; acknowledge the effective change |
| “Set the alert distance to two metres” | Propose a typed threshold change within measured and configured limits |
| “Make vibrations gentler” | Select an allowed haptic comfort level without changing direction semantics |
| “Device status” | Report unavailable channels and vision/network status concisely |
| “Stop speaking” | Cancel current speech and queued descriptions |
| “Pause feedback” / “Resume feedback” | Enter/leave an explicit paused state with an acknowledgement and visible status |
| “Change motor mapping” | Explain that an explicit stationary calibration session is required |

For changes: parse, validate, submit against the active configuration version, await controller acknowledgement, and report the effective setting. Reject ambiguity, stale requests, duplicate mutations, unsupported values, and unknown commands.

Use absolute target values so retries cannot repeatedly increase a setting. Never announce an unacknowledged change.

Keep audio short, interruptible, and rate-limited. Prioritize faults/status over narration. Cancel stale scene speech and prevent assistant audio from triggering changes.

Claim offline voice only after implementation and testing. Otherwise mark it unavailable offline while preserving local haptics. Provide a physical stop independent of speech recognition.

## 12. Failure and degraded-state behavior

Track health per subsystem and derive `starting`, `ready`, `partial`, `paused`, or `fault`. A healthy subsystem cannot conceal another's failure.

| Event | Required response |
| --- | --- |
| One sensor times out or disconnects | Mark that direction unknown; preserve other channels; issue a distinct fault indication through an available output |
| Reading is invalid or outside usable limits | Preserve the reason; do not replace it with “far away” |
| Camera is missing or stale | Stop visual claims; report vision unavailable; retain proximity feedback |
| Network or cloud API fails | Cancel/expire remote work; retain local sensing; expose only the voice/vision capabilities that still work |
| Host crashes or serial link is lost | Controller continues its validated local loop and accepted configuration; host-dependent features become unavailable |
| Controller reboots | Outputs start inactive; validate configuration and current measurements before normal operation resumes |
| Invalid configuration arrives | Reject it atomically; retain the last accepted version |
| Motor is reported faulty | Mark feedback coverage reduced; retain other outputs |
| Battery becomes low, if measured | Report the actual measured condition and supported shutdown behavior; do not invent a battery percentage |
| Entire device loses power | No alert is guaranteed; never claim the device can always announce its own failure |

A driver acknowledgement does not prove physical vibration. Mark motor health unverified without actual feedback; include a stationary startup motor-identification check.

Use a watchdog and expiring commands where supported. Revalidate sensing after restart; reset filters, stale buffers, and tracker state on relevant session changes.

## 13. Configuration and privacy

Centralize mappings, sensor limits, timing, haptics, model/device selection, speech, and logging settings. Validate at startup and on mutation.

- Give configuration a version and retain the last accepted configuration.
- Separate hardware capability limits from user-adjustable preferences.
- Keep API keys in environment variables or the repository's existing secret mechanism. Never place them in code, frontend bundles, logs, or sample files.
- Default to short-lived in-memory camera/audio buffers. Recording is an explicit opt-in action.
- Send camera/audio content to a cloud provider only when that feature is intentionally enabled; make its active state visible.
- Keep the local monitor on the local machine by default. Do not expose remote device-control endpoints without access control.
- Do not add identity recognition or retain bystander audio/video for this prototype.

## 14. Repository and coding conventions

Inspect the actual repository before changing it. Read existing instructions, manifests, lockfiles, schemas, and entry points. Preserve the working stack and unrelated user changes.

If starting from an empty repository, the following is a **proposed structure**, not an existing inventory:

| Path | Purpose |
| --- | --- |
| `firmware/` | Sensor drivers, local scheduler, haptic policy, configuration validation |
| `src/sixth_sense/` | Host adapters, vision, voice, scene evidence, telemetry service |
| `schemas/` | Versioned event/configuration contracts and shared fixtures |
| `config/` | Hardware profiles, mappings, and provisional demo settings |
| `web/` | Optional live monitor; only if a simpler preview is insufficient |
| `tests/` | Policy, schema, integration, and fault-behavior checks |
| `fixtures/` | Small synthetic or consented replay inputs, labeled by origin |
| `docs/` | Hardware inventory, calibration, measured results, demo runbook, decisions |

For a new host, default to Python, the board's supported firmware toolchain, and optionally React/TypeScript for monitoring. Verify compatibility and pin dependencies. Preserve an existing working stack.

Implementation rules:

- Keep acquisition, normalization, policy, actuation, perception, and presentation separate.
- Use typed boundaries and explicit error states. Avoid a monolithic camera/sensor/voice loop.
- Implement fake adapters behind the same interfaces as real hardware.
- Keep policy logic deterministic and testable without hardware or API calls.
- Use structured logs with session, channel, sequence, configuration version, and reason codes.
- Bound retries, queues, network calls, and resource usage.
- Close cameras, microphones, ports, and tasks on shutdown; apply documented output shutdown behavior.
- Prefer small, reviewable changes. Do not rewrite unrelated code or add dependencies without a concrete purpose.
- Never download large datasets or model files implicitly during normal startup. Document and prepare required assets before the demo.

### Commands

Use actual repository commands. When scaffolding, provide verified entry points for setup, simulation, live operation, tests, linting, firmware build, and the demo. Targets such as `make sim` or `make demo` are suggestions until implemented; never report them as already working.

Simulation must not require attached devices, API keys, or network access. Hardware builds and cloud calls should be separate from the default software test path.

## 15. Verification and acceptance criteria

Check changed behavior, especially mapping, freshness, actuation, and configuration. Avoid tests that merely restate code.

| Area | Required evidence |
| --- | --- |
| Direction mapping | Every available physical sensor activates its intended motor; all eight logical mappings are checked |
| Distance policy | Nearer valid readings increase urgency as configured; exact boundaries and hysteresis are checked |
| Missing data | Missing, stale, disconnected, and out-of-order samples cannot appear as unobstructed space |
| Output expiry | Expired commands stop or transition according to the documented policy rather than remaining latched |
| Multi-sensor timing | Record per-channel revisit rate and haptic delay with the full enabled array |
| Host/network independence | Proximity behavior continues while host AI work is stopped and connectivity is disabled |
| Voice changes | Supported requests receive acknowledged updates; invalid and duplicate requests do not mutate settings incorrectly |
| Visual evidence | Unsupported classes, stale frames, missing tracks, and ambiguous range associations are handled explicitly |
| Simulation | The same recorded inputs produce reproducible policy outputs; source labels survive to the monitor |
| Physical outputs | Distinguish software-issued commands from observed actuator behavior |

Use deterministic fault injection/replay for camera loss, delayed responses, packet loss, session resets, and malformed configuration. Record versions, configuration, conditions, sample count, and limitations with results.

The hackathon demo is ready when:

- [ ] The actual sensor/motor count and any unconnected directions are visible.
- [ ] Moving a soft object toward a stationary participant produces the expected directional cue and cadence change.
- [ ] A scene question produces a concise response based on the current visible scene.
- [ ] At least one voice setting change is validated, applied, and acknowledged end to end.
- [ ] Disabling network-dependent features leaves the local haptic loop operational.
- [ ] An unavailable channel is clearly shown as unknown.
- [ ] The team has measured and can explain latency and coverage limitations.
- [ ] The demonstration can be restarted using a verified runbook.
- [ ] Live observations, replay, and simulated values are clearly distinguished.

## 16. Demonstration and presentation

Use a 60–90 second indoor demonstration with the participant stationary:

1. Explain the directional vibration mapping.
2. Move a soft object between directions, then closer; show motor and cadence changes.
3. Ask about a visible object and change an allowed setting by voice.
4. Disable the network-dependent assistant; demonstrate continued local haptics.
5. Show a labeled simulated fault or unavailable camera state.

Use one clear prototype claim: **sixth-sense turns nearby distance measurements into directional touch, with voice access to visual context.**

Present smoke, darkness, and underwater operation as future validation questions, not demonstrated capabilities.

## 17. Open decisions and completion reporting

Log each decision's choice, rationale, evidence, owner, and remaining limitation.

| Decision | Current status | Required next evidence |
| --- | --- | --- |
| Actual sensor/controller/driver parts | Not provided | Hardware inventory and datasheets |
| Usable range and eight-direction coverage | Not measured | Dry indoor measurements by channel, angle, and target type |
| Stale timeout and timing budget | Provisional | Full-array timing measurements |
| Haptic comfort, thresholds, and mapping | Provisional | Stationary identification and comfort checks |
| Camera checkpoint and host device | Not provided | Local inference benchmark and class-map inspection |
| Voice provider and offline vocabulary | Not provided | End-to-end command tests with and without connectivity |
| Speaker or bone conduction | Undecided | Available-device comparison indoors |
| Battery/runtime target | Propose a one-hour demo-session goal; unverified | Measured whole-system power and runtime, with host power reported separately |
| Head-worn weight budget | Not set | Measured assembled mass and fit assessment; report off-head components separately |
| Environmental variants/certification | Outside current prototype scope | Future application-specific engineering and qualified review |

Report changes, meaningful checks, demonstrated behavior, and blockers. Separate software tests from hardware verification. Update this file for changed decisions, never to disguise unmet requirements.

The default implementation order is: **inspect → freeze contracts → simulate → validate one physical channel → expand the array → measure timing → add vision → add voice → rehearse the complete demo.**
