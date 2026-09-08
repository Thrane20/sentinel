import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile

import onnx
from onnx import TensorProto, helper

MODEL_URL = os.getenv(
    "ANIMAL_MODEL_URL",
    "https://zenodo.org/api/records/22018132/files/"
    "camera_trap__detector__MDV6-mit-yolov9-c.zip/content",
)
MODEL_SHA256 = os.getenv(
    "ANIMAL_MODEL_SHA256",
    "da4aa4505f8350dcb2cf2001bc329232e1f78188dc1614141a523ff9ef090655",
)
MODEL_DIR = pathlib.Path("/models")
CONFIG_DIR = pathlib.Path("/frigate-config")
MODEL_PATH = MODEL_DIR / "MDV6-mit-yolov9-c.onnx"
ADAPTER_MARKER = MODEL_DIR / ".frigate-yolonas-adapter-v1"

CAMERAS = (
    ("ch01", "01"),
    ("ch03", "03"),
    ("ch04", "04"),
    ("ch05", "05"),
    ("ch06", "06"),
    ("ch08", "08"),
)


def install_model() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if MODEL_PATH.exists() and ADAPTER_MARKER.exists():
        print(f"Animal model already installed at {MODEL_PATH}")
        return

    with tempfile.NamedTemporaryFile(suffix=".zip") as downloaded:
        print("Downloading pinned MegaDetector V6 MIT model...")
        with urllib.request.urlopen(MODEL_URL, timeout=300) as response:
            shutil.copyfileobj(response, downloaded)
        downloaded.flush()
        digest = hashlib.sha256(pathlib.Path(downloaded.name).read_bytes()).hexdigest()
        if digest != MODEL_SHA256:
            raise RuntimeError(
                f"Model checksum mismatch: expected {MODEL_SHA256}, received {digest}"
            )
        with zipfile.ZipFile(downloaded.name) as archive:
            member = "MDV6-mit-yolov9-c/1/model.onnx"
            if member not in archive.namelist():
                raise RuntimeError("Pinned model archive has an unexpected layout")
            with archive.open(member) as source, tempfile.NamedTemporaryFile(
                dir=MODEL_DIR, delete=False
            ) as target:
                shutil.copyfileobj(source, target)
                temporary = pathlib.Path(target.name)
            adapt_for_frigate(temporary)
            temporary.unlink(missing_ok=True)
            ADAPTER_MARKER.write_text("Squeeze [1,N,6] and map to Frigate YOLO-NAS [N,7].\n")
    print(f"Installed {MODEL_PATH}")


def adapt_for_frigate(source: pathlib.Path) -> None:
    """Adapt MegaDetector's end-to-end rows for Frigate's flat YOLO-NAS reader.

    MegaDetector emits [1,N,6] rows as x1,y1,x2,y2,score,class. Frigate's
    YOLO-NAS path accepts [N,7] rows as ignored,x1,y1,x2,y2,score,class.
    The model already performs NMS, so the adapter only reshapes/reorders data.
    """
    model = onnx.load(source)
    original_output = model.graph.output[0].name
    axes = helper.make_tensor("sentinel_squeeze_axes", TensorProto.INT64, [1], [0])
    indices = helper.make_tensor(
        "sentinel_column_indices", TensorProto.INT64, [7], [0, 0, 1, 2, 3, 4, 5]
    )
    model.graph.initializer.extend([axes, indices])
    model.graph.node.extend(
        [
            helper.make_node(
                "Squeeze",
                [original_output, "sentinel_squeeze_axes"],
                ["sentinel_squeezed"],
                name="SentinelSqueezeBatch",
            ),
            helper.make_node(
                "Gather",
                ["sentinel_squeezed", "sentinel_column_indices"],
                ["sentinel_frigate_output"],
                axis=1,
                name="SentinelFrigateColumns",
            ),
        ]
    )
    del model.graph.output[:]
    model.graph.output.extend(
        [
            helper.make_tensor_value_info(
                "sentinel_frigate_output", TensorProto.FLOAT, ["num_detections", 7]
            )
        ]
    )
    onnx.checker.check_model(model)
    onnx.save(model, MODEL_PATH)


def rtsp_url(channel: str) -> str:
    # Frigate performs the required FFmpeg password escaping when it loads the
    # config. Supplying a pre-escaped value here would encode '%' a second time.
    username = os.environ["IVSEC_USERNAME"]
    password = os.environ["IVSEC_PASSWORD"]
    host = os.getenv("IVSEC_HOST", "192.168.68.203")
    stream = os.getenv("IVSEC_SNAPSHOT_STREAM_INDEX", "2")
    return f"rtsp://{username}:{password}@{host}:554/ch{channel}/{stream}"


def camera_config(name: str, channel: str) -> str:
    source = json.dumps(rtsp_url(channel))
    max_area = "\n          max_area: 0.10" if channel == "05" else ""
    object_mask = os.getenv(f"FRIGATE_OBJECT_MASK_CH{channel}", "").strip()
    mask_line = f"\n          mask: {json.dumps(object_mask)}" if object_mask else ""
    return f"""  {name}:
    ffmpeg:
      inputs:
        - path: {source}
          input_args: preset-rtsp-generic
          roles: [detect]
    detect:
      enabled: true
      width: 640
      height: 360
      fps: 2
    motion:
      threshold: 35
      contour_area: 20
    objects:
      track: [animal]
      filters:
        animal:
          min_score: 0.72
          threshold: 0.80
          min_area: 0.007{max_area}{mask_line}
    record:
      enabled: false
    snapshots:
      enabled: true
      clean_copy: true
      retain:
        default: 30
"""


def write_config() -> None:
    required = ("IVSEC_USERNAME", "IVSEC_PASSWORD")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing required recorder configuration: {', '.join(missing)}")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    device = os.getenv("FRIGATE_OPENVINO_DEVICE", "AUTO").upper()
    if device not in {"AUTO", "GPU", "CPU"}:
        raise RuntimeError("FRIGATE_OPENVINO_DEVICE must be AUTO, GPU, or CPU")
    config = f"""mqtt:
  enabled: true
  host: mqtt
  port: 1883
  topic_prefix: frigate

detectors:
  openvino:
    type: openvino
    device: {device}

model:
  model_type: yolonas
  width: 640
  height: 640
  input_tensor: nchw
  input_dtype: float
  input_pixel_format: rgb
  path: /models/MDV6-mit-yolov9-c.onnx
  labelmap_path: /models/labels.txt

birdseye:
  enabled: false

audio:
  enabled: false

record:
  enabled: false

snapshots:
  enabled: true
  retain:
    default: 30

cameras:
"""
    config += "".join(camera_config(name, channel) for name, channel in CAMERAS)
    (MODEL_DIR / "labels.txt").write_text("0 animal\n1 person\n2 vehicle\n")
    temporary = CONFIG_DIR / "config.yml.tmp"
    temporary.write_text(config)
    temporary.replace(CONFIG_DIR / "config.yml")
    print(f"Wrote Frigate config for {len(CAMERAS)} cameras using {device}")


if __name__ == "__main__":
    try:
        install_model()
        write_config()
    except Exception as error:
        print(f"Model setup failed: {error}", file=sys.stderr)
        raise SystemExit(1)
