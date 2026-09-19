# Sixth-Sense
Hack The North 2026

## speech pipeline scaffold

This is a starting point for the TTS/STT part of the project: a `speech`
package wrapping Piper (TTS) and Vosk (STT) behind one simple API, so the
rest of the project (sensors, haptics, orchestrator) never has to know
which library is doing the talking or listening.

### Setup

```bash
pip install -r requirements.txt
bash scripts/fetch_models.sh
python example-usage.py
python -m pytest tests   # device-free checks using speech.fakes
```

You should hear "system ready" and then be able to say any word from
`configs/grammar.json` (e.g. "mute", "volume up") and see it handled.

### Using it from other modules

```python
from speech import speech, Priority

speech.speak("obstacle ahead", priority=Priority.HIGH, interrupt=True)
speech.on("describe", lambda: run_cv_description())
```

That's the whole contract. `speech` is a singleton configured once at
startup (see `example-usage.py`); everything else just calls `.speak()`
or registers a `.on()` handler.

- **Priority + interrupt**: `Priority.HIGH` with `interrupt=True` cuts off
  whatever is currently playing and drops any queued lower-priority
  speech. Use this for time-critical alerts, not routine narration —
  reserve `Priority.LOW` for ambient scene descriptions from the CV
  stretch goal so they never block an obstacle warning.
- **Stop / expiry**: `speech.stop_speaking()` cancels current and queued
  speech; `speak(..., ttl_seconds=3)` drops a message that hasn't started
  playing by then (use it for scene descriptions that go stale).
- **Handlers run on a dispatcher thread**, not the recognition thread, so
  a slow handler doesn't stop listening. Commands older than
  `max_command_age_seconds` (default 2 s) by the time they're dispatched
  are discarded, and unmatched utterances are logged, not silently dropped.
- **Health**: `speech.health` is `{"tts": ..., "stt": ...}` with values
  `ready`, `fault`, or `unavailable`; `speech.health_reason` carries the
  reason. A backend that fails to load or errors during playback/recognition
  is reported here instead of taking the other side down. `speak()` returns
  `False` when no TTS is available.
- **No hardware needed for tests**: `speech.fakes.FakeTTS` / `FakeSTT`
  implement the same interfaces; wire them with
  `speech.attach(tts=FakeTTS(), stt=FakeSTT())`.
- **Grammar-limited STT**: `configs/grammar.json` is the full list of
  recognizable words/phrases. Keeping it small and fixed is what makes
  Vosk fast and reliable here — add to it as you add commands, but don't
  expect open-vocabulary recognition from this setup.

### A note on QNX

This module (`piper-tts`, `vosk`, `sounddevice`) depends on native
compiled libraries that are built for Linux/macOS/Windows, not QNX. If
you're targeting the QNX sponsor track, the safer path is to develop and
demo this module on Linux (e.g. a Raspberry Pi) and keep the
sonar-sensing + haptic-actuation loop as the piece that actually runs on
QNX, talking to this module over a serial or network link. Confirm
QNX's current audio driver and native-extension support with the sponsor
mentors before committing to porting this module itself — that changes
the plan significantly either way.

### Extending later

If sensors/haptics end up in a different process or language than this
module, don't refactor `tts.py`/`stt.py` — add a transport layer in front
of `SpeechService` (e.g. newline-delimited JSON over a local socket) so the
rest of the project keeps calling `speech.speak()` / `speech.on()`
exactly as before. Don't build it until the process split is known.