from ultralytics import YOLO

model = YOLO("yolo11n.pt")
results = model.predict(
    source=0,
    stream=True,
    show=True
)

'''
Dividing the frame into a 3 x 3 (left/centre/right x top/middle/bottom) grid for occupancy detection.
For each detection, figure out which zone it's in and how big it is (bigger bbox ~ closer to the camera).
Then output a tiny "occupancy" summary per frame - LEFT: person (near)   CENTRE: clear   RIGHT: chair (far)

This summary will be consumed by the haptic layer.
'''


for result in results:

    # Frame dimensions
    frame_height, frame_width = result.orig_shape
    frame_area = frame_width * frame_height

    # 3 x 3 occupancy grid
    zones = {
        "TOP_LEFT": None,
        "TOP_CENTRE": None,
        "TOP_RIGHT": None,
        "MIDDLE_LEFT": None,
        "MIDDLE_CENTRE": None,
        "MIDDLE_RIGHT": None,
        "BOTTOM_LEFT": None,
        "BOTTOM_CENTRE": None,
        "BOTTOM_RIGHT": None,
    }

    for box in result.boxes:

        name = model.names[int(box.cls)]
        conf = float(box.conf)

        print(f"{name}: {conf:.2f}")
        # Bounding box coordinates
        x1, y1, x2, y2 = box.xyxy[0].tolist()

        # Centre of bounding box
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2

        # Bounding box size
        bbox_width = x2 - x1
        bbox_height = y2 - y1
        bbox_area = bbox_width * bbox_height

        # How much of the frame does the object occupy?
        area_ratio = bbox_area / frame_area


        # Determine horizontal zone

        if cx < frame_width / 3:
            horizontal = "LEFT"
        elif cx < 2 * frame_width / 3:
            horizontal = "CENTRE"
        else:
            horizontal = "RIGHT"


        # Determine vertical zone


        if cy < frame_height / 3:
            vertical = "TOP"
        elif cy < 2 * frame_height / 3:
            vertical = "MIDDLE"
        else:
            vertical = "BOTTOM"

        zone_name = f"{vertical}_{horizontal}"


        # Convert bbox size -> approximate distance

        if area_ratio > 0.20:
            distance = "VERY NEAR"
        elif area_ratio > 0.08:
            distance = "NEAR"
        elif area_ratio > 0.02:
            distance = "MID"
        else:
            distance = "FAR"


        # Convert bbox size -> vibration intensity
        # 0.0 = off
        # 1.0 = maximum vibration

        intensity = min(area_ratio / 0.20, 1.0)

        detection = {
            "name": name,
            "confidence": conf,
            "distance": distance,
            "intensity": intensity,
            "area_ratio": area_ratio
        }

        # If multiple objects occupy the same zone,
        # keep the biggest / closest one.
        current = zones[zone_name]

        if current is None or area_ratio > current["area_ratio"]:
            zones[zone_name] = detection


    # Print occupancy grid

    print("\n---------------- FRAME ----------------")

    for row in ["TOP", "MIDDLE", "BOTTOM"]:

        output = []

        for column in ["LEFT", "CENTRE", "RIGHT"]:

            zone = f"{row}_{column}"
            detection = zones[zone]

            if detection is None:
                output.append(f"{column}: clear")
            else:
                output.append(
                    f"{column}: "
                    f"{detection['name']} "
                    f"({detection['distance']}, "
                    f"{detection['intensity']:.2f})"
                )

        print(" | ".join(output))