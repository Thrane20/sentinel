"""Apply a checked, model-specific precision fix to pinned Frigate 0.17.2."""

from pathlib import Path


ORIGINAL = '''        self.compiled_model = self.ov_core.compile_model(
            model=model_path, device_name=device
        )'''

REPLACEMENT = '''        # Sentinel MegaDetector saturates scores on this GPU's FP16 path.
        # Keep the policy local to this model; other Frigate models are unchanged.
        sentinel_fp32 = (
            os.path.basename(model_path) == "MDV6-mit-yolov9-c.onnx"
            and model_type == "yolonas"
        )
        self.compiled_model = self.ov_core.compile_model(
            model=model_path,
            device_name=device,
            config={"INFERENCE_PRECISION_HINT": ov.Type.f32} if sentinel_fp32 else {},
        )
        if sentinel_fp32:
            precision = self.compiled_model.get_property("INFERENCE_PRECISION_HINT")
            logger.info("Sentinel MegaDetector: device=%s inference_precision=%s", device, precision)
            if precision != ov.Type.f32:
                raise RuntimeError("Sentinel MegaDetector requires FP32 inference; compiled precision was " + str(precision))'''


def patch_source(source):
    if source.count(ORIGINAL) != 1:
        raise RuntimeError("Frigate OpenVINO runner changed: expected exactly one compile call. Review the Sentinel FP32 patch before upgrading Frigate.")
    result = source.replace(ORIGINAL, REPLACEMENT, 1)
    compile(result, "detection_runners.py", "exec")
    return result


if __name__ == "__main__":
    path = Path("/opt/frigate/frigate/detectors/detection_runners.py")
    path.write_text(patch_source(path.read_text()))
    print("Installed Sentinel MegaDetector FP32 inference policy.")
