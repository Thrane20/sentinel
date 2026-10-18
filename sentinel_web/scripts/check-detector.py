"""Read-only CPU/GPU comparison, run inside the existing Frigate container."""

import json
import urllib.request

import cv2
import numpy as np
import openvino as ov


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:5000/api/" + path, timeout=15) as response:
        return response.read()


def main():
    config = json.loads(get("config"))
    model = config["model"]
    print("Model:", model.get("model_type"), "input dtype:", model.get("input_dtype"))
    print("Configured detectors:", {key: value.get("device") for key, value in config["detectors"].items()})
    events = json.loads(get("events?labels=animal&has_snapshot=1&limit=1"))
    if not events:
        raise RuntimeError("No animal snapshot is available for comparison.")
    event = events[0]
    # The clean copy avoids feeding Frigate's own bounding box/text into the model.
    image = cv2.imdecode(np.frombuffer(get(f"events/{event['id']}/snapshot-clean.png"), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Could not decode the clean event snapshot.")
    print("Event:", event["id"], "camera:", event["camera"], "saved score:", event.get("data", {}).get("score", event.get("top_score")))
    if model.get("model_type") != "yolonas" or model.get("input_tensor") != "nchw":
        raise RuntimeError("This check expects Sentinel's flat YOLO-NAS adapter and NCHW input.")
    if model.get("input_dtype") != "float":
        raise RuntimeError("Unexpected input dtype: Sentinel's MegaDetector requires normalized float input.")
    image = cv2.resize(image, (model["width"], model["height"]))
    if model.get("input_pixel_format") == "rgb":
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    tensor = np.ascontiguousarray(image.transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
    core = ov.Core()
    print("Available OpenVINO devices:", core.available_devices)
    for device in ["CPU", "GPU"]:
        if not any(value == device or value.startswith(device + ".") for value in core.available_devices):
            print(device + ": unavailable")
            continue
        try:
            compiled = core.compile_model(model["path"], device)
            rows = compiled([tensor])[compiled.output(0)]
            animals = rows[rows[:, 6] == 0]
            scores = sorted((float(row[5]) for row in animals), reverse=True)
            print(device + ":", json.dumps({"animalCount": len(scores), "highestAnimalScores": scores[:5], "allOutputsFinite": bool(np.isfinite(rows).all())}))
        except Exception as error:
            print(device + " failed:", str(error))
    print("Both devices tested the same full frame. Frigate normally tests cropped regions, so these scores need not equal the saved event score.")


if __name__ == "__main__":
    main()
