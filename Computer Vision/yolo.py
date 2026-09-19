from ultralytics import YOLO

model = YOLO("yolo11n.pt")
results = model.predict(
    source=0,
    stream=True,
    show=True
)

for result in results:

    for box in result.boxes:

        name = model.names[int(box.cls)]
        conf = float(box.conf)

        print(f"{name}: {conf:.2f}")