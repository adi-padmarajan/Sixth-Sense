"""Live YOLO tracking with automatic object-to-object pixel distances.

Every frame, tracked objects are connected by lines labelled with the pixel
distance between their bounding-box centroids. If any person is in view, lines
run from each person to every other tracked object; otherwise all pairs are
connected. No mouse interaction is needed.

These are image-space measurements (pixels between two objects in the frame),
not camera-to-object ranges. They must not be treated as a substitute for the
physical distance sensors.

Controls (preview window must have focus):
  q  quit
"""

import itertools
import math
import logging
from pathlib import Path
import time
from typing import Callable

import cv2
import numpy as np
from ultralytics import YOLO

from scene_state import SceneState

MODEL_PATH = Path(__file__).resolve().parent / "yolo26n-objv1-150.pt"
SOURCE = 0            # camera index, or a path to an image/video file
CONF = 0.35           # detection threshold; provisional, not a measured optimum
ANCHOR_CLASS = "person"  # measure from this class to others when present
MAX_OBJECTS = 8       # cap on tracked objects drawn per frame to limit clutter
RECORD_PATH = None    # e.g. "distance_output.mp4" to save the annotated output (opt-in)
MIRROR_PREVIEW: bool = False  # display only; never changes published evidence
RECONNECT_INITIAL_DELAY_S = 0.5  # provisional bench timings
RECONNECT_MAX_DELAY_S = 5.0
UNAVAILABLE_FRAME_SHAPE = (480, 640, 3)
PREVIEW_POLL_MS = 50
log = logging.getLogger(__name__)

LINE_COLOR = (104, 31, 17)
CENTROID_COLOR = (255, 0, 255)
TEXT_COLOR = (255, 255, 255)


def centroid(xyxy):
    x0, y0, x1, y1 = xyxy
    return int((x0 + x1) / 2), int((y0 + y1) / 2)


def object_pairs(objects, anchor_class_id):
    """Yield index pairs to measure: anchor→others if an anchor exists, else all pairs."""
    anchors = [i for i, o in enumerate(objects) if o["cls"] == anchor_class_id]
    if anchors:
        for a in anchors:
            for j, o in enumerate(objects):
                if j != a and (o["cls"] != anchor_class_id or j > a):
                    yield a, j
    else:
        yield from itertools.combinations(range(len(objects)), 2)


def draw_distances(frame, objects, anchor_class_id):
    """Draw centroid-to-centroid lines and pixel distances; return list of measurements."""
    measurements = []
    for i, j in object_pairs(objects, anchor_class_id):
        a, b = objects[i], objects[j]
        dist = math.hypot(a["c"][0] - b["c"][0], a["c"][1] - b["c"][1])
        mid = ((a["c"][0] + b["c"][0]) // 2, (a["c"][1] + b["c"][1]) // 2)
        cv2.line(frame, a["c"], b["c"], LINE_COLOR, 3)
        cv2.putText(frame, f"{dist:.0f}px", mid, cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT_COLOR, 2, cv2.LINE_AA)
        measurements.append((a["label"], b["label"], dist))
    for o in objects:
        cv2.circle(frame, o["c"], 6, CENTROID_COLOR, -1)
    return measurements


def reset_session(model, state: SceneState) -> None:
    """Invalidate evidence and reset persistent Ultralytics tracker histories/IDs.

    Verified in installed Ultralytics 8.4.138: predict() reuses model.predictor,
    and on_predict_start returns early when trackers exist and persist=True.
    Merely calling track() again therefore does NOT reset a tracking session.
    """
    state.reset()
    predictor = getattr(model, "predictor", None)
    if predictor is not None:
        for tracker in getattr(predictor, "trackers", ()):
            tracker.reset()
        predictor._feats = None
        if hasattr(predictor, "vid_path"):
            predictor.vid_path = [None] * len(predictor.vid_path)


def close_source(model, results):
    """Release a generator and its loader even when iteration raised or quit early."""
    resources = [getattr(results, "close", None)]
    dataset = getattr(getattr(model, "predictor", None), "dataset", None)
    if dataset is not None:
        close = getattr(dataset, "close", None)
        resources.append(close if callable(close) else getattr(getattr(dataset, "cap", None), "release", None))
    for close in resources:
        if callable(close):
            try:
                close()
            except Exception:
                log.warning("camera_cleanup_failed reason=source_close_failed")


def overlay_status(frame, camera, preview_status):
    cloud = preview_status() if preview_status is not None else "off"
    cv2.putText(frame, f"cloud {cloud} | camera {camera}", (12, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT_COLOR, 2, cv2.LINE_AA)


def plot_validated(result, snapshot):
    """Ultralytics plot() also indexes names; never pass rejected boxes to it."""
    raw_count = len(result.boxes.cls.tolist()) if result.boxes is not None else 0
    if raw_count == len(snapshot.detections):
        return result.plot()
    frame = result.orig_img.copy()
    for d in snapshot.detections:
        x0, y0, x1, y1 = map(int, d.xyxy)
        cv2.rectangle(frame, (x0, y0), (x1, y1), CENTROID_COLOR, 2)
        label = d.class_name if d.track_id is None else f"{d.class_name}#{d.track_id}"
        cv2.putText(frame, f"{label} {d.conf:.2f}", (x0, y0),
                    cv2.FONT_HERSHEY_SIMPLEX, .6, TEXT_COLOR, 2)
    return frame


def wait_to_reconnect(delay, attempt, preview_status, *, clock=time.monotonic):
    """Pump the GUI throughout backoff; no frozen image is presented as live."""
    deadline = clock() + delay
    while True:
        frame = np.zeros(UNAVAILABLE_FRAME_SHAPE, dtype=np.uint8)
        overlay_status(frame, "unavailable", preview_status)
        cv2.putText(frame, "CAMERA UNAVAILABLE", (30, 200),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, TEXT_COLOR, 2, cv2.LINE_AA)
        cv2.putText(frame, f"Reconnect attempt {attempt} | q to quit", (30, 250),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, TEXT_COLOR, 2, cv2.LINE_AA)
        cv2.imshow("YOLO Distances", frame)
        if cv2.waitKey(PREVIEW_POLL_MS) & 0xFF == ord("q"):
            return False
        if clock() >= deadline:
            return True


def main(state: SceneState | None = None, *,
         preview_status: Callable[[], str] | None = None) -> None:
    if state is None:
        state = SceneState()
    state.reset()
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Model checkpoint not found: {MODEL_PATH}")

    model = YOLO(str(MODEL_PATH))
    names = model.names
    anchor_class_id = next((k for k, v in names.items() if v.lower() == ANCHOR_CLASS), None)

    results = None
    video_writer = None
    source_mode = "live" if isinstance(SOURCE, int) else "replay"
    attempt = 0
    delay = RECONNECT_INITIAL_DELAY_S

    try:
        while True:
            # Catch acquisition/inference failures only. Rendering/programming
            # errors must still surface rather than become infinite retries.
            try:
                if results is None:
                    results = iter(model.track(source=SOURCE, stream=True, persist=True,
                                               conf=CONF, verbose=False))
                result = next(results)
            except Exception as exc:
                if source_mode == "replay":
                    if isinstance(exc, StopIteration):
                        break
                    log.error("camera_unavailable reason=replay_failed")
                    raise
                reason = "live_stream_ended" if isinstance(exc, StopIteration) else "live_stream_failed"
                log.warning("camera_unavailable reason=%s", reason)
                reset_session(model, state)
                close_source(model, results)
                results = None
                attempt += 1
                if not wait_to_reconnect(delay, attempt, preview_status):
                    break
                delay = min(delay * 2, RECONNECT_MAX_DELAY_S)
                continue
            attempt = 0
            delay = RECONNECT_INITIAL_DELAY_S
            state.update(result.orig_img, result.boxes, names, source_mode)
            snapshot = state.read()
            frame = plot_validated(result, snapshot)

            objects = []
            # Reuse validated labels; an unknown class must not kill the overlay.
            for detection in snapshot.detections[:MAX_OBJECTS]:
                tid = detection.track_id
                label = detection.class_name if tid is None else f"{detection.class_name}#{tid}"
                objects.append({"cls": detection.class_id, "c": centroid(detection.xyxy), "label": label})

            for a, b, dist in draw_distances(frame, objects, anchor_class_id):
                print(f"{a} <-> {b}: {dist:.0f}px")

            if RECORD_PATH and video_writer is None:
                h, w = frame.shape[:2]
                video_writer = cv2.VideoWriter(RECORD_PATH, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (w, h))
            if video_writer is not None:
                video_writer.write(frame)

            display = cv2.flip(frame, 1) if MIRROR_PREVIEW else frame.copy()
            camera_status = source_mode if snapshot.quality == "ok" else f"low quality ({snapshot.quality})"
            overlay_status(display, camera_status, preview_status)
            cv2.imshow("YOLO Distances", display)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        reset_session(model, state)
        close_source(model, results)
        if video_writer is not None:
            video_writer.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
