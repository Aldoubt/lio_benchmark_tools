from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

from benchmark_base.lib.trajectory_timestamp_audit import (
    TimestampAuditSample,
    summarize_timestamp_samples,
)


class TrajectoryTimestampAuditMathTest(unittest.TestCase):
    def sample(
        self,
        index: int,
        bag: float,
        header: float | None,
        *,
        source: str | None = None,
    ) -> TimestampAuditSample:
        if source is None:
            source = "HEADER_STAMP" if header is not None else "ROSBAG_RECORD_TIME"
        effective = header if header is not None else bag
        return TimestampAuditSample(
            index=index,
            bag_record_timestamp_s=bag,
            header_timestamp_s=header,
            effective_timestamp_s=effective,
            effective_source=source,
            x_m=float(index),
            y_m=0.0,
            z_m=0.0,
            qx=0.0,
            qy=0.0,
            qz=0.0,
            qw=1.0,
        )

    def test_header_duplicate_is_classified_without_modifying_samples(self) -> None:
        samples = (
            self.sample(0, 10.0, 100.0),
            self.sample(1, 10.1, 100.0),
            self.sample(2, 10.2, 100.1),
        )
        before = samples
        summary = summarize_timestamp_samples(samples)
        self.assertEqual(before, samples)
        self.assertEqual("HEADER_DUPLICATES", summary["classification"])
        self.assertEqual(1, summary["effective_duplicate_count"])
        self.assertEqual(0, summary["effective_regression_count"])
        self.assertEqual(1, summary["header_duplicate_count"])
        self.assertTrue(summary["bag_record_strictly_increasing"])
        self.assertFalse(summary["effective_strictly_increasing"])
        self.assertEqual(1, summary["first_offending_index"])

    def test_header_regression_is_distinct_from_duplicate(self) -> None:
        summary = summarize_timestamp_samples(
            (
                self.sample(0, 10.0, 100.0),
                self.sample(1, 10.1, 99.95),
                self.sample(2, 10.2, 100.1),
            )
        )
        self.assertEqual("HEADER_REGRESSION", summary["classification"])
        self.assertEqual(1, summary["effective_regression_count"])
        self.assertEqual(1, summary["header_regression_count"])
        self.assertAlmostEqual(0.05, summary["max_effective_backward_s"], places=12)

    def test_zero_header_fallback_can_remain_monotonic(self) -> None:
        summary = summarize_timestamp_samples(
            (
                self.sample(0, 10.0, None),
                self.sample(1, 10.1, None),
                self.sample(2, 10.2, None),
            )
        )
        self.assertEqual("PASS", summary["classification"])
        self.assertEqual(3, summary["bag_record_fallback_count"])
        self.assertTrue(summary["effective_strictly_increasing"])

    def test_mixed_timestamp_policy_regression_is_explicit(self) -> None:
        summary = summarize_timestamp_samples(
            (
                self.sample(0, 10.0, 100.0),
                self.sample(1, 10.1, None),
                self.sample(2, 10.2, 100.2),
            )
        )
        self.assertEqual("MIXED_POLICY_REGRESSION", summary["classification"])
        self.assertEqual(1, summary["effective_regression_count"])
        self.assertEqual(1, summary["bag_record_fallback_count"])


class TrajectoryTimestampAuditCliTest(unittest.TestCase):
    @staticmethod
    def load_cli():
        root = Path(__file__).resolve().parents[2]
        path = root / "benchmark_base/bin/lio-benchmark"
        loader = importlib.machinery.SourceFileLoader("lio_benchmark_cli_timestamp_audit", str(path))
        spec = importlib.util.spec_from_loader("lio_benchmark_cli_timestamp_audit", loader)
        if spec is None:
            raise RuntimeError("unable to load lio-benchmark CLI")
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_timestamp_audit_is_exposed_through_main_cli(self) -> None:
        module = self.load_cli()
        args = module.build_parser().parse_args(
            [
                "audit",
                "trajectory-timestamps",
                "--run",
                "/persistent/run",
                "--algorithms",
                "fast_livo2",
            ]
        )
        self.assertEqual("audit", args.command)
        self.assertEqual("trajectory-timestamps", args.audit_command)
        self.assertEqual(["fast_livo2"], args.algorithms)
        self.assertEqual("cmd_audit_trajectory_timestamps", args.func.__name__)

    def test_handler_uses_shared_ros_workspace_runner(self) -> None:
        module = self.load_cli()
        run = Path("/persistent/run")
        manifest = {"workspace": "/persistent/workspace", "algorithms": {"fast_livo2": {}}}
        calls: dict[str, object] = {}
        original_resolve_run = module._core.resolve_run
        original_run_python_ros = module._core.run_python_ros

        def fake_resolve_run(path: Path):
            calls["resolved"] = path
            return run, manifest

        def fake_run_python_ros(resolved_run, resolved_manifest, script, arguments):
            calls["ros"] = (resolved_run, resolved_manifest, script, arguments)

        module._core.resolve_run = fake_resolve_run
        module._core.run_python_ros = fake_run_python_ros
        try:
            code = module.cmd_audit_trajectory_timestamps(
                SimpleNamespace(run=run, algorithms=["fast_livo2"])
            )
        finally:
            module._core.resolve_run = original_resolve_run
            module._core.run_python_ros = original_run_python_ros

        self.assertEqual(0, code)
        self.assertEqual(
            (
                run,
                manifest,
                "evaluators/audit_trajectory_timestamps.py",
                ["--run", str(run), "--algorithms", "fast_livo2"],
            ),
            calls["ros"],
        )

    def test_evaluator_records_header_bag_and_effective_timestamp_evidence(self) -> None:
        root = Path(__file__).resolve().parents[2]
        evaluator = root / "evaluators/audit_trajectory_timestamps.py"
        self.assertTrue(evaluator.is_file())
        text = evaluator.read_text(encoding="utf-8")
        self.assertIn("timestamp_components", text)
        self.assertIn("bag_record_timestamp_s", text)
        self.assertIn("header_timestamp_s", text)
        self.assertIn("effective_timestamp_s", text)
        self.assertIn("translation_step_m", text)
        self.assertIn("rotation_step_deg", text)
        self.assertNotIn("sort(", text)
        self.assertNotIn("drop_duplicates", text)

    def test_shared_reader_exposes_timestamp_components_without_changing_policy(self) -> None:
        root = Path(__file__).resolve().parents[2]
        text = (root / "benchmark_base/lib/rosbag_trajectory.py").read_text(encoding="utf-8")
        self.assertIn("def timestamp_components(", text)
        self.assertIn("HEADER_STAMP", text)
        self.assertIn("ROSBAG_RECORD_TIME", text)
        self.assertIn("return timestamp_components(message, recorded_ns)[2]", text)

    def test_bundle_treats_timestamp_audit_as_optional_evidence(self) -> None:
        root = Path(__file__).resolve().parents[2]
        text = (root / "benchmark_base/lib/diagnostic_bundle.py").read_text(encoding="utf-8")
        self.assertIn("metrics/trajectory_timestamp_audit/*.csv", text)
        self.assertIn("metadata/trajectory_timestamp_audit/*.json", text)


if __name__ == "__main__":
    unittest.main()
