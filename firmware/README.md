# firmware — QNX Spidey Sense sensor → haptic loop

C firmware for the local proximity path: 8 ultrasonic sensors → validate →
median filter → hysteresis → proximity band, per channel. Runs entirely on
the QNX Spidey Sense Raspberry Pi, independent of the camera, voice, cloud,
and network — see [AGENTS.md](../AGENTS.md) §4 for why that separation is
required. It does **not** import or depend on anything under `speech/`,
`omni/`, or `computer-vision/`.

## What's implemented

| Piece | File | Status |
| --- | --- | --- |
| Channel/pin mapping (8 directions, bearings, trigger/echo pins) | `channels.c` / `channels.h` | ✅ matches [`pin_map_pi.md`](../pin_map_pi.md) and the direction table in the root README |
| QNX GPIO sensor driver (trigger pulse, edge-timed echo, grouped trigger to avoid cross-talk) | `sensor_driver_qnx.c` | ✅ uses the vendored `third_party/rpi_gpio` resource-manager client; a missed echo returns `false`, never a distance |
| Distance-from-echo conversion, all-8-channel read | `sensor.c` / `sensor.h` | ✅ |
| Median filter (3-sample window, provisional) | `proximity_filter.c` / `.h` | ✅ |
| Proximity bands with hysteresis (`unknown`/`beyond`/`far`/`mid`/`near`/`urgent`, provisional bench thresholds) | `proximity_band.c` / `.h` | ✅ matches the bench profile in the root README/AGENTS.md §8 |
| Per-channel state (filter + band together) | `proximity_state.c` / `.h` | ✅ |
| Main loop | `main.c` | 🟡 reads all 8 channels every ~200 ms and **prints** name/band/filtered-mm to stdout |
| Build system | `Makefile`, `third_party/rpi_gpio/Makefile` | ✅ (added; previously there was no way to produce a binary at all — see "Fixed in this pass" below) |

## Not implemented yet

- **No motor/haptic output.** `channels.c` records a motor *name* (`"motor_0"`,
  etc.) per direction, but nothing in this directory drives a GPIO/PWM pin,
  a motor driver IC, or any actual vibration hardware. `main.c` only prints
  to stdout. Do not report haptic feedback as working until this exists and
  has been felt on real motors — see AGENTS.md §8 (bounded, expiring
  `HapticCommand`) and §12 (motor health must be verified, not assumed from
  a driver ack).
- No bounded/expiring command semantics (AGENTS.md §8: "An expired motor
  command cannot remain latched indefinitely") — there's no command output
  yet to expire.
- No watchdog, no health/fault reporting output, no physical stop.
- No serial/telemetry link to the Eyes & Voice host. Per AGENTS.md §4 this
  is intentional for the proximity path itself (it must work without the
  host); a *read-only* telemetry export for the monitor is a P1 item, not
  built here.
- No config file / versioned thresholds — bands, hysteresis, and the median
  window are compile-time constants (`proximity_band.h`, `proximity_filter.h`).
- No automated tests for the QNX-specific code (`sensor_driver_qnx.c`)
  beyond the manual `test_registration.c` experiment (not part of the
  build, kept for reference — see its header comment).
- Timing (`AGENTS.md` §9: p95 sample→command latency, per-channel revisit
  interval) has not been measured on real hardware.

## Fixed in this pass

Before this change, `make` could not produce a firmware binary at all:

1. `third_party/rpi_gpio/Makefile` included `../../common/config.mk`, a
   path that doesn't exist in this repo (the file is at
   `third_party/config.mk`, one level up, not two, and not under
   `common/`). Fixed to `include ../config.mk`.
2. The same Makefile referenced `-I../system/gpio` for the
   `<sys/rpi_gpio.h>` resource-manager protocol header, but the vendored
   directory is `third_party/system_gpio/sys/rpi_gpio.h`. Fixed to
   `-I../system_gpio`.
3. There was no top-level `firmware/Makefile` linking `main.c` and the
   rest of the sensor/policy sources against the `rpi_gpio` static
   library. Added one (see below).

The new top-level `Makefile` has been dry-run (`make -n`) on this
(non-QNX) machine to confirm the dependency graph and flags are wired
correctly, but **not compiled against a real QNX SDP** — there is no QNX
toolchain available in this environment. Verify `make` actually builds on
your QNX SDP/target before relying on it, and adjust `INCLUDES`/`LIBS_all`
if the SDP reports missing symbols.

## Build

Requires the QNX Software Development Platform: `qcc`/`q++` on `PATH` with
`QNX_HOST` set (cross build from Linux/macOS/Windows), or a QNX
self-hosted target with `clang`. See `third_party/config.mk` for how the
toolchain and platform variant are selected — this mirrors BlackBerry's
own vendored `rpi_gpio` sample, which is why that file lives under
`third_party/` unmodified.

```bash
cd firmware
make                                   # aarch64le, debug build
make PLATFORM=armv7le BUILD_PROFILE=release
make clean
```

Output: `build/<platform>-<profile>/sixth_sense_firmware`.

Compiling `sensor_driver_qnx.c` requires QNX-only headers
(`<sys/neutrino.h>`, the `rpi_gpio` resource-manager protocol) that do not
exist outside a QNX SDP — this cannot be built with a plain host
gcc/clang, by design (the sensor loop only ever runs on the QNX Pi).

## Deploy and run

1. Build on your dev machine (cross-compile) or directly on the QNX Pi
   (self-hosted).
2. Copy the resulting binary to the device, e.g.:
   ```bash
   scp build/aarch64le-release/sixth_sense_firmware qnxuser@<spidey-sense-pi>:/tmp/
   ```
3. Wire the 8 ultrasonic sensors per [`pin_map_pi.md`](../pin_map_pi.md)
   (BCM pin numbers are duplicated as comments in `channels.c` — keep both
   in sync if you change wiring).
4. On the device, run it with whatever privilege the GPIO resource manager
   requires on your QNX image (consult your QNX GPIO resource-manager
   setup/docs; this repo doesn't script that step):
   ```bash
   /tmp/sixth_sense_firmware
   ```
5. Expect one line per channel every ~200 ms:
   `front        near                712 mm`. There is no vibration yet —
   this only proves the sense half of the loop end to end (see "Not
   implemented yet").

## Reporting

For any change in this directory, report: which checks actually ran (a
successful `make -n` dry run is not a compiled binary; a compiled binary
is not hardware verification), what remains unimplemented, and any
measured timing/coverage — per the root [AGENTS.md](../AGENTS.md) §15/§17
reporting rules.
