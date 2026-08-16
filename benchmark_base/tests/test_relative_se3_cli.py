from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.diagnostic_bundle import collect_bundle_files


class RelativeSE3CliContractTest(unittest.TestCase):
    def test_compare_relative_se3_cli_exposes_only_run_and_algorithm_selection(self) -> None:
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                sys.executable,
                str(root / "benchmark_base/bin/lio-benchmark"),
                "compare",
                "relative-se3",
                "--help",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--run", result.stdout)
        self.assertIn("--algorithms", result.stdout)
        for forbidden in (
            "--alignment",
            "--display-alignment",
            "--sample-period",
            "--threshold",
            "--sustain",
            "--extrinsic",
            "--reference-algorithm",
            "--warmup",
        ):
            self.assertNotIn(forbidden, result.stdout)

    def test_bundle_includes_relative_se3_artifacts_only_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            output = run / "metrics" / "relative_se3"
            output.mkdir(parents=True)
            expected = {
                "metrics/relative_se3/metadata.json",
                "metrics/relative_se3/normalized_motion.csv",
                "metrics/relative_se3/pairwise_samples.csv",
                "metrics/relative_se3/pairwise_summary.csv",
                "metrics/relative_se3/onset_thresholds.csv",
            }
            for relative in expected:
                path = run / relative
                path.write_text("evidence\n", encoding="utf-8")
            selection = collect_bundle_files(run, {"algorithms": {}}, include_reports=False)
            self.assertTrue(expected.issubset(set(selection.included)))

        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            selection = collect_bundle_files(run, {"algorithms": {}}, include_reports=False)
            self.assertTrue(expected.isdisjoint(set(selection.missing)))


if __name__ == "__main__":
    unittest.main()
