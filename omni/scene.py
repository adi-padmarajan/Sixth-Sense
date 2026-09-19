"""Read one CV snapshot and prepare a bounded, current scene request."""
from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import Protocol

from .client import AssistantResult


AUDIO_QUESTION_PROMPT = (
    "The audio is the wearer's spoken question. Answer it in one short sentence "
    "using only the image and the detection list."
)
TEXT_QUESTION_PREFIX = "Question: "


class SceneReader(Protocol):
    @property
    def session_generation(self) -> int | None: ...

    def read(self, max_age_s: float | None = None): ...


def describe_scene(state: SceneReader, client, *, prompt: str = "What is in the camera view?",
                   wav: bytes | None = None, max_age_s: float = 0.5,
                   answer_within_s: float = 6.0,
                   jpeg_width: int = 640, clock=time.monotonic) -> AssistantResult:
    """Use the same monotonic clock as SceneState, including for fake-clock tests.

    No imports of the hyphenated CV directory or YOLO are needed: the reader is
    structural. Input freshness is checked before/after JPEG encoding; the
    request and answer use a separate lifetime for this same snapshot.
    Call on an assistant worker, not the CV or speech-dispatch thread.
    """
    if (not math.isfinite(max_age_s) or max_age_s <= 0
            or not math.isfinite(answer_within_s) or answer_within_s < max_age_s):
        raise ValueError("answer_within_s >= max_age_s > 0 must be finite")
    if type(jpeg_width) is not int or jpeg_width <= 0:
        raise ValueError("jpeg_width must be a positive integer")
    snapshot = state.read(max_age_s=max_age_s)
    if snapshot is None:
        return AssistantResult.unavailable("missing_or_stale_scene", camera=True)
    generation = snapshot.session_generation

    def age_now():
        if state.session_generation != generation:
            return math.inf
        age = clock() - snapshot.captured_at
        if not math.isfinite(age) or age < 0:
            return math.inf
        return age

    def unavailable(reason, *, call_id=None):
        return replace(AssistantResult.unavailable(reason, camera=True),
                       source_mode=snapshot.source_mode, call_id=call_id,
                       session_generation=generation)

    if age_now() > max_age_s:
        return unavailable("stale_scene")
    if snapshot.quality != "ok":
        return unavailable("low_quality")

    import cv2  # no camera/window creation; only encode the original BGR pixels

    try:
        frame = snapshot.frame
        if snapshot.width > jpeg_width:
            height = max(1, round(snapshot.height * jpeg_width / snapshot.width))
            frame = cv2.resize(frame, (jpeg_width, height), interpolation=cv2.INTER_AREA)
        encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not encoded:
            return unavailable("encoding_failed")
        data = jpeg.tobytes()
    except (cv2.error, ValueError):
        return unavailable("encoding_failed")
    age = age_now()
    if age > max_age_s:
        return unavailable("stale_scene")
    lifetime = answer_within_s - age
    if lifetime <= 0:
        return unavailable("stale_scene")
    config = getattr(client, "config", None)
    budget = min(lifetime, config.timeout_s) if config is not None else lifetime
    # Same format as the CV helper; no import shim/global sys.path mutation.
    detections = ", ".join(f"{d.class_name} {d.region} {d.conf:.2f}" for d in snapshot.detections)
    evidence = (f"Source: {snapshot.source_mode}; frame sequence: {snapshot.sequence}.\n"
                f"Detected (age {age * 1000:.0f} ms): {detections or 'none'}\n"
                "Age is since YOLO result receipt, not camera exposure.\n"
                "Empty detections do not establish that the area is clear.\n")
    question = AUDIO_QUESTION_PROMPT if wav is not None else TEXT_QUESTION_PREFIX + prompt
    result = client.complete(evidence + question, data, wav, timeout_s=budget)
    if age_now() > answer_within_s:
        return unavailable("stale_scene", call_id=result.call_id)
    return replace(result, expires_at=snapshot.captured_at + answer_within_s,
                   source_mode=snapshot.source_mode, session_generation=generation)


def describe_and_speak(state, client, speech, **kwargs) -> AssistantResult:
    """Explicit speech handoff; no microphone registration or devices on import.

    Invoke on an assistant worker. Expired/session-invalid results stay silent;
    missing input and service failures get a status message. No threads start here.
    """
    from speech import Priority

    result = describe_scene(state, client, **kwargs)
    if result.reason == "stale_scene":
        return result
    clock = kwargs.get("clock", time.monotonic)
    ttl = 0.5 if result.expires_at is None else result.expires_at - clock()
    def valid():
        remaining = 0.5 if result.expires_at is None else result.expires_at - clock()
        return (math.isfinite(remaining) and remaining > 0
                and (result.session_generation is None
                     or state.session_generation == result.session_generation))

    if not math.isfinite(ttl) or ttl <= 0 or not valid():
        return replace(result, status="unavailable", text="Camera view is unavailable",
                       reason="stale_scene")
    speech.speak(result.text, priority=Priority.LOW if result.status == "success" else Priority.NORMAL,
                 ttl_seconds=ttl, is_valid=valid)
    return result
