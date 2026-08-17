from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from benchmark_base.lib.runtime_performance import run_process_with_metrics


class RuntimePerformanceContractTest(unittest.TestCase):
    def test_success_writes_auditable_metrics_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log_path = root / "run.log"
            output_path = root / "metrics.json"
            returncode = run_process_with_metrics(
                [
                    sys.executable,
                    "-c",
                    "x=sum(range(1000000)); print('runtime-metric-ok', x)",
                ],
                cwd=root,
                env=os.environ.copy(),
                log_path=log_path,
                algorithm_id="synthetic",
                output_path=output_path,
                sample_period_s=0.01,
            )

            self.assertEqual(returncode, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], "lio_benchmark_runtime_performance/v1")
            self.assertEqual(payload["algorithm_id"], "synthetic")
            self.assertEqual(payload["measurement_method"], "LINUX_PROC_PROCESS_SESSION_V1")
            self.assertGreater(payload["wall_time_s"], 0.0)
            self.assertIsNotNone(payload["started_at"])
            self.assertIsNotNone(payload["finished_at"])
            self.assertGreaterEqual(payload["cpu_user_s"], 0.0)
            self.assertGreaterEqual(payload["cpu_system_s"], 0.0)
            self.assertGreaterEqual(payload["cpu_total_s"], 0.0)
            self.assertIsNone(payload["max_rss_kib"] if sys.platform != "linux" else None)
            if sys.platform == "linux":
                self.assertIsNotNone(payload["max_rss_kib"])
                self.assertGreater(payload["max_rss_kib"], 0)
            self.assertEqual(payload["returncode"], 0)
            self.assertEqual(payload["status"], "PASS")
            self.assertIn("runtime-metric-ok", log_path.read_text(encoding="utf-8"))

    def test_nonzero_process_is_recorded_without_masking_returncode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output_path = root / "metrics.json"
            returncode = run_process_with_metrics(
                [sys.executable, "-c", "raise SystemExit(7)"],
                cwd=root,
                env=os.environ.copy(),
                log_path=root / "run.log",
                algorithm_id="synthetic_failure",
                output_path=output_path,
                sample_period_s=0.01,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(returncode, 7)
            self.assertEqual(payload["returncode"], 7)
            self.assertEqual(payload["status"], "FAIL")

    def test_refuses_to_overwrite_existing_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output_path = root / "metrics.json"
            output_path.write_text("existing\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                run_process_with_metrics(
                    [sys.executable, "-c", "print('must-not-run')"],
                    cwd=root,
                    env=os.environ.copy(),
                    log_path=root / "run.log",
                    algorithm_id="synthetic",
                    output_path=output_path,
                    sample_period_s=0.01,
                )
            self.assertEqual(output_path.read_text(encoding="utf-8"), "existing\n")
            self.assertFalse((root / "run.log").exists())


if __name__ == "__main__":
    unittest.main()
