from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "benchmark_base/bin/lio-benchmark"


def load_cli():
    loader = importlib.machinery.SourceFileLoader("lio_benchmark_cli_dataset_intake", str(CLI))
    spec = importlib.util.spec_from_loader("lio_benchmark_cli_dataset_intake", loader)
    if spec is None:
        raise RuntimeError("unable to load public CLI")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class DatasetIntakeCliContractTest(unittest.TestCase):
    def test_probe_parser_exposes_only_bag_and_optional_output(self) -> None:
        module = load_cli()
        parser = module.build_parser()
        args = parser.parse_args(["dataset", "probe", "--bag", "/data/bag"])
        self.assertEqual(Path("/data/bag"), args.bag)
        self.assertIsNone(args.output)
        self.assertIs(args.func, module.cmd_dataset_probe)

        args = parser.parse_args(
            ["dataset", "probe", "--bag", "/data/bag", "--output", "/tmp/probe.json"]
        )
        self.assertEqual(Path("/tmp/probe.json"), args.output)

        for forbidden in (
            ["--lidar-topic", "/livox/lidar"],
            ["--imu-topic", "/livox/imu"],
            ["--profile", "mid360-internal"],
            ["--overwrite"],
            ["--fix"],
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["dataset", "probe", "--bag", "/data/bag", *forbidden])

    def test_freeze_parser_exposes_frozen_v1_surface_only(self) -> None:
        module = load_cli()
        parser = module.build_parser()
        base = [
            "dataset", "freeze",
            "--probe", "/tmp/probe.json",
            "--dataset-id", "field_mid360",
            "--lidar-topic", "/livox/lidar",
            "--imu-topic", "/livox/imu",
            "--profile", "mid360-internal",
            "--imu-angular-velocity-unit", "rad_s",
            "--imu-linear-acceleration-unit", "g_like_raw",
            "--output", "/tmp/frozen",
        ]
        args = parser.parse_args(base)
        self.assertEqual("field_mid360", args.dataset_id)
        self.assertEqual("mid360-internal", args.profile)
        self.assertEqual("rad_s", args.imu_angular_velocity_unit)
        self.assertEqual("g_like_raw", args.imu_linear_acceleration_unit)
        self.assertIsNone(args.rotation_lidar_to_imu)
        self.assertIsNone(args.translation_lidar_to_imu)
        self.assertIsNone(args.calibration_source)
        self.assertIs(args.func, module.cmd_dataset_freeze)

        user = parser.parse_args(
            [
                *base[: base.index("mid360-internal")],
                "mid360-user-extrinsic",
                *base[base.index("mid360-internal") + 1 :],
                "--rotation-lidar-to-imu", "1", "0", "0", "0", "1", "0", "0", "0", "1",
                "--translation-lidar-to-imu", "0.1", "-0.2", "0.3",
                "--calibration-source", "field-calib",
            ]
        )
        self.assertEqual(9, len(user.rotation_lidar_to_imu))
        self.assertEqual([0.1, -0.2, 0.3], user.translation_lidar_to_imu)
        self.assertEqual("field-calib", user.calibration_source)

        for forbidden in (
            ["--overwrite"],
            ["--autodetect-calibration"],
            ["--algorithm", "fast_lio2"],
            ["--algorithms", "fast_lio2"],
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(SystemExit):
                    parser.parse_args([*base, *forbidden])

    def test_probe_handler_invokes_only_probe_evaluator(self) -> None:
        module = load_cli()
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0)

        with mock.patch.object(module.subprocess, "run", side_effect=fake_run):
            code = module.cmd_dataset_probe(
                SimpleNamespace(bag=Path("/frozen/bag"), output=Path("/tmp/probe.json"))
            )
        self.assertEqual(0, code)
        self.assertEqual(1, len(calls))
        command = calls[0][0]
        self.assertIn("evaluators/probe_dataset.py", command[1])
        self.assertEqual(
            ["--bag", "/frozen/bag", "--output", "/tmp/probe.json"],
            command[2:],
        )
        self.assertNotIn("run_python_ros", str(calls))

    def test_freeze_handler_invokes_only_pure_freeze_evaluator(self) -> None:
        module = load_cli()
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0)

        args = SimpleNamespace(
            probe=Path("/tmp/probe.json"),
            dataset_id="field_mid360",
            lidar_topic="/lidar",
            imu_topic="/imu",
            profile="mid360-user-extrinsic",
            imu_angular_velocity_unit="rad_s",
            imu_linear_acceleration_unit="m_s2",
            output=Path("/tmp/dataset"),
            rotation_lidar_to_imu=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            translation_lidar_to_imu=[0.1, 0.2, 0.3],
            calibration_source="manual-calib",
        )
        with mock.patch.object(module.subprocess, "run", side_effect=fake_run):
            code = module.cmd_dataset_freeze(args)
        self.assertEqual(0, code)
        self.assertEqual(1, len(calls))
        command = calls[0][0]
        self.assertIn("evaluators/freeze_dataset.py", command[1])
        self.assertIn("--rotation-lidar-to-imu", command)
        self.assertIn("--translation-lidar-to-imu", command)
        self.assertIn("--calibration-source", command)
        self.assertNotIn("evaluators/probe_dataset.py", str(command))

    def test_only_probe_side_has_rosbag_dependency(self) -> None:
        probe = (ROOT / "evaluators/probe_dataset.py").read_text(encoding="utf-8")
        freeze = (ROOT / "evaluators/freeze_dataset.py").read_text(encoding="utf-8")
        shared = (ROOT / "benchmark_base/lib/rosbag_inspection.py").read_text(encoding="utf-8")
        self.assertIn("rosbag_inspection", probe)
        self.assertIn("rosbag2_py", shared)
        for forbidden in (
            "rosbag2_py",
            "rclpy",
            "standardize_map",
            "run_process_with_metrics",
            "generate_report",
        ):
            self.assertNotIn(forbidden, freeze)


if __name__ == "__main__":
    unittest.main()
