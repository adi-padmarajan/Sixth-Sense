"""
Run this after downloading models (see scripts/fetch_models.sh and the
README) to sanity-check the TTS/STT pipeline end to end before wiring it
into sensors/haptics. This is also the pattern the rest of the project
should follow: import `speech`, call `configure()` once, then use
`speak()` / `on()` everywhere else.
"""

import json
import logging
import time

from speech import speech, Priority

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

GRAMMAR = json.load(open("configs/grammar.json"))

health = speech.configure(
    tts_model_path="speech/models/en_US-lessac-medium.onnx",
    tts_config_path="speech/models/en_US-lessac-medium.onnx.json",
    stt_model_path="speech/models/vosk-model-small-en-us-0.15",
    grammar=GRAMMAR,
)
print("speech health:", health)

speech.on("mute", lambda: print("[demo] muted"))
speech.on("volume up", lambda: print("[demo] volume up"))
speech.on("describe", lambda: speech.speak("nothing detected nearby", priority=Priority.NORMAL, ttl_seconds=3))
speech.on("stop", speech.stop_speaking)

speech.speak("system ready", priority=Priority.NORMAL)

print("Listening for commands (say one from configs/grammar.json)... Ctrl+C to quit.")
try:
    while True:
        time.sleep(0.5)
except KeyboardInterrupt:
    speech.shutdown()