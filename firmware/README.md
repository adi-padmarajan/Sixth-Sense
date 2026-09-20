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
| Pulse-rate haptic pattern (silent when invalid, faster as distance shrinks) | `haptic_pattern.c` / `.h` | ✅ pure function, no hardware dependency; pulse rate/width are first-guess values, not tuned for comfort |
| QNX motor GPIO driver | `motor_driver_qnx.c` | 🟡 drives a pin high/low via `rpi_gpio`; **only wired into the build and never run against real hardware in this environment** — driver success does not prove physical vibration (AGENTS.md §12) |
| Main loop | `main.c` | 🟡 reads all 8 channels every ~200 ms, prints name/band/filtered-mm to stdout, and now also drives each channel's motor pin from the haptic pattern |
| Build system | `Makefile`, `third_party/rpi_gpio/Makefile` | ✅ (added; previously there was no way to produce a binary at all — see "Fixed in this pass" below) |

## Not implemented yet

- **Only one of eight motor pins is assigned.** `channels.c` defines
  `MOTOR_PIN_REAR` (BCM 14) but leaves the other seven as `MOTOR_PIN_UNSET`
  (`-1`) — "unconfirmed... TODO: fill in as wiring is decided." `motor_set()`
  safely no-ops for an unset pin (bounds-checked in `rpi_gpio_output`), so
  those seven channels cannot actuate no matter how they're physically
  wired until real GPIO numbers are filled in here. Do not report multi-
  direction haptic feedback as working until all eight pins are assigned
  and each has been felt on a real motor — see AGENTS.md §12 (motor health
  must be verified, not assumed from a driver ack) and §15 ("every
  available physical sensor activates its intended motor" applies equally
  to motors).
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

Two more issues found and fixed after that build was first attempted on
the actual QNX Pi:

4. `firmware/Makefile`'s `SRCS` list omitted `haptic_pattern.c` and
   `motor_driver_qnx.c`, even though `main.c` calls
   `haptic_pattern_is_on()` and `motor_set()` — the link failed with
   `undefined reference to 'haptic_pattern_is_on'` / `'motor_set'`. Added
   both files to `SRCS`.
5. **Suspected root cause of unreliable sensor readings** ("some sensors
   not working"): in `sensor_driver_qnx.c`, `ensure_pin_registered()`
   registered each GPIO edge event using the pin's position within its
   own trigger group (0–3) as the event ID. Since group A and group B each
   have 4 channels, this reused the same small ID across groups — e.g.
   `front` (group A, index 0) and `front_right` (group B, index 0) were
   both registered under event ID 0. Every registered pin stays live on
   one shared QNX channel for the life of the process, so a late/stray
   edge from one group's sensor arriving while the other group is mid-wait
   could be misattributed to whichever channel happened to share its
   index, corrupting that channel's measured duration. Fixed by using the
   GPIO pin number itself as the event ID (globally unique) and having
   both `sensor_wait_for_echo` and `sensor_wait_for_echoes` verify which
   physical pin a received pulse actually came from before accepting it.
   **This has not been run against real hardware in this environment** —
   it addresses a real defect found by code inspection, not a confirmed
   fix for what you're seeing on the bench. Re-run and recheck per-channel
   readings after rebuilding; if a channel is still consistently `unknown`
   or implausible, it's more likely a wiring/sensor-health issue than this
   one.

## Motor GPIO bring-up test

`motor_gpio_test.c` is a standalone tool (not part of the Makefile build,
same pattern as `test_registration.c`) that holds one or more GPIO pins
HIGH at once for a fixed duration, bypassing sensors, valid-reading
gating, and the haptic pattern entirely. Use it to isolate a non-firing
motor into "software" vs. "hardware" before digging further into
`main.c`/`haptic_pattern.c` -- and to test several motors simultaneously
(e.g. ones you've wired to a shared ground) without needing them assigned
in `channels.c` first:

```bash
cd firmware
qcc -Vgcc_ntoaarch64le -I. -Ithird_party/rpi_gpio/public \
    motor_gpio_test.c -Lthird_party/rpi_gpio/build/aarch64le-debug \
    -lrpi_gpio -lpthread -o build/motor_gpio_test
# or, self-hosted with clang, same flags:
# clang -I. -Ithird_party/rpi_gpio/public motor_gpio_test.c \
#     -Lthird_party/rpi_gpio/build/aarch64le-debug -lrpi_gpio -lpthread \
#     -o build/motor_gpio_test

./build/motor_gpio_test 5 14           # BCM 14 (rear) only, hold HIGH 5s
./build/motor_gpio_test 5 14 4 17 27   # four pins together, hold HIGH 5s
```

First argument is always the hold duration in seconds; every argument
after it is a BCM pin number to drive HIGH simultaneously. Each pin still
gets its own separate `rpi_gpio_output` resource-manager call under the
hood, so "simultaneous" here means back-to-back in the same tight loop,
not a single atomic hardware write -- fine for a by-touch/multimeter
check, not for measuring inter-channel timing.

Requires `third_party/rpi_gpio`'s static lib already built (running `make`
once in `firmware/` first produces
`third_party/rpi_gpio/build/aarch64le-debug/librpi_gpio.a`).

Reading the result (per pin, since a shared ground can make one working
motor's vibration hard to attribute by touch alone when several are
tested together -- check each with a multimeter individually if results
seem ambiguous):

- **Motor buzzes** → the GPIO→driver→motor hardware path works for that
  channel. The fault is upstream in software: check whether `main.c` is
  actually reaching that channel's `motor_set()` call with `true` (e.g.
  the sensor reading is valid and within `haptic_pattern`'s range — see
  the "Not implemented yet" section above for which pins are even
  assigned).
- **Motor stays silent** → it's downstream of that pin. Most likely: no
  transistor/MOSFET driver stage between the GPIO and the motor. A GPIO
  pin sources only a few mA; most vibration motors need tens to hundreds
  of mA, and driving one directly off a GPIO typically does nothing (or
  risks the pin). Confirm with a multimeter across the motor leads while
  the pin is held high, not just by touch — that tells you whether any
  voltage/current is arriving at all before you go looking for a driver
  IC or transistor problem.
- **Some fire, some don't, when tested together** → points at a per-pin
  hardware difference (driver stage present on some channels but not
  others, a bad connection on specific motors) rather than a shared
  software or power-supply problem, since they all received the same
  command at the same time.
- **`rpi_gpio_setup`/`rpi_gpio_output` itself returns non-zero** → that's
  a resource-manager/permission problem (see the GPIO privilege note under
  "Deploy and run" above), separate from either of the above.

Delete this file once the real motor path is confirmed working end to end
— it's a bring-up aid, not permanent tooling.

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
   `front        near                712 mm`. The `rear` channel's motor
   (BCM 14) is driven from its own reading; the other seven channels have
   no motor pin assigned yet and cannot actuate regardless of wiring (see
   "Not implemented yet"). Motor GPIO output has not been confirmed to
   produce physical vibration on real hardware — verify by touch, don't
   assume from the absence of a driver error.

## Reporting

For any change in this directory, report: which checks actually ran (a
successful `make -n` dry run is not a compiled binary; a compiled binary
is not hardware verification), what remains unimplemented, and any
measured timing/coverage — per the root [AGENTS.md](../AGENTS.md) §15/§17
reporting rules.
