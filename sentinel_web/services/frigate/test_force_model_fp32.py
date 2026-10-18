import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import openvino as ov
from frigate.detectors import detection_runners as runners

from force_model_fp32 import ORIGINAL, REPLACEMENT, patch_source


class PrecisionPolicyTests(unittest.TestCase):
    def runner(self, filename, model_type="yolonas", precision=ov.Type.f32):
        core = MagicMock()
        core.compile_model.return_value.get_property.return_value = precision
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / filename
            path.touch()
            with patch.object(runners.ov, "Core", return_value=core), patch.object(runners.OpenVINOModelRunner, "is_complex_model", return_value=True):
                runners.OpenVINOModelRunner(str(path), "GPU", model_type)
        return core.compile_model.call_args.kwargs

    def test_megadetector_requests_fp32(self):
        args = self.runner("MDV6-mit-yolov9-c.onnx")
        self.assertEqual(args["device_name"], "GPU")
        self.assertEqual(args["config"], {"INFERENCE_PRECISION_HINT": ov.Type.f32})

    def test_other_models_keep_default_precision(self):
        args = self.runner("other.onnx")
        self.assertEqual(args["config"], {})

    def test_other_model_types_keep_default_precision(self):
        args = self.runner("MDV6-mit-yolov9-c.onnx", "yologeneric")
        self.assertEqual(args["config"], {})

    def test_wrong_compiled_precision_fails_clearly(self):
        with self.assertRaisesRegex(RuntimeError, "requires FP32"):
            self.runner("MDV6-mit-yolov9-c.onnx", precision=ov.Type.f16)

    def test_patch_rejects_changed_or_already_patched_source(self):
        source = Path(runners.__file__).read_text()
        self.assertIn(REPLACEMENT, source)
        with self.assertRaisesRegex(RuntimeError, "expected exactly one"):
            patch_source(source)
        original_source = source.replace(REPLACEMENT, ORIGINAL)
        self.assertEqual(patch_source(original_source), source)
        with self.assertRaises(RuntimeError):
            patch_source(original_source.replace(ORIGINAL, ""))


if __name__ == "__main__":
    unittest.main()
