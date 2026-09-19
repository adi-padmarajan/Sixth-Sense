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
from pathlib import Path

import cv2
from ultralytics import YOLO

MODEL_PATH = Path(__file__).resolve().parent / "yolo26n-objv1-150.pt"
SOURCE = 0            # camera index, or a path to an image/video file
CONF = 0.35           # detection threshold; provisional, not a measured optimum
ANCHOR_CLASS = "person"  # measure from this class to others when present
MAX_OBJECTS = 8       # cap on tracked objects drawn per frame to limit clutter
RECORD_PATH = None    # e.g. "distance_output.mp4" to save the annotated output (opt-in)

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


def main() -> None:
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Model checkpoint not found: {MODEL_PATH}")

    model = YOLO(str(MODEL_PATH))
    names = model.names
    anchor_class_id = next((k for k, v in names.items() if v.lower() == ANCHOR_CLASS), None)

    results = model.track(source=SOURCE, stream=True, persist=True, conf=CONF, verbose=False)
    video_writer = None

    try:
        for result in results:
            frame = result.plot()  # boxes, labels, track IDs

            objects = []
            boxes = result.boxes
            if boxes is not None and len(boxes):
                ids = boxes.id.int().tolist() if boxes.id is not None else [None] * len(boxes)
                for xyxy, cls, tid in zip(boxes.xyxy.tolist(), boxes.cls.int().tolist(), ids):
                    label = names[cls] if tid is None else f"{names[cls]}#{tid}"
                    objects.append({"cls": cls, "c": centroid(xyxy), "label": label})
                objects = objects[:MAX_OBJECTS]

            for a, b, dist in draw_distances(frame, objects, anchor_class_id):
                print(f"{a} <-> {b}: {dist:.0f}px")

            if RECORD_PATH and video_writer is None:
                h, w = frame.shape[:2]
                video_writer = cv2.VideoWriter(RECORD_PATH, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (w, h))
            if video_writer is not None:
                video_writer.write(frame)

            cv2.imshow("YOLO Distances", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        if video_writer is not None:
            video_writer.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
