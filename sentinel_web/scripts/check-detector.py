"""Read-only CPU/GPU comparison, run inside the existing Frigate container."""

import json
import inspect
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

import cv2
import numpy as np
import openvino as ov
import yaml


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:5000/api/" + path, timeout=15) as response:
        return response.read()


def configured_devices(config, config_path=Path("/config/config.yml")):
    print("Configured detector devices (API):", {
        key: value.get("device") or "not reported by API"
        for key, value in config["detectors"].items()
    })
    try:
        saved = yaml.safe_load(config_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        print("Requested detector devices (config file): unavailable")
        return
    # Print only device fields, never camera URLs or other credentials.
    print("Requested detector devices (config file):", {
        key: value.get("device") or "not specified"
        for key, value in saved.get("detectors", {}).items()
    })
    print("Requested config devices do not independently confirm the active hardware.")


def fetch_image(path):
    try:
        encoded = get(path)
    except urllib.error.HTTPError as error:
        if error.code in (404, 410):
            return None
        raise
    if not encoded:
        return None
    return cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_COLOR)


def comparison_snapshot(events):
    # Newer Frigate versions serve WebP; older versions serve PNG. A snapshot
    # flag can also precede the file being written, or outlive a missing file.
    for event in events:
        event_id = urllib.parse.quote(event["id"], safe="")
        for extension in ("webp", "png"):
            path = f"events/{event_id}/snapshot-clean.{extension}"
            image = fetch_image(path)
            if image is not None:
                print("Comparison image:", path)
                return event, image
    # Still useful for comparing hardware on identical pixels. On completed
    # events Frigate may return a JPEG with baked-in annotations despite bbox=0.
    for event in events:
        event_id = urllib.parse.quote(event["id"], safe="")
        path = f"events/{event_id}/snapshot.jpg?bbox=0&timestamp=0&crop=0"
        image = fetch_image(path)
        if image is not None:
            print("Comparison image:", path)
            print("WARNING: No clean snapshot was available. This JPEG may contain annotations, which can affect scores; both devices will still receive the same image.")
            return event, image
    raise RuntimeError("No readable snapshot was found in the latest 10 animal events. Wait for a new detection with snapshots enabled, then retry.")


def inference_checks(core, model_path, tensor):
    print("OpenVINO version:", ov.__version__)
    print("Available OpenVINO devices:", core.available_devices)
    for label, device, properties in [
        ("CPU", "CPU", {}),
        ("GPU", "GPU", {}),
        ("GPU FP32", "GPU", {"INFERENCE_PRECISION_HINT": ov.Type.f32}),
    ]:
        if not any(value == device or value.startswith(device + ".") for value in core.available_devices):
            print(label + ": unavailable")
            continue
        try:
            compiled = core.compile_model(model_path, device, properties)
            try:
                print(label + " compiled precision hint:", compiled.get_property("INFERENCE_PRECISION_HINT"))
            except RuntimeError:
                print(label + " compiled precision hint: not reported")
            rows = compiled([tensor])[compiled.output(0)]
            animals = rows[rows[:, 6] == 0]
            scores = sorted((float(row[5]) for row in animals), reverse=True)
            print(label + ":", json.dumps({"animalCount": len(scores), "highestAnimalScores": scores[:5], "allOutputsFinite": bool(np.isfinite(rows).all())}))
        except Exception as error:
            print(label + " failed:", str(error))
    print("All runs tested the same full frame. Frigate normally tests cropped regions, so these scores need not equal the saved event score.")
    print("The GPU line is an unforced baseline and can still show FP16 errors even with the production fix installed. GPU FP32 tests the precision used by the fixed Sentinel image.")
    print("This check does not change Frigate's running configuration. Confirm the production detector's device/precision in Frigate startup logs.")


def main():
    config = json.loads(get("config"))
    model = config["model"]
    print("Model:", model.get("model_type"), "input dtype:", model.get("input_dtype"))
    configured_devices(config)
    from frigate.detectors.detection_runners import OpenVINOModelRunner
    policy_installed = "sentinel_fp32" in inspect.getsource(OpenVINOModelRunner.__init__)
    print("Production MegaDetector FP32 policy:", "installed (confirm active precision in Frigate startup logs)" if policy_installed else "not installed; rebuild/redeploy Frigate to apply the fix")
    events = json.loads(get("events?labels=animal&has_snapshot=1&limit=10"))
    if not events:
        raise RuntimeError("No animal snapshot is available for comparison.")
    event, image = comparison_snapshot(events)
    print("Event:", event["id"], "camera:", event["camera"], "saved score:", event.get("data", {}).get("score", event.get("top_score")))
    if model.get("model_type") != "yolonas" or model.get("input_tensor") != "nchw":
        raise RuntimeError("This check expects Sentinel's flat YOLO-NAS adapter and NCHW input.")
    if model.get("input_dtype") != "float":
        raise RuntimeError("Unexpected input dtype: Sentinel's MegaDetector requires normalized float input.")
    image = cv2.resize(image, (model["width"], model["height"]))
    if model.get("input_pixel_format") == "rgb":
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    tensor = np.ascontiguousarray(image.transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
    inference_checks(ov.Core(), model["path"], tensor)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as error:
        print("Detector check could not complete:", str(error), file=sys.stderr)
        sys.exit(1)
