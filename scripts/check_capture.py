#!/usr/bin/env python3
"""Manual mic check for the question recorder (opens the real mic + speaker).

Run from the repo root with models downloaded (scripts/fetch_models.sh):

    python scripts/check_capture.py [--seconds 3.0] [--out /tmp/question.wav]

Speaks "system ready", waits out the echo guard, prints "ask now", records
`--seconds` of raw mic audio bypassing Vosk, and writes it as WAV. Play the
file back: it should be your voice, not the speaker's. Peak amplitude near
0 means silence (wrong device or muted); a healthy utterance is usually a
few thousand out of 32767.
"""
import argparse
import array
import io
import logging
import os
import sys
import time
import wave

# Script lives in scripts/; make the repo root importable so `speech` resolves
# regardless of how it is invoked.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speech import speech, Priority, SpeechConfig  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=None, help="default: configs/speech.json question_seconds")
    ap.add_argument("--out", default="/tmp/question.wav")
    ap.add_argument("--config", default="configs/speech.json")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = SpeechConfig.load(args.config)
    seconds = config.question_seconds if args.seconds is None else args.seconds

    health = speech.configure(config)
    print("speech health:", health, speech.health_reason)
    if health.get("stt") not in ("ready", "partial"):
        print("STT unavailable; cannot capture.")
        speech.shutdown()
        return 1

    try:
        speech.speak("system ready", priority=Priority.NORMAL)
        # Wait for playback to finish plus the echo guard; capture refuses
        # to start while muted, so poll until it succeeds or we give up.
        deadline = time.monotonic() + 10.0
        data = None
        announced = False
        while data is None and time.monotonic() < deadline:
            if not announced and not speech._stt._muted.is_set():
                print(f"ask now ({seconds:.1f} s)...")
                announced = True
            data = speech.capture_question(seconds)
            if data is None:
                time.sleep(0.05)
        if data is None:
            print("capture returned None (muted the whole time, stalled, or busy)")
            return 1

        with open(args.out, "wb") as f:
            f.write(data)
        w = wave.open(io.BytesIO(data))
        frames = w.getnframes()
        samples = array.array("h", w.readframes(frames))
        peak = max((abs(s) for s in samples), default=0)
        print(f"wrote {args.out}: {frames / w.getframerate():.2f} s, "
              f"{w.getframerate()} Hz, peak amplitude {peak} / 32767")
        return 0
    finally:
        speech.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
