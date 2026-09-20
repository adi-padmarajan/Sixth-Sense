# Deployment: two physical devices

sixth-sense splits across **two independent Raspberry Pis**, both worn on
the headband, with **no network link between them**:

| Device | Runs | Language | Depends on |
| --- | --- | --- | --- |
| **Spidey Sense Pi** — QNX | `firmware/` | C, built with the QNX SDP | Nothing else. No Python, no network, no camera. |
| **Eyes & Voice Pi** — Linux | `main.py` and everything it imports (`speech/`, `omni/`, `computer-vision/`) | Python 3.11+ | Camera, mic, speaker; network only if `--cloud` is used |

This split is not incidental — it's a repository rule
([AGENTS.md](../AGENTS.md) §4, "Architecture and ownership"):

> Keep distance sensing and directional haptics local and independent of
> camera inference, speech services, internet access, and the dashboard.

So there is deliberately no serial/socket link scripted between the two
devices in this repo. If you later add a read-only telemetry export from
the QNX Pi to the monitor, keep the haptic loop itself independent of it —
don't make the Spidey Sense Pi wait on the Eyes & Voice Pi for anything.

Each device has its own README with implementation detail:
[`firmware/README.md`](../firmware/README.md) for the QNX side,
[`../README.md`](../README.md) for the Eyes & Voice side. This document is
the **runbook**: what to install, in what order, on which device, and what
currently doesn't work yet.

---

## Device 1: Spidey Sense Pi (QNX)

Runs the sensor → filter → hysteresis → proximity-band → haptic-pattern
loop from `firmware/`. See [`firmware/README.md`](../firmware/README.md)
for exactly what's implemented (short version: sensing, the policy math,
and pulse-pattern motor output are wired together in code, but only the
`rear` channel has an assigned motor GPIO pin — the other seven can't
actuate until real pins are filled in — and no motor output has been
confirmed to produce physical vibration on real hardware yet).

1. **Toolchain**: install the QNX Software Development Platform (SDP) on
   your build machine (can be your dev laptop, cross-compiling) or build
   self-hosted on the QNX Pi itself with `clang`. `firmware/third_party/config.mk`
   picks the right compiler automatically once `QNX_HOST` is set or you're
   running on a QNX host — see that file if you need to override it.
2. **Wire the sensors** per [`pin_map_pi.md`](../pin_map_pi.md); pin
   numbers are duplicated as comments in `firmware/channels.c` — keep both
   in sync if wiring changes.
3. **Build**:
   ```bash
   cd firmware
   make                                    # aarch64le, debug
   make PLATFORM=armv7le BUILD_PROFILE=release   # adjust for your Pi's QNX image
   ```
   Output: `firmware/build/<platform>-<profile>/sixth_sense_firmware`.
4. **Deploy**: copy the binary to the device and run it:
   ```bash
   scp firmware/build/aarch64le-release/sixth_sense_firmware qnxuser@<spidey-sense-pi>:/tmp/
   ssh qnxuser@<spidey-sense-pi> /tmp/sixth_sense_firmware
   ```
   Whatever privilege your QNX image's GPIO resource manager requires is
   outside this repo's scope — confirm it with your QNX/sponsor docs.
5. **Verify**: you should see one line per channel roughly every 200 ms
   (`front near 712 mm`, etc.), with `unknown` for any disconnected sensor
   — never a fabricated distance. There's no restart/health script yet;
   `ssh` in and re-run the binary if it stops.

This device needs no `pip install`, no `requirements.txt`, and no network
— that's intentional (P0 requirement: proximity feedback must survive the
host/network disappearing).

---

## Device 2: Eyes & Voice Pi (Linux) or dev laptop

Runs `main.py`: camera → YOLO tracking, offline speech (Vosk/Piper), and
the optional cloud OMNI assistant. The root [README.md](../README.md)
"Getting started" section covers the commands in full; this section adds
the parts specific to deploying on a **headless Raspberry Pi** rather than
a dev laptop.

### Easy path

```bash
git clone https://github.com/adi-padmarajan/Sixth-Sense.git
cd Sixth-Sense
bash scripts/setup_eyes_voice.sh
source .venv/bin/activate
python main.py
```

`scripts/setup_eyes_voice.sh` creates a venv, installs
`requirements.txt`, fetches the Piper/Vosk models, and import-checks every
required package. It does **not** open the camera/mic/speaker or prove
they work on the device — that's a separate, manual check (below), because
this script has to run without any of that hardware attached too.

### Raspberry Pi specific caveats (not an issue on a dev laptop)

These are real deployment risks worth checking before your rehearsal, not
things this repository can guarantee for you:

- **Python version.** The documented dev environment used Python 3.13.5.
  Raspberry Pi OS (Bookworm) ships Python 3.11, which is also fine, but
  hasn't been the machine `computer-vision/README.md`'s verified-version
  table was measured on — re-verify `ultralytics`/`torch`/`opencv-python`
  versions actually installed on the Pi (`pip show ultralytics torch
  opencv-python numpy`) and note them, per AGENTS.md §10 ("Record
  checkpoint, checksum, backend, resolution, class map... Benchmark the
  actual device").
- **ARM wheels for `torch`/`ultralytics`.** These are large, compiled
  packages. Raspberry Pi OS's default `pip.conf` already points at
  [piwheels.org](https://www.piwheels.org/), which publishes aarch64
  wheels for most of this stack — a plain `pip install -r requirements.txt`
  should pick them up without a source build. If pip tries to compile
  `torch` from source, the install will take a very long time or fail on
  the Pi's RAM; check `pip config list` / `/etc/pip.conf` and point it at
  piwheels explicitly if needed, or follow Ultralytics' own Raspberry Pi
  installation guide for a known-good wheel set.
- **`opencv-python` GUI backend.** `track_distances.py` calls
  `cv2.imshow(...)` for the annotated preview. On a headless Pi (no
  attached HDMI display, no VNC session), this will fail to open a window.
  There is currently no `--no-show`/headless flag in
  `computer-vision/track_distances.py` (documented as a gap in
  `computer-vision/CLAUDE.md` §"Not implemented yet"). Until that's added,
  either: attach a physical display for the demo, run a VNC/X11 desktop
  session on the Pi, or add a headless flag before deploying without a
  screen. Don't silently drop the preview requirement — AGENTS.md §3
  requires "a small live monitor showing direction, distance, freshness,
  motor commands, and subsystem health" as a P1 item.
- **Audio devices.** `sounddevice` needs PortAudio (`libportaudio2` on
  Debian/Raspberry Pi OS: `sudo apt install libportaudio2`) and a working
  ALSA/PulseAudio device for the mic and speaker. Run
  `python scripts/check_capture.py` on the Pi to confirm the mic actually
  records before the demo — an import-only check can't prove this.
- **Camera permission/index.** `SOURCE = 0` in `track_distances.py` assumes
  camera index 0. On a Pi with a CSI camera, this may need
  `libcamera`/`v4l2` bridging depending on your OS image and camera module
  — confirm `cv2.VideoCapture(0)` actually opens on your specific Pi/camera
  combination before the rehearsal.

None of the above are fixed by this repository automatically — they
depend on your specific Pi image, camera module, and audio hardware, which
AGENTS.md §6 explicitly requires you to record rather than assume
("Choose an available board that can service sensors and motor drivers
predictably... Record actual part numbers, interfaces, operating limits").

### Auto-start (optional)

A systemd unit template is provided at
[`../deploy/sixth-sense-eyes-voice.service`](../deploy/sixth-sense-eyes-voice.service).
Edit the `User`/`WorkingDirectory`/`ExecStart` paths for your device, then:

```bash
sudo cp deploy/sixth-sense-eyes-voice.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sixth-sense-eyes-voice
journalctl -u sixth-sense-eyes-voice -f
```

This is a convenience for leaving the demo running unattended, not a
requirement — `python main.py` in a terminal works exactly as well for a
rehearsed demo where someone is present to restart it.

### Tests

```bash
env -u YIBU_API_KEY python -m pytest tests omni/tests computer-vision/Tests -q
```

Runs with no camera, mic, sensors, network, GPU, or API key — safe to run
on the Pi itself or in CI before deploying.

---

## Running the combined demo

Both devices run independently and are demonstrated side by side — there
is no software integration step between them. Follow
[README.md "Demonstration and presentation"](../README.md#demonstration-and-presentation)
for the rehearsed sequence: directional vibration first (Spidey Sense Pi),
then a scene question and a voice setting change (Eyes & Voice Pi), then
the network-down and camera-unavailable degraded states.

Since only one of eight motor pins (`rear`) is assigned in firmware, and
motor GPIO output hasn't been confirmed on real hardware yet (see
`firmware/README.md`), the current honest demo is: **directional sensing**
on the QNX Pi (printed readings for all 8 channels, felt vibration only
possible on `rear` and unverified even there) running alongside the
**full Eyes & Voice** interaction on the Linux Pi. Update this section
once the remaining motor pins are assigned and vibration is confirmed by
touch on real motors.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `firmware`: `make` fails immediately with an `include` error | Wrong toolchain paths | Should already be fixed in this repo (`third_party/rpi_gpio/Makefile`); if you still see it, check you're building from `firmware/`, not a subdirectory |
| `firmware`: compile errors about missing `sys/neutrino.h` | No QNX SDP on `PATH`/`QNX_HOST` unset | Install/activate the QNX SDP; this code cannot build with a plain host gcc/clang by design |
| `main.py`: `pip install` hangs or fails building `torch` | Pi's pip isn't using piwheels, or is falling back to a source build | Check `pip config list`; see the ARM-wheels caveat above |
| `main.py`: `cv2.imshow` errors / blank window / crash on the Pi | No display/VNC session (headless Pi) | See the headless-preview caveat above |
| `main.py`: "Could not connect to pigpiod" | You're running `sensor_python/linux_driver.py` directly | That module is a legacy reference, superseded by `firmware/`; not used by `main.py` — see `requirements.txt` |
| `main.py --cloud`: "Scene assistant unavailable" | `YIBU_API_KEY` not set in the current shell | `export YIBU_API_KEY='...'` before running, or drop `--cloud` |
| Vosk: a grammar word never recognizes (e.g. `unmute`) | Word isn't in the small Vosk model's vocabulary | `speech.health_reason` reports this at startup (`partial` health) — see `speech/README.md` |
