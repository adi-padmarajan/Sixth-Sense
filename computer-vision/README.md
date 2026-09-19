# Computer Vision

Live object tracking with on-screen pixel distances between tracked objects.
This is the current state of the vision prototype for sixth-sense; it is a
preview/demo tool, not yet the structured scene-evidence pipeline described in
the repository guides.

## What `track_distances.py` does

1. Loads the local Objects365 checkpoint `yolo26n-objv1-150.pt` (resolved relative to the script).
2. Runs Ultralytics tracking on the camera at index `0` (`persist=True`, `conf=0.35`).
3. Draws the annotated boxes, class names, and track IDs.
4. For every frame, draws a line between tracked objects and labels it with the
   distance **in pixels** between their bounding-box centroids:
   - if at least one `person` is in view, lines run from each person to every other object;
   - otherwise all object pairs are connected.
5. Prints each measurement to the terminal, e.g. `person#1 <-> cup#3: 400px`.

Press `q` in the preview window to quit. Capture, windows, and any writer are
released on exit, including Ctrl-C and errors.

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
cd "Computer Vision"
python3 track_distances.py
```

Requires an available camera at index `0`, camera permission, and a GUI.
Importing the module has no side effects; everything runs inside `main()`.

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

- Structured `Detection` / `SceneEvidence` / `HealthEvent` output for the assistant.
- Command-line flags for source selection or headless mode (edit the constants instead).
- Frame age / staleness reporting and session resets on camera reconnect.
- Left/centre/right image regions.
- Tests under `Tests/`.
- Depth or metric range estimation (deliberately out of scope for this script).
