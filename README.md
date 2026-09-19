# SpideyIRL 🕷️

**A real-life Spidey Sense.** A head-worn wearable that turns nearby obstacles into
directional vibration, and lets you *ask* what the camera sees — hands-free.

<p align="center">
  <img src="spider-sense.avif" alt="SpideyIRL headband prototype" width="640">
</p>

> Ever wanted to be Spider-Man? Or maybe you've just related a little too much to
> Peter Parker lately? Either way, you can't exactly get bitten by a radioactive
> spider at Hack the North… so we tried the next best thing.

Built at **Hack the North 2026**.

---

## What it does

Peter's Spidey Sense is a tingle that tells him *where* danger is before he sees
it. Ours works the same way, minus the radioactive spider:

1. **Feel where things are.** Ultrasonic range sensors around a headband each
   drive a vibration motor on the same side of your head. Something on your
   left → your left temple buzzes. The closer it gets, the faster the pulses.
   Eight directions, 45° apart, all relative to where your head is pointing.
2. **Ask what it is.** Say *"what's in front of me"* and a camera + YOLO object
   detector + multimodal assistant answer out loud: *"A person is visible on the
   left of the camera view."* Voice in, voice out, no hands.
3. **Keep working when the smart parts don't.** Vibration comes from local
   sensor readings only. No camera, no cloud, no Wi-Fi required. If the
   assistant is offline, it says so — the tingle keeps tingling.

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

## How it works

Three paths, kept deliberately separate so the reflexes never wait on the brain:

```
  ┌──────────────── Spidey Sense (reflex) ────────────────┐
  │  8× ultrasonic sensors ─▶ validate ─▶ filter ─▶       │  local · no network
  │  proximity band ─▶ bounded pulse ─▶ 8× motors         │  no camera · no AI
  └───────────────────────────────────────────────────────┘
  ┌──────────────── Eyes & voice (companion host) ────────┐
  │  camera ─▶ YOLO tracker ─▶ SceneState (latest frame)  │  local
  │  mic ─▶ Vosk STT (12-phrase grammar) ─▶ handlers      │  local, offline
  │  "what's in front of me" ─▶ frame + audio ─▶ OMNI ─▶  │  cloud, opt-in
  │  Piper TTS ─▶ speaker                                  │  local, offline
  └───────────────────────────────────────────────────────┘
```

| Layer | Where | Status |
| --- | --- | --- |
| Ultrasonic sensor driver (HC-SR04 + front AJ-SR04M via `pigpio`) and a deterministic fake | [`sensor/`](sensor/) | Driver + fake exist; filtering, proximity bands, motor policy in progress |
| Haptic motor output | — | Not yet in the repo |
| Live object tracking (Ultralytics, Objects365 checkpoint) + `SceneState` evidence layer | [`computer-vision/`](computer-vision/) | Working |
| Offline speech: Vosk STT (grammar-limited) + Piper TTS with priority/interrupt queue | [`speech/`](speech/) | Working |
| Multimodal assistant client (`qwen3.5-omni-flash`), fake client, subprocess deadlines, audit ledger | [`omni/`](omni/) | Working; cloud is off unless enabled |
| Orchestrator wiring camera, speech, and one assistant question at a time | [`main.py`](main.py) | Working |
| Versioned config: speech, assistant, voice grammar | [`configs/`](configs/) | Working |

Each subfolder has its own README with the details.

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
which is what keeps offline recognition fast and reliable:

`what's in front of me` · `describe` · `device status` · `stop speaking` ·
`pause feedback` · `resume feedback` · `increase sensitivity` ·
`decrease sensitivity` · `volume up` · `volume down` · `mute` · `sound on`

Every phrase has a handler, checked at startup. Volume uses bounded levels 1–5
(default 3); audio controls speak confirmations. Mute preserves HIGH alerts and
`sound on` recognition, without muting the microphone. Pause/resume feedback and
sensitivity commands honestly say haptic controls are not available yet; the host
has no controller configuration bridge.

`describe` plays a short listening tone before recording the question (disable with
`listening_tone: false` in speech config). A busy question says "Still answering"
only outside recording, to avoid interrupting the accepted capture.

## Getting started

Everything below is the companion-host software. It runs on a laptop with a
webcam and a microphone; no sensors or motors needed.

```bash
git clone https://github.com/adi-padmarajan/Sixth-Sense.git
cd Sixth-Sense
# On the development Mac, use conda base: /opt/anaconda3/bin/python
python --version
pip install -r requirements.txt          # speech + assistant deps
pip install ultralytics opencv-python    # computer vision deps
bash scripts/fetch_models.sh             # Piper voice (~60 MB) + Vosk model (~40 MB)
```

### Run it

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

While running, say **"what's in front of me"** and listen. Press `q` in the
preview window or `Ctrl-C` to quit.

Live camera generator loss now shows CAMERA UNAVAILABLE and retries with
provisional 0.5–5 s backoff while voice commands keep running. Replay EOF exits
normally. A provisional image-quality floor rejects very dark, bright or
low-contrast frames without a cloud request. The preview labels cloud and camera
state; image mirroring defaults off and wearer orientation still needs a manual
check. These paths have headless fault-injection tests; upstream blocking camera
operations and actual device reconnect responsiveness need a device rehearsal.

Smaller pieces on their own:

```bash
python example-usage.py                  # speech only: say a command, see it handled
python scripts/check_capture.py          # mic check: records 3 s and writes a WAV
python computer-vision/track_distances.py  # camera + YOLO preview only
env -u YIBU_API_KEY python -m omni.demo  # synthetic scene → fake assistant → fake TTS, no devices
python sensor/sensors.py                 # fake ultrasonic read → distance in mm
```

### Test

All offline: no camera, mic, sensors, network, GPU, or API key.

```bash
env -u YIBU_API_KEY python -m pytest tests omni/tests computer-vision/Tests -q
env -u YIBU_API_KEY python -W error -m pytest omni/tests -q
```

Host logs include command-to-handoff and first-PCM-submission timing; aggregate
a saved JSON-lines log with `python scripts/summarize_latency.py demo.log` (or
stdin using `-`). Counts/p50/p95/max are split by status and capture mode. This
is software timing, not measured acoustic onset. Live vendor ledgers/summaries
are git-ignored; historical committed examples live in `omni/artifacts/examples/`.

## Hardware

| Part | Choice | Notes |
| --- | --- | --- |
| Range sensors | HC-SR04 ultrasonic + AJ-SR04M (front) | Sequenced firing to avoid cross-talk; a missed echo is `unknown`, not "clear" |
| Controller | Raspberry Pi (`pigpio` GPIO driver) | QNX on Pi explored for the sensor/haptic loop — see [`sensor/sensors.py`](sensor/sensors.py) |
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
  No recording, no identity recognition, no bystander retention.
- The reflex loop cannot block on HTTP, inference, speech, or logging.

## Prototype boundaries

This is a hackathon prototype demonstrated with a stationary wearer, soft
movable objects, and a dry, well-lit indoor room. It is **not** certified,
fireproof, waterproof, or a replacement for any protective, rescue, or mobility
equipment. Smoke, darkness, and underwater operation are future validation
questions, not demonstrated capabilities. It does not plan routes, guarantee
obstacle avoidance, or build a 3D map. Please don't blindfold yourself and walk
into traffic with it. With great power, etc.

## Repository layout

```
main.py             orchestrator: camera + speech + one assistant question at a time
sensor/             ultrasonic SensorDriver protocol, pigpio Linux driver, deterministic fake
computer-vision/    YOLO tracker, SceneState, tests, local checkpoint
speech/             Piper TTS + Vosk STT service, fakes, downloaded models (gitignored)
omni/               assistant client, scene request builder, fake, vendor CLIs, audit ledger
configs/            speech.json · assistant.json · grammar.json (all schema_version 1)
scripts/            fetch_models.sh · check_capture.py · summarize_latency.py
tests/              orchestrator + speech tests
SYSTEM_ARCHITECTURE.md   companion-host software architecture in depth
AGENTS.md / CLAUDE.md    engineering guidance for contributors and coding agents
```

## Team

Built at Hack the North 2026 by **Aditya Padmarajan**, **Halie Favron**, **Noah Valentin Klaholz** and **Chris Dietrich**.

## License

[MIT](LICENSE)
