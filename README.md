# SpideyIRL 🕷️

**A real-life Spidey Sense.** A head-worn wearable that turns nearby obstacles into
directional vibration, and lets you *ask* what the camera sees — hands-free.

<p align="center">
  <img src="spider-sense.avif" alt="SpideyIRL headband prototype" width="640">
</p>

> Ever wanted to be Spider-Man? Or maybe you've just related a little too much to
> Peter Parker lately? Either way, you can't exactly get bitten by a radioactive
> spider at Hack the North… so we tried the next best thing.

Built at **Hack the North 2026** · repository name `Sixth-Sense` · [MIT](LICENSE)

---

## What it does

Peter's Spidey Sense is a tingle that tells him *where* danger is before he sees
it. Ours works the same way, minus the radioactive spider:

1. **Feel where things are.** Ultrasonic range sensors around a headband each
   drive a vibration motor on the same side of your head. Something on your
   left → your left temple buzzes. The closer it gets, the faster the pulses.
   Eight directions, 45° apart, all relative to where your head is pointing.
2. **Ask what it is.** Say *"what's in front of me"* and a camera + YOLO object
   tracker + multimodal assistant answer out loud: *"A person is visible on the
   left of the camera view."* Voice in, voice out, no hands.
3. **Keep working when the smart parts don't.** Vibration comes from local
   sensor readings only — no camera, no cloud, no Wi-Fi. If the assistant is
   offline, it says so. The tingle keeps tingling.

**The one-line claim:** SpideyIRL turns nearby distance measurements into
directional touch, with voice access to visual context.

## Why

Spider-Man's real superpower isn't the webs, it's *knowing where things are
without looking*. That's exactly what's missing when visibility is gone — a
firefighter in smoke, a diver in silt, someone navigating without sight.
Those are the futures we're building toward; each one needs its own hardware
and validation. What we built this weekend is the honest indoor prototype: a
stationary wearer, soft objects, a dry room, and a device that tells you where
they are.

## Status at a glance

We'd rather you know exactly what works than be impressed by a checklist.

| Piece | Status |
| --- | --- |
| Camera → YOLO tracking → `SceneState` evidence, annotated preview, camera-loss recovery | ✅ Working |
| Offline voice: Vosk STT (12-phrase grammar) + Piper TTS with priority/interrupt/mute/volume | ✅ Working |
| "What's in front of me" / "describe" → one frame (+ optional recorded question) → cloud assistant → spoken answer | ✅ Working (cloud is opt-in; fake client for offline demos) |
| Orchestrator (`main.py`): every grammar phrase handled, status, bounded shutdown, latency logs | ✅ Working |
| 224 offline tests — no camera, mic, sensors, network, GPU, or API key | ✅ Passing |
| Ultrasonic sensor read (Python: driver protocol, `pigpio` driver, deterministic fake) | 🟡 Reference only — being replaced by C firmware |
| C firmware for the sensor → haptic loop on QNX / Raspberry Pi | 🟡 Scaffolded — `firmware/` files exist but are empty |
| Filtering, hysteresis, proximity bands, motor output | ❌ Not yet in the repo |
| Voice control of haptics (pause / sensitivity) | ❌ Recognized, but replies "Haptic controls are not available yet" |
| Measured latency, range, and coverage on assembled hardware | ❌ Not measured |

## How it works

Three paths, kept deliberately separate so the reflexes never wait on the brain:

```
  ┌──────────────── Spidey Sense (reflex) ────────────────┐
  │  8× ultrasonic sensors ─▶ validate ─▶ filter ─▶       │  local · no network
  │  proximity band ─▶ bounded pulse ─▶ 8× motors         │  no camera · no AI
  └───────────────────────────────────────────────────────┘   (firmware in progress)
  ┌──────────────── Eyes & voice (companion host) ────────┐
  │  camera ─▶ YOLO tracker ─▶ SceneState (latest frame)  │  local
  │  mic ─▶ Vosk STT (12-phrase grammar) ─▶ handlers      │  local, offline
  │  "what's in front of me" ─▶ frame (+audio) ─▶ OMNI ─▶ │  cloud, opt-in
  │  Piper TTS ─▶ speaker                                  │  local, offline
  └───────────────────────────────────────────────────────┘
```

| Layer | Where | Notes |
| --- | --- | --- |
| Live object tracking (Ultralytics 8.4, local Objects365 checkpoint `yolo26n-objv1-150.pt`) | [`computer-vision/track_distances.py`](computer-vision/track_distances.py) | Tracks on camera `0` or a replay file; overlays cloud/camera state; on camera loss shows **CAMERA UNAVAILABLE** and reconnects with 0.5–5 s backoff |
| `SceneState` evidence layer | [`computer-vision/scene_state.py`](computer-vision/scene_state.py) | One immutable latest snapshot: original frame, detections (class from the checkpoint's own `model.names`, confidence, box, track ID, left/center/right region), freshness, `live`/`replay`/`simulated` source, image-quality floor, session generation |
| Offline speech | [`speech/`](speech/) | Vosk grammar-limited recognition, Piper synthesis, `LOW/NORMAL/HIGH` priority queue with interrupt, TTL, repeat suppression, echo guard, optional wake phrase, per-subsystem health, question recorder that bypasses Vosk |
| Assistant client | [`omni/`](omni/) | `qwen3.5-omni-flash` via an OpenAI-compatible endpoint; bytes-only requests; one request at a time; killable subprocess with a hard deadline; sanitized token-usage ledger; `FakeOmniClient` for offline runs |
| Orchestrator | [`main.py`](main.py) | Wires camera, speech, and one assistant question at a time; structured JSON-lines logs with per-question timings |
| Versioned config | [`configs/`](configs/) | `speech.json`, `assistant.json`, `grammar.json` — all `schema_version` 1, validated on load |
| Sensor read (Python reference) | [`sensor_python/`](sensor_python/) | `SensorDriver` protocol, `FakeSensorDriver`, `pigpio`-based `LinuxSensorDriver`, and `read_distance_mm()` (a missed echo returns `None`, never a distance) |
| Sensor/haptic firmware (C, QNX target) | [`firmware/`](firmware/) | Placeholder files from the Python→C pivot; no code yet |

Each subfolder has its own README with the details, and
[`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md) covers the companion-host
software in depth.

### Direction mapping

Directions are relative to the wearer's head, clockwise from above. One
versioned mapping is used everywhere — firmware, telemetry, tests, audio.

| Channel | Bearing | Motor | | Channel | Bearing | Motor |
| --- | --- | --- | --- | --- | --- | --- |
| `front` | 0° | `motor_0` | | `rear` | 180° | `motor_4` |
| `front_right` | 45° | `motor_1` | | `rear_left` | 225° | `motor_5` |
| `right` | 90° | `motor_2` | | `left` | 270° | `motor_6` |
| `rear_right` | 135° | `motor_3` | | `front_left` | 315° | `motor_7` |

### Distance → pulse cadence (provisional bench profile)

This is the policy the firmware will implement. It is not yet running on hardware.

| Band | Distance | Feel |
| --- | --- | --- |
| `far` | 1.5 – 3 m | ~1 pulse / s |
| `mid` | 0.8 – 1.5 m | ~2 pulses / s |
| `near` | 0.4 – 0.8 m | ~4 pulses / s |
| `urgent` | < 0.4 m | rapid, bounded burst |
| `unknown` | no / stale / invalid reading | **no pulse** — reported as a fault, never as "clear" |

These are indoor testing defaults, not measured or validated distances.

### Voice commands

The recognizer is limited to the phrases in [`configs/grammar.json`](configs/grammar.json),
which is what keeps offline recognition fast and reliable. Every phrase has a
handler, checked at startup:

| Say | What happens |
| --- | --- |
| **what's in front of me** | Sends the current camera frame with a fixed prompt to the assistant and speaks the answer. No recording. |
| **describe** | Plays a short listening tone, records **2 s** of your open-vocabulary question (raw mic audio, bypassing Vosk), sends audio + frame to the assistant, and speaks the answer. |
| **device status** | Speaks speech, listening, cloud, camera, and question state — e.g. *"Speech ready, listening ready, cloud off, camera live, question idle."* |
| **stop speaking** | Cancels current and queued speech. Always active, even with a wake phrase enabled. |
| **volume up** / **volume down** | Bounded levels 1–5 (default 5, full scale); confirmed aloud. |
| **mute** / **sound on** | Mute keeps `HIGH`-priority alerts and the spoken confirmation; the mic stays live so "sound on" still works. |
| **pause feedback** / **resume feedback** / **increase sensitivity** / **decrease sensitivity** | Recognized, but reply *"Haptic controls are not available yet."* — there is no host↔controller configuration bridge yet. |

Only one question is in flight at a time; a second one gets *"Still answering."*
(never during recording, so it can't talk over your question). Answers need a
camera snapshot no older than 0.5 s with acceptable image quality, or you hear
that the camera view is unavailable. Answers are spoken at `LOW` priority so an
alert can always interrupt them; once an answer starts playing, only a camera
session reset cancels it mid-sentence.

Wake phrase is **off** by default (`wake_phrase: null` in `configs/speech.json`).

## Getting started

Everything below is the companion-host software. It runs on a laptop with a
webcam, microphone, and speaker; no sensors or motors needed.

```bash
git clone https://github.com/adi-padmarajan/Sixth-Sense.git
cd Sixth-Sense
# On the development Mac, we use conda base: /opt/anaconda3/bin/python (3.13)
python --version
pip install -r requirements.txt          # speech + assistant deps (+ pigpio client)
pip install ultralytics opencv-python    # computer vision deps
bash scripts/fetch_models.sh             # Piper voice (~60 MB) + Vosk model (~40 MB)
```

The YOLO checkpoint `computer-vision/yolo26n-objv1-150.pt` is committed; nothing
is downloaded implicitly at startup.

### Run it

Always run from the repository root.

```bash
# Full demo, everything local. Cloud assistant off; you'll hear "system ready. cloud off."
python main.py

# Same, with canned assistant answers (still real camera, mic, and speaker)
OMNI_FAKE=1 python main.py

# Enable the cloud assistant for real scene answers
export YIBU_API_KEY='…'     # current shell only — never commit it
python main.py --cloud

# Replay an image or video instead of camera 0
python main.py --source path/to/clip.mp4
```

While running, say **"what's in front of me"** and listen. The preview window
labels cloud (`off` / `fake` / `on`) and camera (`live` / `replay` / `low quality` /
`unavailable`) state. Press `q` in the preview window or `Ctrl-C` to quit.

Camera media leaves the machine **only** with `--cloud`. If `--cloud` is set
without `YIBU_API_KEY`, startup logs a warning and questions answer
"unavailable" instead of crashing.

Smaller pieces on their own:

```bash
python example-usage.py                    # speech only: say a command, see it handled
python scripts/check_capture.py            # mic check: records 3 s and writes a WAV
python computer-vision/track_distances.py  # camera + YOLO preview only
env -u YIBU_API_KEY python -m omni.demo    # synthetic scene → fake assistant → fake TTS, no devices
python -m omni.demo --live --audit-log /tmp/live-check.jsonl   # ONE billable provider call with a generated image
```

### Test

All offline: no camera, mic, sensors, network, GPU, or API key.

```bash
env -u YIBU_API_KEY python -m pytest tests omni/tests computer-vision/Tests -q
# → 224 passed

env -u YIBU_API_KEY python -W error -m pytest omni/tests -q   # warnings as errors
```

Coverage includes: grammar/handler wiring, speech priority/mute/TTL/dedup,
question capture, scene freshness and immutability, image-quality boundaries,
camera reconnect fault injection, assistant deadlines (real stalled
subprocesses, no sockets), audit-ledger sanitization, and latency summarization.

### Latency logs

`main.py` emits JSON-lines events with `capture_ms`, `assistant_ms`, `total_ms`
(from recognition to completion), and `speech_started_ms` (first PCM handoff).
Summarize a saved log:

```bash
python main.py 2> demo.log
python scripts/summarize_latency.py demo.log     # or `-` for stdin
```

Counts, p50, p95, and max are split by status and capture mode. This is
**software timing**, not measured acoustic onset or motor response. Live vendor
ledgers are git-ignored; committed historical examples live in
[`omni/artifacts/examples/`](omni/artifacts/examples/).

## Configuration

Everything tunable lives in [`configs/`](configs/), versioned and validated on load.

| File | Key settings (current values) |
| --- | --- |
| `speech.json` | 16 kHz mono, `question_seconds: 2.0`, `max_capture_seconds: 10`, `echo_guard_seconds: 0.3`, `max_command_age_seconds: 2`, `dedup_window_seconds: 2`, `wake_phrase: null`, `always_on_commands: ["stop speaking"]`, `listening_tone: true` |
| `assistant.json` | `cloud_enabled: false`, `omni_model: qwen3.5-omni-flash`, `omni_timeout_s: 6`, `max_scene_age_ms: 500`, `answer_within_ms: 6000`, `frame_jpeg_width: 480`, `max_tokens: 96`, audit ledger path |
| `grammar.json` | The 12 recognizable phrases; every word is checked against the Vosk model's vocabulary at startup |

Credentials come only from the `YIBU_API_KEY` environment variable. There is no
key in the repo, no key file, and proxies are never read (`trust_env=False`).

## Hardware

| Part | Choice | Notes |
| --- | --- | --- |
| Range sensors | HC-SR04 ultrasonic + AJ-SR04M (front) | Sequenced firing to avoid cross-talk; a missed echo is `unknown`, not "clear" |
| Controller | Raspberry Pi, targeting QNX for the sensor/haptic loop | Python `pigpio` driver exists as a reference; the C firmware is scaffolded and in progress |
| Vibration | 8 motors, one per direction | Motor driver not yet in the repo; pulse widths and comfort limits still to be measured |
| Camera / mic / speaker | Laptop webcam, mic, and speaker | Off-head compute during the demo, disclosed as such |
| Mount | Adjustable headband | Helmet compatibility is a future goal |

Eight sensors 45° apart do **not** give continuous 360° coverage — there are
gaps between beams, and a horizontal ring doesn't see steps, holes, or overhead
hazards. We describe it as eight-direction sensing until we've measured
otherwise.

## Ground rules we built to

- Distance → vibration is a fixed, testable mapping. **No AI model ever touches
  a motor.**
- Missing, stale, or invalid readings are **unknown**, never empty space.
- Sensor measurements, camera detections, and assistant interpretations stay
  distinguishable end to end. The assistant says *"A person is visible ahead"*
  and the sensor says *"obstacle about one metre in front"* — we never glue the
  sensor's distance onto the camera's object without a real association.
- Cloud is off by default, visible when on, and only ever sees one frame and
  one question at a time. Credentials come from the environment, never code.
  The audit ledger stores token counts and status — never prompts, images,
  audio, or replies.
- No recording by default, no identity recognition, no bystander retention.
  Camera and audio buffers are short-lived and in-memory.
- The reflex loop cannot block on HTTP, inference, speech, or logging.

## Prototype boundaries

This is a hackathon prototype demonstrated with a stationary wearer, soft
movable objects, and a dry, well-lit indoor room. It is **not** certified,
fireproof, waterproof, or a replacement for any protective, rescue, or mobility
equipment. Smoke, darkness, and underwater operation are future validation
questions, not demonstrated capabilities. It does not plan routes, guarantee
obstacle avoidance, or build a 3D map. The pixel distances drawn on the preview
are image-space measurements between objects, not real-world ranges. Please
don't blindfold yourself and walk into traffic with it. With great power, etc.

## Repository layout

```
main.py                  orchestrator: camera + speech + one assistant question at a time
example-usage.py         speech-only smoke test
computer-vision/         YOLO tracker, SceneState, offline tests, committed checkpoint
speech/                  Piper TTS + Vosk STT service, fakes, downloaded models (gitignored)
omni/                    assistant client, scene request builder, fake, vendor CLIs, audit ledger
sensor_python/           Python sensor reference: SensorDriver protocol, pigpio driver, fake
firmware/                C firmware for the QNX sensor/haptic loop (scaffold, empty)
configs/                 speech.json · assistant.json · grammar.json (all schema_version 1)
scripts/                 fetch_models.sh · check_capture.py · summarize_latency.py
tests/                   orchestrator, speech, and latency tests (+ fixtures)
SYSTEM_ARCHITECTURE.md   companion-host software architecture in depth
proj_spec.md             original project spec and open questions
AGENTS.md / CLAUDE.md    engineering guidance for contributors and coding agents
```

## Team

Built at Hack the North 2026 by **Aditya Padmarajan**, **Halie Favron**,
**Noah Valentin Klaholz** and **Chris Dietrich**.

## License

[MIT](LICENSE)
