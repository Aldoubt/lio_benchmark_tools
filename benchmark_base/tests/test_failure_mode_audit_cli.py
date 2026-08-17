from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "benchmark_base/bin/lio-benchmark"


class FailureModeAuditCliTest(unittest.TestCase):
    @staticmethod
    def _load_cli():
        loader = importlib.machinery.SourceFileLoader("lio_benchmark_cli_failure_mode", str(CLI))
        spec = importlib.util.spec_from_loader("lio_benchmark_cli_failure_mode", loader)
        if spec is None:
            raise RuntimeError("unable to load lio-benchmark CLI")
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_failure_mode_audit_exposes_only_batch_location_inputs(self) -> None:
        module = self._load_cli()
        args = module.build_parser().parse_args(
            [
                "audit",
                "failure-mode",
                "--run-root",
                "/persistent/green_house",
                "--batch-id",
                "repv1_final_20260817_133745",
            ]
        )
        self.assertEqual("audit", args.command)
        self.assertEqual("failure-mode", args.audit_command)
        self.assertEqual(Path("/persistent/green_house"), args.run_root)
        self.assertEqual("repv1_final_20260817_133745", args.batch_id)
        self.assertEqual("cmd_audit_failure_mode", args.func.__name__)

        forbidden = (
            ["--gap-multiplier", "2.0"],
            ["--window-duration-s", "30"],
            ["--algorithm", "kiss_icp"],
            ["--overwrite"],
        )
        for extra in forbidden:
            with self.subTest(extra=extra), self.assertRaises(SystemExit):
                module.build_parser().parse_args(
                    [
                        "audit",
                        "failure-mode",
                        "--run-root",
                        "/persistent/green_house",
                        "--batch-id",
                        "repv1_final_20260817_133745",
                        *extra,
                    ]
                )

    def test_handler_directly_invokes_pure_python_evaluator_without_ros_resolution(self) -> None:
        module = self._load_cli()
        calls: dict[str, object] = {}
        original_resolve_run = module._core.resolve_run
        original_run_python_ros = module._core.run_python_ros
        original_subprocess_run = module.subprocess.run

        def forbidden_resolve_run(*args, **kwargs):
            raise AssertionError("Failure-Mode Audit V1 must not resolve a child run as a ROS execution run")

        def forbidden_run_python_ros(*args, **kwargs):
            raise AssertionError("Failure-Mode Audit V1 must not source a ROS workspace")

        class Completed:
            returncode = 0

        def fake_subprocess_run(command, cwd=None, check=None):
            calls["command"] = command
            calls["cwd"] = cwd
            calls["check"] = check
            return Completed()

        module._core.resolve_run = forbidden_resolve_run
        module._core.run_python_ros = forbidden_run_python_ros
        module.subprocess.run = fake_subprocess_run
        try:
            code = module.cmd_audit_failure_mode(
                SimpleNamespace(
                    run_root=Path("/persistent/green_house"),
                    batch_id="repv1_final_20260817_133745",
                )
            )
        finally:
            module._core.resolve_run = original_resolve_run
            module._core.run_python_ros = original_run_python_ros
            module.subprocess.run = original_subprocess_run

        self.assertEqual(0, code)
        self.assertEqual(
            [
                module.sys.executable,
                str(ROOT / "evaluators/audit_failure_modes.py"),
                "--run-root",
                "/persistent/green_house",
                "--batch-id",
                "repv1_final_20260817_133745",
            ],
            calls["command"],
        )
        self.assertEqual(ROOT, calls["cwd"])
        self.assertFalse(calls["check"])

    def test_evaluator_is_read_only_and_has_no_ros_or_bag_dependency(self) -> None:
        evaluator = ROOT / "evaluators/audit_failure_modes.py"
        self.assertTrue(evaluator.is_file())
        text = evaluator.read_text(encoding="utf-8")
        self.assertIn("failure_mode_audit", text)
        self.assertNotIn("rclpy", text)
        self.assertNotIn("rosbag2_py", text)
        self.assertNotIn("open_reader", text)
        self.assertNotIn("deserialize_message", text)
        self.assertNotIn("ros2 bag", text.lower())


if __name__ == "__main__":
    unittest.main()
