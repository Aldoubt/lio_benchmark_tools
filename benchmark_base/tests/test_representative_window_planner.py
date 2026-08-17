from __future__ import annotations

import json
from pathlib import Path
import unittest

from benchmark_base.lib.representative_windows import (
    SelectedWindow,
    WindowFeature,
    build_child_experiment_config,
    validate_selector_manifest,
)


ROOT = Path(__file__).resolve().parents[2]
EVALUATOR = ROOT / "evaluators/plan_representative_windows.py"
SELECTOR_CONFIG = ROOT / "benchmark_base/config/green_house_representative_window_selector.json"


def selector_manifest() -> dict:
    return {
        "schema_version": 2,
        "source_schema_version": 2,
        "name": "green_house_representative_window_selector",
        "workspace": "/home/yangxuan/agt_navigation_v2",
        "output_root": "/home/yangxuan/lio_benchmark_runs/green_house",
        "dataset_ref": "green_house_mid360",
        "algorithm_refs": ["fast_livo2", "fast_lio2", "kiss_icp"],
        "execution_overrides": {
            "fast_lio2": {"executable": "/home/yangxuan/RM-NAV/build/fast_lio/fastlio_mapping"}
        },
        "runtime_overlays": {
            "kiss_icp": [
                "/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash"
            ]
        },
        "replay": {"rate": 1.0, "start_offset_s": 0.0, "duration_s": None},
        "standardization": {
            "map_scan_step": 5,
            "map_point_step": 8,
            "map_voxel_m": 0.12,
            "near_range_m": 0.5,
            "trajectory_time_tolerance_s": 0.05,
        },
        "dataset": {"dataset_id": "green_house_mid360"},
        "algorithms": {"fast_livo2": {}, "fast_lio2": {}, "kiss_icp": {}},
    }


def selected(label: str, start: float) -> SelectedWindow:
    feature = WindowFeature(
        start_offset_s=start,
        duration_s=45.0,
        lidar_scan_count=450,
        imu_sample_count=9000,
        gyro_rms_rad_s=0.1,
        gyro_p95_rad_s=0.2,
        accel_dynamic_rms_native=0.1,
        scene_change_mean=0.2,
        geometric_degeneracy_median=0.3,
        geometric_degeneracy_p90=0.4,
        valid=True,
    )
    return SelectedWindow(label, start, 45.0, 0.5, feature)


class RepresentativeWindowPlannerTest(unittest.TestCase):
    def test_selector_manifest_requires_full_bag_replay(self) -> None:
        manifest = selector_manifest()
        validate_selector_manifest(manifest)

        truncated = selector_manifest()
        truncated["replay"] = {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 15.0}
        with self.assertRaisesRegex(ValueError, "full-bag replay"):
            validate_selector_manifest(truncated)

        offset = selector_manifest()
        offset["replay"] = {"rate": 1.0, "start_offset_s": 5.0, "duration_s": None}
        with self.assertRaisesRegex(ValueError, "full-bag replay"):
            validate_selector_manifest(offset)

    def test_child_config_preserves_execution_contract_and_changes_replay(self) -> None:
        manifest = selector_manifest()
        window = selected("high_angular_motion", 125.0)
        config = build_child_experiment_config(manifest, window)

        self.assertEqual(2, config["schema_version"])
        self.assertEqual("green_house_mid360", config["dataset"])
        self.assertEqual(["fast_livo2", "fast_lio2", "kiss_icp"], config["algorithms"])
        self.assertEqual(manifest["workspace"], config["workspace"])
        self.assertEqual(manifest["output_root"], config["output_root"])
        self.assertEqual(manifest["execution_overrides"], config["execution_overrides"])
        self.assertEqual(manifest["runtime_overlays"], config["runtime_overlays"])
        self.assertEqual(manifest["standardization"], config["standardization"])
        self.assertEqual(
            {"rate": 1.0, "start_offset_s": 125.0, "duration_s": 45.0},
            config["replay"],
        )
        self.assertIn("high_angular_motion", config["name"])

    def test_selector_config_is_full_bag_three_algorithm_v2_config(self) -> None:
        self.assertTrue(SELECTOR_CONFIG.is_file())
        config = json.loads(SELECTOR_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(2, config["schema_version"])
        self.assertEqual("green_house_mid360", config["dataset"])
        self.assertEqual(["fast_livo2", "fast_lio2", "kiss_icp"], config["algorithms"])
        self.assertEqual(
            {"rate": 1.0, "start_offset_s": 0.0, "duration_s": None},
            config["replay"],
        )

    def test_evaluator_uses_raw_sensor_evidence_only(self) -> None:
        self.assertTrue(EVALUATOR.is_file())
        text = EVALUATOR.read_text(encoding="utf-8")
        self.assertIn("deserialize_message", text)
        self.assertIn("cloud_rows", text)
        self.assertIn("recorded_ns", text)
        self.assertIn("angular_velocity", text)
        self.assertNotIn("standardized/trajectories", text)
        self.assertNotIn("standardized/maps", text)
        self.assertNotIn("relative_se3", text.lower())

    def test_evaluator_freezes_immutable_run_local_outputs(self) -> None:
        text = EVALUATOR.read_text(encoding="utf-8")
        self.assertIn('run / "metadata" / "representative_windows"', text)
        self.assertIn('run / "configs" / "representative_windows"', text)
        self.assertIn('run / "reports" / "REPRESENTATIVE_WINDOW_PLAN.md"', text)
        self.assertIn("partial representative-window artifacts", text)
        self.assertIn("existing representative-window artifacts do not match", text)


if __name__ == "__main__":
    unittest.main()
