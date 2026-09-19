from ultralytics import YOLO
import cv2

model = YOLO("yolo26n-objv1-150.pt")

results = model.track(
    source=0,
    stream=True,
    persist=True,
    conf=0.35
)

for result in results:
    frame = result.plot()

    cv2.imshow("YOLO Live Tracking", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cv2.destroyAllWindows()