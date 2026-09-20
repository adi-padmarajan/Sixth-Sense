# speech — offline TTS/STT for SpideyIRL

Piper (TTS) and Vosk (STT) behind one small API so sensors, haptics, and the
orchestrator never need to know which library is talking or listening.
Run all commands from the repository root.

## Setup

```bash
pip install -r requirements.txt
bash scripts/fetch_models.sh
python example-usage.py
python -m pytest tests   # device-free checks using speech.fakes
```

You should hear "system ready" and then be able to say any word from
`configs/grammar.json` (e.g. "mute", "volume up") and see it handled.

## Using it from other modules

```python
from speech import speech, Priority, SpeechConfig

speech.configure(SpeechConfig.load("configs/speech.json"))   # once, at startup
speech.speak("obstacle ahead", priority=Priority.HIGH, interrupt=True)
speech.on("describe", lambda cmd: run_cv_description(request_id=cmd.seq))
```

That's the whole contract. `speech` is a singleton configured once at
startup (see `example-usage.py`); everything else just calls `.speak()`
or registers a `.on()` handler. Handlers receive a frozen `Command` with
`text`, `seq`, `recognized_at`, `dispatched_at`, `age_seconds`, and
`source_mode` (`live` from the mic, `simulated`/`replay` from fakes).

- **All settings live in `configs/speech.json`** (`SpeechConfig`,
  `schema_version` 1): model paths, audio device indices, samplerate and
  blocksize, echo guard, command age limit, queue size, repeat-suppression
  window, and the wake-phrase policy. It is validated on load; paths are
  relative to the config file. `grammar_path` points at `grammar.json`.

- **Priority + interrupt**: `Priority.HIGH` with `interrupt=True` cuts off
  whatever is currently playing and drops any queued lower-priority
  speech. Use this for time-critical alerts, not routine narration —
  reserve `Priority.LOW` for ambient scene descriptions from the CV
  stretch goal so they never block an obstacle warning.
- **Stop / expiry / repeats**: `speech.stop_speaking()` cancels current and
  queued speech; `speak(..., ttl_seconds=3)` drops a message that hasn't
  started playing by then (use it for scene descriptions that go stale);
  identical text queued again within `dedup_window_seconds` is suppressed
  unless it is `Priority.HIGH` or `interrupt=True` (`speak()` returns
  `False` when suppressed).
- **Wake phrase (optional)**: set `wake_phrase` in the config and commands
  only dispatch within `wake_window_seconds` after it is heard, except
  `always_on_commands` (default `["stop speaking"]`). Off by default.
- **Handlers run on a dispatcher thread**, not the recognition thread, so
  a slow handler doesn't stop listening. Commands older than
  `max_command_age_seconds` (default 2 s) by the time they're dispatched
  are discarded, and unmatched utterances are logged, not silently dropped.
- **Health**: `speech.health` is `{"tts": ..., "stt": ...}` with values
  `ready`, `partial`, `fault`, or `unavailable`; `speech.health_reason`
  carries the reason. `partial` means the recognizer is running but some
  grammar phrases use words the model doesn't know (they are listed in the
  reason and can never fire -- e.g. `unmute` with the small English model). A backend that fails to load or errors during playback/recognition
  is reported here instead of taking the other side down. `speak()` returns
  `False` when no TTS is available.
- **No hardware needed for tests**: `speech.fakes.FakeTTS` / `FakeSTT`
  implement the same interfaces; wire them with
  `speech.attach(tts=FakeTTS(), stt=FakeSTT(), config=SpeechConfig(...))`.
- **Grammar-limited STT**: `configs/grammar.json` is the full list of
  recognizable words/phrases. Keeping it small and fixed is what makes
  Vosk fast and reliable here — add to it as you add commands, but don't
  expect open-vocabulary recognition from this setup. Every word is
  checked against the model's vocabulary at startup; a bare `[unk]` result
  (speech heard, nothing matched) is logged as `not_understood`.

## Troubleshooting: TTS reports "ready" but nothing is audible

`speech.health["tts"] == "ready"` only means Piper loaded and the output
stream opened without raising -- a driver acknowledgement, not proof of
physical sound (CLAUDE.md §12). On a headless Raspberry Pi (or any Linux
host with plain ALSA and no desktop session), `sounddevice`/PortAudio's
"default" output device is whatever `/etc/asound.conf` or `~/.asoundrc`
hardcodes -- commonly HDMI on a Pi -- and it silently opening does not mean
that's the jack/speaker you're listening to.

When `configs/speech.json` has `"tts_device": null` (the default), startup
logs `tts: no PulseAudio/PipeWire "pulse" ALSA device found; ...` followed
by every candidate output device the log found, each with the sounddevice
index needed for `tts_device`, and marks which one PortAudio picked by
default. To fix a silent Pi:

1. Run `python main.py --cloud` (or any entry point that calls
   `speech.configure(...)`) and read that device list in the startup log.
2. Confirm on the OS side which device is actually wired to your speaker:
   `aplay -l` lists ALSA cards/devices, `speaker-test -D hw:<card>,<device> -c1`
   plays a test tone on one of them directly, and `alsamixer` (or
   `raspi-config` on Raspberry Pi OS) checks the channel isn't muted or at 0.
3. Once you know the right index from the startup log, set it explicitly in
   `configs/speech.json`: `"tts_device": <index>`. An explicit `tts_device`
   always wins over the "pulse"/default auto-selection.

## A note on QNX

This module (`piper-tts`, `vosk`, `sounddevice`) depends on native
compiled libraries that are built for Linux/macOS/Windows, not QNX. If
you're targeting the QNX sponsor track, the safer path is to develop and
demo this module on Linux (e.g. a Raspberry Pi) and keep the
sonar-sensing + haptic-actuation loop as the piece that actually runs on
QNX, talking to this module over a serial or network link. Confirm
QNX's current audio driver and native-extension support with the sponsor
mentors before committing to porting this module itself — that changes
the plan significantly either way.

## Extending later

If sensors/haptics end up in a different process or language than this
module, don't refactor `tts.py`/`stt.py` — add a transport layer in front
of `SpeechService` (e.g. newline-delimited JSON over a local socket) so the
rest of the project keeps calling `speech.speak()` / `speech.on()`
exactly as before. Don't build it until the process split is known.