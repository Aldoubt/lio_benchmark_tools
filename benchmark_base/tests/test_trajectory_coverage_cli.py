from __future__ import annotations

import importlib.machinery
import importlib.util
from types import SimpleNamespace
import unittest
from pathlib import Path


class TrajectoryCoverageCliTest(unittest.TestCase):
    @staticmethod
    def _load_cli():
        root = Path(__file__).resolve().parents[2]
        path = root / "benchmark_base/bin/lio-benchmark"
        loader = importlib.machinery.SourceFileLoader("lio_benchmark_cli_coverage", str(path))
        spec = importlib.util.spec_from_loader("lio_benchmark_cli_coverage", loader)
        if spec is None:
            raise RuntimeError("unable to load lio-benchmark CLI")
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_trajectory_coverage_audit_is_exposed_through_main_cli(self) -> None:
        module = self._load_cli()
        args = module.build_parser().parse_args(
            [
                "audit",
                "trajectory-coverage",
                "--run",
                "/persistent/run",
                "--algorithms",
                "fast_livo2",
                "fast_lio2",
                "kiss_icp",
            ]
        )
        self.assertEqual("audit", args.command)
        self.assertEqual("trajectory-coverage", args.audit_command)
        self.assertEqual(["fast_livo2", "fast_lio2", "kiss_icp"], args.algorithms)
        self.assertEqual("cmd_audit_trajectory_coverage", args.func.__name__)

    def test_coverage_handler_uses_ros_workspace_runner(self) -> None:
        module = self._load_cli()
        run = Path("/persistent/run")
        manifest = {"workspace": "/persistent/workspace", "algorithms": {"kiss_icp": {}}}
        calls: dict[str, object] = {}

        original_resolve_run = module._core.resolve_run
        original_run_python_ros = module._core.run_python_ros
        original_subprocess_run = module.subprocess.run

        def fake_resolve_run(path: Path):
            calls["resolved"] = path
            return run, manifest

        def fake_run_python_ros(
            resolved_run: Path,
            resolved_manifest: dict,
            script: str,
            arguments: list[str],
        ) -> None:
            calls["ros"] = (resolved_run, resolved_manifest, script, arguments)

        def forbidden_subprocess_run(*args, **kwargs):
            raise AssertionError("trajectory coverage must use the shared ROS workspace runner")

        module._core.resolve_run = fake_resolve_run
        module._core.run_python_ros = fake_run_python_ros
        module.subprocess.run = forbidden_subprocess_run
        try:
            code = module.cmd_audit_trajectory_coverage(
                SimpleNamespace(run=run, algorithms=["kiss_icp"])
            )
        finally:
            module._core.resolve_run = original_resolve_run
            module._core.run_python_ros = original_run_python_ros
            module.subprocess.run = original_subprocess_run

        self.assertEqual(0, code)
        self.assertEqual(run, calls["resolved"])
        self.assertEqual(
            (
                run,
                manifest,
                "evaluators/audit_trajectory_coverage.py",
                ["--run", str(run), "--algorithms", "kiss_icp"],
            ),
            calls["ros"],
        )

    def test_coverage_evaluator_uses_frozen_replay_without_cli_overrides(self) -> None:
        root = Path(__file__).resolve().parents[2]
        text = (root / "evaluators/audit_trajectory_coverage.py").read_text(encoding="utf-8")
        self.assertIn("start_offset_override=None", text)
        self.assertIn("duration_override=None", text)

    def test_kiss_runner_records_converter_boundary_for_diagnostics(self) -> None:
        root = Path(__file__).resolve().parents[2]
        text = (root / "evaluators/run_kiss_icp_test.sh").read_text(encoding="utf-8")
        record_start = text.index('ros2 bag record -o "$OUTPUT_DIR/kiss_icp_outputs"')
        record_end = text.index('>"$OUTPUT_DIR/record.log"', record_start)
        record_command = text[record_start:record_end]
        self.assertIn("/lio_benchmark/kiss_icp_points", record_command)
        self.assertIn("/kiss/odometry", record_command)

    def test_coverage_outputs_are_run_local_and_bundle_optional(self) -> None:
        root = Path(__file__).resolve().parents[2]
        evaluator = root / "evaluators/audit_trajectory_coverage.py"
        self.assertTrue(evaluator.is_file())
        text = evaluator.read_text(encoding="utf-8")
        self.assertIn('run / "metrics" / "trajectory_coverage.csv"', text)
        self.assertIn('run / "metadata" / "trajectory_coverage"', text)

        bundle = (root / "benchmark_base/lib/diagnostic_bundle.py").read_text(encoding="utf-8")
        self.assertIn("metrics/trajectory_coverage.csv", bundle)
        self.assertIn("metadata/trajectory_coverage/*.json", bundle)


if __name__ == "__main__":
    unittest.main()
