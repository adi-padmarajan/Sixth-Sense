"""Latest camera-view evidence, independent of OpenCV, YOLO, and consumers."""

from dataclasses import dataclass, replace
import math
from threading import Lock
import time
from typing import Callable, Literal

import numpy as np


SourceMode = Literal["live", "replay", "simulated"]
Region = Literal["left", "center", "right"]


@dataclass(frozen=True, slots=True)
class Detection:
    """One detection in original-image pixels; regions are camera-view positions."""

    class_id: int
    class_name: str
    conf: float
    xyxy: tuple[float, float, float, float]
    track_id: int | None
    region: Region


class _ReadOnlyDetections(list[Detection]):
    """Preserve the public list interface without exposing mutation methods."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("Snapshot detections are read-only")

    __setitem__ = __delitem__ = __iadd__ = __imul__ = _immutable
    append = clear = extend = insert = pop = remove = reverse = sort = _immutable


@dataclass(frozen=True, slots=True)
class SceneSnapshot:
    """Published evidence. Pixels are read-only, detections and fields are frozen.

    captured_at uses the source-local monotonic clock at update entry. With the
    tracking generator this is result read-completion (after inference), not
    camera exposure or the underlying VideoCapture.read() completion time.
    """

    frame: np.ndarray
    captured_at: float
    width: int
    height: int
    detections: list[Detection]
    source_mode: SourceMode
    sequence: int
    session_generation: int = 0


def detections_from_result(boxes, names, width: int) -> list[Detection]:
    """Extract boxes using only the supplied checkpoint's class map.

    For centre x, left is x < width/3, center is width/3 <= x < 2*width/3,
    and right is x >= 2*width/3. An exact boundary belongs to the region on
    its right. Coordinates stay in the original image; no scaling or clipping.
    Tensor-like inputs need only .tolist(); no Ultralytics import is needed.
    """
    if not math.isfinite(width) or width <= 0:
        raise ValueError("Image width must be positive and finite")
    if boxes is None:
        return []

    coordinates = boxes.xyxy.tolist()
    classes = boxes.cls.tolist()
    confidences = boxes.conf.tolist()
    ids = boxes.id.tolist() if boxes.id is not None else [None] * len(coordinates)
    detections = []
    for row, class_id, conf, track_id in zip(coordinates, classes, confidences, ids, strict=True):
        xyxy = tuple(float(value) for value in row)
        if len(xyxy) != 4 or not all(math.isfinite(value) for value in xyxy):
            continue
        x0, y0, x1, y1 = xyxy
        if x1 <= x0 or y1 <= y0:
            continue
        if not math.isfinite(class_id) or not math.isfinite(conf):
            continue
        class_id = int(class_id)
        center_x = x0 / 2 + x1 / 2
        region = "left" if center_x < width / 3 else "center" if center_x < 2 * width / 3 else "right"
        detections.append(Detection(
            class_id=class_id,
            class_name=names[class_id],
            conf=float(conf),
            xyxy=xyxy,
            track_id=int(track_id) if track_id is not None and math.isfinite(track_id) else None,
            region=region,
        ))
    return detections


def to_text(detections: list[Detection], age_s: float | None) -> str:
    """Format evidence only; an empty list says nothing about unseen objects."""
    if age_s is not None and (not math.isfinite(age_s) or age_s < 0):
        raise ValueError("Age must be non-negative and finite, or None")
    age = "unknown" if age_s is None else f"{age_s * 1000:.0f} ms"
    objects = ", ".join(f"{d.class_name} {d.region} {d.conf:.2f}" for d in detections)
    return f"Detected (age {age}): {objects or 'none'}"


class SceneState:
    """One writer, many readers, one latest snapshot (no frame queue).

    Writers/reset serialize on a lock; readers never acquire that lock or hold
    up publication. Readers take one reference to a fully constructed snapshot.
    This relies on atomic Python object-reference reads/assignments in CPython,
    the supported runtime, rather than mutating shared snapshot fields in place.
    Consumers can retain old snapshots without blocking future updates.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._write_lock = Lock()
        self._latest: SceneSnapshot | None = None
        self._sequence = 0
        self._session_generation = 0

    @property
    def session_generation(self) -> int:
        """Reset counter for consumers to reject in-flight results from an old session."""
        return self._session_generation

    def update(self, frame, boxes, names, source_mode: SourceMode) -> None:
        """Copy and publish the original BGR frame, timestamped before processing."""
        with self._write_lock:
            captured_at = self._clock()
            if source_mode not in ("live", "replay", "simulated"):
                raise ValueError("source_mode must be live, replay, or simulated")
            if (not isinstance(frame, np.ndarray) or frame.ndim != 3
                    or frame.shape[2] != 3 or min(frame.shape[:2]) <= 0
                    or frame.dtype != np.uint8):
                raise ValueError("Expected a non-empty uint8 BGR frame with shape (H, W, 3)")
            height, width = frame.shape[:2]
            detections = _ReadOnlyDetections(detections_from_result(boxes, names, width))
            # bytes owns the pixels: neither source reuse nor setflags(write=True)
            # can mutate published data. No JPEG encoding, resizing, or annotation.
            frozen_frame = np.frombuffer(frame.tobytes(), dtype=frame.dtype).reshape(frame.shape)
            sequence = self._sequence + 1
            snapshot = SceneSnapshot(
                frozen_frame, captured_at, width, height, detections, source_mode, sequence,
                self._session_generation,
            )
            self._sequence = sequence
            self._latest = snapshot

    def read(self, max_age_s: float | None = None) -> SceneSnapshot | None:
        """Return latest evidence; age == max_age_s is fresh, age > it is stale.

        Omitting max_age_s returns even stale evidence. Each reader receives its
        own array view so changing view metadata cannot affect another reader.
        """
        if max_age_s is not None and (not math.isfinite(max_age_s) or max_age_s < 0):
            raise ValueError("max_age_s must be non-negative and finite, or None")
        snapshot = self._latest
        if snapshot is None:
            return None
        if max_age_s is not None and self._clock() - snapshot.captured_at > max_age_s:
            return None
        return replace(snapshot, frame=snapshot.frame.view())

    def age_s(self) -> float | None:
        """Age of the latest publication, including stale evidence; None if empty.

        For text about a snapshot already read, subtract that snapshot's
        captured_at from the same clock instead: another update may have arrived.
        """
        snapshot = self._latest
        return None if snapshot is None else self._clock() - snapshot.captured_at

    def reset(self) -> None:
        """Clear evidence on a session change; the next update has sequence 1."""
        with self._write_lock:
            self._session_generation += 1
            self._latest = None
            self._sequence = 0
