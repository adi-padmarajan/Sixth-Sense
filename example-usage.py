"""
Run this after downloading models (see scripts/fetch_models.sh and the
README) to sanity-check the TTS/STT pipeline end to end before wiring it
into sensors/haptics. This is also the pattern the rest of the project
should follow: import `speech`, call `configure()` once with the shared
config, then use `speak()` / `on()` everywhere else.
"""

import logging
import time

from speech import speech, Priority, SpeechConfig

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

config = SpeechConfig.load("configs/speech.json")
health = speech.configure(config)
print("speech health:", health, speech.health_reason)

speech.on("mute", lambda cmd: print(f"[demo] muted (seq {cmd.seq}, {cmd.source_mode}, age {cmd.age_seconds:.2f}s)"))
speech.on("volume up", lambda cmd: print("[demo] volume up"))
speech.on("device status", lambda cmd: speech.speak(
    f"speech {speech.health['tts']}, listening {speech.health['stt']}", priority=Priority.NORMAL))
speech.on("describe", lambda cmd: speech.speak("nothing detected nearby", priority=Priority.NORMAL, ttl_seconds=3))
speech.on("what's in front of me", lambda cmd: speech.speak("camera view is unavailable", priority=Priority.NORMAL, ttl_seconds=3))
speech.on("stop speaking", lambda cmd: speech.stop_speaking())

speech.speak("system ready", priority=Priority.NORMAL)

print("Listening for commands (say one from configs/grammar.json)... Ctrl+C to quit.")
try:
    while True:
        time.sleep(0.5)
except KeyboardInterrupt:
    speech.shutdown()
