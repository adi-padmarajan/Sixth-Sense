"""Read one CV snapshot and prepare a bounded, current scene request."""
from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import Protocol

from .client import AssistantResult


class SceneReader(Protocol):
    @property
    def session_generation(self) -> int: ...

    def read(self, max_age_s: float | None = None): ...


def describe_scene(state: SceneReader, client, *, prompt: str = "What is in the camera view?",
                   wav: bytes | None = None, max_age_s: float = 0.5,
                   jpeg_width: int = 640, clock=time.monotonic) -> AssistantResult:
    """Use the same monotonic clock as SceneState, including for fake-clock tests.

    No imports of the hyphenated CV directory or YOLO are needed: the reader is
    structural. Input freshness is checked before/after JPEG encoding; the
    request is limited to the remaining lifetime of this same snapshot.
    Call on an assistant worker, not the CV or speech-dispatch thread.
    """
    if not math.isfinite(max_age_s) or max_age_s <= 0 or jpeg_width <= 0:
        raise ValueError("max_age_s and jpeg_width must be positive")
    snapshot = state.read(max_age_s=max_age_s)
    if snapshot is None:
        return AssistantResult.unavailable("missing_or_stale_scene", camera=True)
    generation = snapshot.session_generation

    def remaining():
        if state.session_generation != generation:
            return 0.0
        age = clock() - snapshot.captured_at
        if not math.isfinite(age) or age < 0:
            return 0.0
        return max_age_s - age

    if remaining() <= 0:
        return AssistantResult.unavailable("stale_scene", camera=True)
    if not snapshot.detections:
        # Never turn an empty detector output into an API-generated all-clear.
        return AssistantResult("success", "No objects were detected in the camera view; "
                               "unrecognized objects may still be present.", "no_detections",
                               expires_at=snapshot.captured_at + max_age_s,
                               source_mode=snapshot.source_mode)

    import cv2  # no camera/window creation; only encode the original BGR pixels

    try:
        frame = snapshot.frame
        if snapshot.width > jpeg_width:
            height = max(1, round(snapshot.height * jpeg_width / snapshot.width))
            frame = cv2.resize(frame, (jpeg_width, height), interpolation=cv2.INTER_AREA)
        encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not encoded:
            return AssistantResult.unavailable("encoding_failed", camera=True)
        data = jpeg.tobytes()
    except (cv2.error, ValueError):
        return AssistantResult.unavailable("encoding_failed", camera=True)
    lifetime = remaining()
    if lifetime <= 0:
        return AssistantResult.unavailable("stale_scene", camera=True)
    age = max_age_s - lifetime
    # Same format as the CV helper; no import shim/global sys.path mutation.
    detections = ", ".join(f"{d.class_name} {d.region} {d.conf:.2f}" for d in snapshot.detections)
    evidence = (f"Source: {snapshot.source_mode}; frame sequence: {snapshot.sequence}.\n"
                f"Detected (age {age * 1000:.0f} ms): {detections}\n"
                "Age is since YOLO result receipt, not camera exposure.\n")
    result = client.complete(evidence + "Question: " + prompt, data, wav, timeout_s=lifetime)
    if remaining() <= 0:
        return AssistantResult.unavailable("stale_scene", camera=True)
    return replace(result, expires_at=snapshot.captured_at + max_age_s, source_mode=snapshot.source_mode)


def describe_and_speak(state, client, speech, **kwargs) -> AssistantResult:
    """Explicit speech handoff; no microphone registration or devices on import.

    The orchestrator must invoke this on its assistant worker and cancel that
    worker's requests on session changes. This function does not start threads.
    """
    from speech import Priority

    result = describe_scene(state, client, **kwargs)
    clock = kwargs.get("clock", time.monotonic)
    ttl = 0.5 if result.expires_at is None else result.expires_at - clock()
    if ttl <= 0:
        return AssistantResult.unavailable("stale_scene", camera=True)
    speech.speak(result.text, priority=Priority.LOW if result.status == "success" else Priority.NORMAL,
                 ttl_seconds=ttl)
    return result
