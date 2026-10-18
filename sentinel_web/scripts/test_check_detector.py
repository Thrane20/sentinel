import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import cv2
import numpy as np

spec = importlib.util.spec_from_file_location("check_detector", Path(__file__).with_name("check-detector.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class SnapshotCheckTests(unittest.TestCase):
    def setUp(self):
        self.image = cv2.imencode(".png", np.zeros((16, 16, 3), np.uint8))[1].tobytes()

    def select(self, available, events=None):
        paths = []

        def get(path):
            paths.append(path)
            if path in available:
                return available[path]
            raise HTTPError(path, 404, "Not found", {}, None)

        with patch.object(check, "get", side_effect=get), contextlib.redirect_stdout(io.StringIO()) as output:
            event, image = check.comparison_snapshot(events or [{"id": "new"}])
        self.assertEqual(image.shape, (16, 16, 3))
        return event, paths, output.getvalue()

    def test_webp_endpoint(self):
        _, paths, _ = self.select({"events/new/snapshot-clean.webp": self.image})
        self.assertEqual(paths, ["events/new/snapshot-clean.webp"])

    def test_legacy_png_after_webp_404(self):
        _, paths, _ = self.select({"events/new/snapshot-clean.png": self.image})
        self.assertEqual(paths[-1], "events/new/snapshot-clean.png")

    def test_older_clean_snapshot_preferred_over_new_annotated_jpeg(self):
        event, paths, _ = self.select(
            {"events/old/snapshot-clean.webp": self.image},
            [{"id": "new"}, {"id": "old"}],
        )
        self.assertEqual(event["id"], "old")
        self.assertFalse(any("snapshot.jpg" in path for path in paths))

    def test_jpeg_fallback_warns_about_annotations(self):
        _, _, output = self.select({"events/new/snapshot.jpg?bbox=0&timestamp=0&crop=0": self.image})
        self.assertIn("WARNING", output)
        self.assertIn("annotations", output)

    def test_missing_or_invalid_images_give_actionable_error(self):
        with patch.object(check, "get", return_value=b"not an image"):
            with self.assertRaisesRegex(RuntimeError, "Wait for a new detection"):
                check.comparison_snapshot([{"id": "new"}])

    def test_authentication_failure_is_not_hidden_by_fallback(self):
        with patch.object(check, "get", side_effect=HTTPError("local", 401, "Unauthorized", {}, None)):
            with self.assertRaises(HTTPError):
                check.comparison_snapshot([{"id": "new"}])

    def test_missing_api_device_uses_explicit_file_diagnostic_without_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yml"
            config_path.write_text("detectors:\n  openvino:\n    device: GPU\nmqtt:\n  password: do-not-print\n")
            with contextlib.redirect_stdout(io.StringIO()) as output:
                check.configured_devices({"detectors": {"openvino": {"device": None}}}, config_path)
        self.assertIn("not reported by API", output.getvalue())
        self.assertIn("GPU", output.getvalue())
        self.assertNotIn("do-not-print", output.getvalue())

    def test_precision_comparison_reuses_identical_input(self):
        core = MagicMock()
        core.available_devices = ["CPU", "GPU.0"]
        compiled = core.compile_model.return_value
        compiled.output.return_value = "output"
        compiled.return_value = {"output": np.zeros((0, 7), np.float32)}
        tensor = np.zeros((1, 3, 640, 640), np.float32)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            check.inference_checks(core, "/model.onnx", tensor)
        self.assertEqual(core.compile_model.call_count, 3)
        fp32_call = core.compile_model.call_args_list[-1]
        self.assertEqual(fp32_call.args, ("/model.onnx", "GPU", {"INFERENCE_PRECISION_HINT": check.ov.Type.f32}))
        for invocation in compiled.call_args_list:
            self.assertIs(invocation.args[0][0], tensor)
        self.assertIn("GPU FP32:", output.getvalue())

    def test_failed_default_gpu_still_tests_fp32(self):
        core = MagicMock()
        core.available_devices = ["GPU"]
        compiled = MagicMock()
        compiled.output.return_value = "output"
        compiled.return_value = {"output": np.zeros((0, 7), np.float32)}
        core.compile_model.side_effect = [RuntimeError("default failed"), compiled]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            check.inference_checks(core, "/model.onnx", np.zeros((1, 3, 8, 8)))
        self.assertIn("GPU failed: default failed", output.getvalue())
        self.assertIn("GPU FP32:", output.getvalue())
        self.assertEqual(core.compile_model.call_count, 2)


if __name__ == "__main__":
    unittest.main()
