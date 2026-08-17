from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from benchmark_base.lib.calibration import canonical_lidar_to_imu, resolve_algorithm_extrinsic
from benchmark_base.lib.map_frame_contract import lidar_points_in_tracked_frame
from benchmark_base.lib.registry import Registry
from benchmark_base.lib.relative_se3 import normalize_pose_to_imu, pose_from_sample
from benchmark_base.lib.trajectory import PoseSample


ROOT = Path(__file__).resolve().parents[2]
FAST_LIO2_GENERATOR = ROOT / "evaluators/prepare_fast_lio2_config.py"


class Mid360ConsumerDirectionTest(unittest.TestCase):
    def setUp(self) -> None:
        registry = Registry()
        self.dataset = registry.load_dataset("green_house_mid360")
        self.fast_lio2 = registry.load_algorithm("fast_lio2")
        self.canonical = canonical_lidar_to_imu(self.dataset)

    def test_unified_map_imu_body_uses_negative_canonical_t_il(self) -> None:
        origin = np.asarray([[0.0, 0.0, 0.0]], dtype=np.float64)
        transformed = lidar_points_in_tracked_frame(
            origin,
            tracked_frame_physical="IMU_BODY",
            calibration=self.dataset["calibration"],
        )
        np.testing.assert_allclose(
            transformed[0],
            np.asarray([-0.011, -0.02329, 0.04412]),
            atol=1e-12,
        )

    def test_relative_se3_lidar_pose_uses_positive_inverse_t_li(self) -> None:
        identity_lidar_pose = pose_from_sample(
            PoseSample(
                timestamp_s=0.0,
                x_m=0.0,
                y_m=0.0,
                z_m=0.0,
                qx=0.0,
                qy=0.0,
                qz=0.0,
                qw=1.0,
                roll_rad=0.0,
                pitch_rad=0.0,
                yaw_rad=0.0,
                source_topic="/kiss/odometry",
            )
        )
        imu_pose = normalize_pose_to_imu(identity_lidar_pose, "LIDAR", self.canonical)
        np.testing.assert_allclose(
            np.asarray(imu_pose.translation),
            np.asarray([0.011, 0.02329, -0.04412]),
            atol=1e-12,
        )

    def test_fast_lio2_generated_yaml_uses_negative_t_il_and_fixed_extrinsic(self) -> None:
        resolved = resolve_algorithm_extrinsic(self.dataset, self.fast_lio2)
        self.assertEqual("LIDAR_TO_IMU", resolved["convention"])
        self.assertEqual([-0.011, -0.02329, 0.04412], resolved["translation_m"])
        self.assertFalse(resolved["diagnostic_only"])

        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            generated = run / "configs/generated/fast_lio2"
            generated.mkdir(parents=True)
            (run / "manifest.json").write_text(
                json.dumps({"dataset": self.dataset}),
                encoding="utf-8",
            )
            (generated / "calibration.json").write_text(
                json.dumps(resolved),
                encoding="utf-8",
            )
            output = generated / "runtime_params.yaml"
            result = subprocess.run(
                [
                    sys.executable,
                    str(FAST_LIO2_GENERATOR),
                    "--run",
                    str(run),
                    "--output",
                    str(output),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            text = output.read_text(encoding="utf-8")
            self.assertIn("extrinsic_est_en: false", text)
            self.assertIn("extrinsic_T: [-0.011, -0.02329, 0.04412]", text)
            self.assertIn(
                "extrinsic_R: [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]",
                text,
            )


if __name__ == "__main__":
    unittest.main()
