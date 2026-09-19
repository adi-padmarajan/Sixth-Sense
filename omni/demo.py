"""Synthetic scene → assistant → fake speech. Offline unless --live is explicit."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from types import SimpleNamespace

from .client import ClientConfig, OmniClient
from .fake import FakeOmniClient
from .scene import describe_and_speak


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send one synthetic image to the cloud; requires YIBU_API_KEY")
    parser.add_argument("--audit-log", type=Path, default=Path("/tmp/sixth-sense-demo-audit.jsonl"))
    parser.add_argument("--max-age", type=float, default=5.0,
                        help="Explicit synthetic-demo freshness budget, not a validated live-view setting")
    args = parser.parse_args()

    import cv2
    import numpy as np
    from speech import SpeechService
    from speech.fakes import FakeTTS

    # Only the explicit demo entry point bridges the existing hyphenated directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "computer-vision"))
    from scene_state import SceneState

    frame = np.full((240, 320, 3), 255, dtype=np.uint8)
    cv2.rectangle(frame, (30, 40), (95, 130), (0, 0, 180), -1)
    cv2.line(frame, (30, 130), (30, 210), (0, 0, 180), 8)
    cv2.line(frame, (95, 130), (95, 210), (0, 0, 180), 8)
    boxes = SimpleNamespace(xyxy=np.array([[26., 36., 99., 214.]]), cls=np.array([0]),
                            conf=np.array([0.71]), id=None)
    state = SceneState()
    client = OmniClient(ClientConfig(cloud_enabled=True, audit_log=args.audit_log)) if args.live else FakeOmniClient()
    speech = SpeechService()
    tts = FakeTTS()
    try:
        speech.attach(tts=tts)
        state.update(frame, boxes, {0: "chair"}, "simulated")
        print(f"source_mode=simulated cloud_enabled={args.live} speech=fake")
        result = describe_and_speak(state, client, speech, max_age_s=args.max_age)
        tts.wait_idle(1)
        print(f"status={result.status} reason={result.reason}")
        print(result.text)
        print(f"fake speech outputs={len(tts.spoken)}")
        return 0 if result.status == "success" else 1
    finally:
        state.reset()
        speech.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
