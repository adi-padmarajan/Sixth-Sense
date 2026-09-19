# Computer Vision

Live object tracking with on-screen pixel distances between tracked objects,
plus a local `SceneState` layer that exposes the latest original frame and
structured detections without consumers touching OpenCV or YOLO.

## What `track_distances.py` does

1. Loads the local Objects365 checkpoint `yolo26n-objv1-150.pt` (resolved relative to the script).
2. Runs Ultralytics tracking on the camera at index `0` (`persist=True`, `conf=0.35`).
3. Publishes the original frame and all detections into `SceneState`, then draws
   the annotated boxes, class names, and track IDs.
4. For every frame, draws a line between tracked objects and labels it with the
   distance **in pixels** between their bounding-box centroids:
   - if at least one `person` is in view, lines run from each person to every other object;
   - otherwise all object pairs are connected.
5. Prints each measurement to the terminal, e.g. `person#1 <-> cup#3: 400px`.

Press `q` in the preview window to quit. The existing `finally` block clears
`SceneState`, releases any writer, and destroys windows, including on Ctrl-C and
errors. The existing capture lifecycle is unchanged by the SceneState integration.

### Settings (constants at the top of the script)

| Constant | Default | Meaning |
| --- | --- | --- |
| `SOURCE` | `0` | Camera index, or a path to an image/video file |
| `CONF` | `0.35` | Detection confidence threshold (provisional, not a measured optimum) |
| `ANCHOR_CLASS` | `"person"` | Class to measure from; looked up in the checkpoint's own `model.names` |
| `MAX_OBJECTS` | `8` | Cap on objects drawn per frame to limit clutter |
| `RECORD_PATH` | `None` | Set to a filename (e.g. `"out.mp4"`) to save the annotated video; off by default |

## What the numbers mean — and don't

- The distances are **image-space pixel distances between two objects in the
  frame**. They are not real-world distances and not the distance from the
  camera to anything. 300 px can be 30 cm or 3 m depending on how far the
  objects are from the lens and the capture resolution.
- Track IDs (`#n`) are temporary tracker associations, not identities. They
  can change after occlusion or when an object leaves and re-enters the frame.
- An empty frame or a lost camera is not evidence that the area is clear.
  Physical range comes from the proximity sensors, never from this script.

## Run

```bash
cd computer-vision
python3 track_distances.py
```

Requires the local checkpoint `yolo26n-objv1-150.pt` (in this directory; SHA-256
`fab6114e…6253b3`), installed CV dependencies, an available camera at index `0`,
camera permission, and a GUI. If the checkpoint is missing, `main()` raises
`FileNotFoundError` — restore it with
`git show ebdc558:"Computer Vision/yolo26n-objv1-150.pt" > computer-vision/yolo26n-objv1-150.pt`
or from the repository once it is committed under the new folder name.
Importing the module has no side effects; everything runs inside `main()`.

## Scene evidence (`scene_state.py`)

`SceneState` stores one latest snapshot, with one writer and many readers.
It imports only NumPy and the standard library. A future orchestrator passes a
shared instance to `track_distances.main(state=state)` and gives that same state
to the assistant. The preview's `MAX_OBJECTS` cap does not truncate scene evidence.

`Detection` is a frozen dataclass containing `class_id`, `class_name`, `conf`,
`xyxy` (four floats in original-image pixels), nullable `track_id`, and `region`.
Labels come exclusively from `model.names`. Invalid/non-finite coordinates and
non-positive-area boxes are skipped; no distance or identity is inferred.

For box-centre x and image width W, the region is:

- `left` when x < W/3;
- `center` when W/3 <= x < 2W/3;
- `right` when x >= 2W/3.

A centre exactly on a boundary belongs to the region on its right. These are
positions in the camera view, not verified wearer-relative directions.

`SceneSnapshot` is a frozen dataclass with these fields:

| Field | Meaning |
| --- | --- |
| `frame` | Original BGR uint8 ndarray, copied before annotation; read-only pixels |
| `captured_at` | Source-local monotonic seconds sampled at `update()` entry; see timing limitation below |
| `width`, `height` | Original image dimensions in pixels |
| `detections` | Read-only `list[Detection]`; empty is valid evidence from a received frame |
| `source_mode` | `live`, `replay`, or `simulated`; the tracking script uses `live` for integer `SOURCE`, otherwise `replay` |
| `sequence` | Starts at 1, increments once per successful update; restarts at 1 after reset |

Snapshot fields and detections reject normal mutation; pixels have immutable
byte backing. Changing the source frame cannot change a published snapshot. Each
read returns its own array view, protecting other readers from view-shape changes.
Publication swaps a complete snapshot reference under CPython; readers acquire
no writer lock. Holding an old snapshot does not block updates. State retains only
the latest publication, though a consumer can retain its own older snapshot.
There is no frame queue or JPEG encoding.

### Freshness and sessions

- `read()` returns the latest snapshot, even if stale, or `None` before publication
  and after reset.
- `read(max_age_s=0.5)` returns `None` when age is **greater than** 0.5 seconds;
  equality is fresh. Negative or non-finite limits are rejected.
- `age_s()` returns the latest snapshot's age, including when stale, or `None`
  when the state is empty. It can refer to a newer publication than a preceding
  `read()`: compute age from the returned snapshot for a consistent description.
- `reset()` clears current evidence and the sequence counter. `main()` resets at
  entry and in its `finally` block. Callers must reset on any separately managed
  source restart/change and reset the corresponding YOLO tracker. Automatic
  mid-stream reconnect detection is not implemented.
- The clock is injectable (`SceneState(clock=fake_clock)`) for deterministic tests.

**Timing limitation:** `captured_at` is read-completion of the yielded YOLO
result at the loop's handoff to `update()`. YOLO has already performed inference
when it yields. It is **not** the underlying camera read-completion or sensor
exposure timestamp. Reported age excludes upstream capture buffering and YOLO
inference time. Measuring that earlier age needs separate capture-timing plumbing;
this change intentionally preserves the existing tracking path. For replay, this
is local processing time, not the recording's original capture/media timestamp.

Example consumer (given the shared `state`, with the default monotonic clock):

```python
import time
from scene_state import to_text

snapshot = state.read(max_age_s=0.5)
if snapshot is None:
    description = "Camera view is unavailable"
else:
    description = to_text(snapshot.detections, time.monotonic() - snapshot.captured_at)
```

`to_text(...)` produces `Detected (age 80 ms): chair left 0.71, person center 0.82`
or `Detected (age 80 ms): none` for an empty list. An unavailable age is rendered
as `age unknown`. No detections does not establish absence of obstacles.

## Offline tests

From the repository root:

```bash
python3 -m unittest discover -s computer-vision/Tests -p "test_*.py" -v
```

The tests use small fake boxes, a fake clock, synthetic frames, and mocked preview
and YOLO construction. They cover extraction, boundaries, missing/invalid data,
freshness, immutable evidence, concurrent reads, reset/sequence behavior, text,
import side effects, and loop wiring. Installed dependencies are needed for the
import checks; no camera, checkpoint, network, or GPU is used.

## Environment (as verified on 2026-09-19, macOS)

| Package | Version |
| --- | --- |
| Python | 3.13.5 |
| ultralytics | 8.4.138 |
| torch | 2.13.0 |
| numpy | 2.3.5 |
| opencv-python | 5.0.0.93 |

Checkpoint: `yolo26n-objv1-150.pt`, task `detect`, 365 Objects365 classes,
trained at `imgsz=640` for 150 epochs with Ultralytics 8.3.222.
SHA-256: `fab6114e4c91cac560c849ac732c0756e0575c9195e2a7fedfa4a8d92c6253b3`.
Provenance and license of the checkpoint are not yet documented.

## Not implemented yet

- The `omni/` consumer and shared-process orchestrator; JPEG/request construction.
- Full versioned `SceneEvidence` / `HealthEvent` envelopes and explicit inference-error health reporting.
- Command-line flags for source selection or headless mode (edit the constants instead).
- Automatic reconnect/session detection and tracker reset during a running stream.
- Camera read/exposure timestamps, preview stale-state indicators, and measured live performance.
- Depth or metric range estimation (deliberately out of scope for this script).
