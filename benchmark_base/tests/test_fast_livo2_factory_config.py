from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "evaluators" / "prepare_fast_livo2_config.py"
RUNNER = ROOT / "evaluators" / "run_fast_livo_test.sh"


class FastLivo2FactoryConfigContractTest(unittest.TestCase):
    def test_generator_writes_canonical_mid360_extrinsic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            generated = run / "configs/generated/fast_livo2"
            generated.mkdir(parents=True)
            (run / "manifest.json").write_text(
                json.dumps(
                    {
                        "dataset": {
                            "topics": {
                                "lidar": "/agt/sensors/lidar/custom",
                                "imu": "/agt/sensors/imu/data",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (generated / "calibration.json").write_text(
                json.dumps(
                    {
                        "algorithm_id": "fast_livo2",
                        "convention": "LIDAR_TO_IMU",
                        "rotation_row_major": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                        "translation_m": [-0.011, -0.02329, 0.04412],
                        "canonical_convention": "LIDAR_TO_IMU",
                        "canonical_equation": "p_I = R_IL * p_L + t_IL",
                        "calibration_status": "MANUFACTURER_SPEC",
                        "calibration_source_type": "MANUFACTURER_SPEC",
                        "sensor_model": "Livox Mid-360",
                        "imu_relation": "INTERNAL_IMU",
                        "diagnostic_only": False,
                    }
                ),
                encoding="utf-8",
            )
            output = generated / "runtime_params.yaml"
            result = subprocess.run(
                [sys.executable, str(GENERATOR), "--run", str(run), "--output", str(output)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            text = output.read_text(encoding="utf-8")
            self.assertIn("lid_topic: /agt/sensors/lidar/custom", text)
            self.assertIn("imu_topic: /agt/sensors/imu/data", text)
            self.assertIn("extrinsic_T: [-0.011, -0.02329, 0.04412]", text)
            self.assertIn("extrinsic_R: [1.0, 0.0, 0.0,", text)

            metadata = json.loads(
                (generated / "adapter_config_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual("MANUFACTURER_SPEC", metadata["calibration_status"])
            self.assertEqual("LIDAR_TO_IMU", metadata["canonical_convention"])
            self.assertEqual("p_I = R_IL * p_L + t_IL", metadata["canonical_equation"])
            self.assertEqual(str(output.resolve()), metadata["config"])

    def test_runner_explicitly_generates_and_passes_run_local_params(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn('prepare_fast_livo2_config.py', text)
        self.assertIn('runtime_params.yaml', text)
        self.assertIn('params_file:="$fast_livo_params"', text)
        self.assertLess(
            text.index('prepare_fast_livo2_config.py'),
            text.index('estimator_cmd=('),
        )


if __name__ == "__main__":
    unittest.main()
