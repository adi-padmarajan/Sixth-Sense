from ultralytics import YOLO
import numpy as np

# Object detector
detector = YOLO("yolo26n.pt")

# Depth estimator
depth_model = YOLO("yolo26n-depth.pt")

results = detector.predict(
    source=0,
    stream=True,
    show=True,
    verbose=False
)

for result in results:

    # The actual webcam frame that YOLO just processed
    frame = result.orig_img

    # Run depth estimation on the SAME frame
    depth_result = depth_model.predict(
        frame,
        verbose=False
    )[0]

    # H x W array, values are estimated distance in meters
    depth = depth_result.depth.data.cpu().numpy()

    for box in result.boxes:

        name = detector.names[int(box.cls)]
        conf = float(box.conf)

        # Detection bounding box
        x1, y1, x2, y2 = map(
            int,
            box.xyxy[0].cpu().numpy()
        )

        # ---------------------------
        # Estimate object distance
        # ---------------------------

        # Don't use the whole bounding box because edges
        # often contain background pixels.
        width = x2 - x1
        height = y2 - y1

        margin_x = int(width * 0.25)
        margin_y = int(height * 0.25)

        cx1 = x1 + margin_x
        cy1 = y1 + margin_y
        cx2 = x2 - margin_x
        cy2 = y2 - margin_y

        object_depth = depth[cy1:cy2, cx1:cx2]

        # Remove invalid values
        valid_depth = object_depth[
            np.isfinite(object_depth) & (object_depth > 0)
        ]

        if len(valid_depth) > 0:
            distance = np.median(valid_depth)

            print(
                f"{name}: "
                f"{conf:.2f} confidence | "
                f"{distance:.2f} m away"
            )