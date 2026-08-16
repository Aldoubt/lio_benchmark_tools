from __future__ import annotations

import importlib.machinery
import importlib.util
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
