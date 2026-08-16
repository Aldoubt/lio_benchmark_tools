from __future__ import annotations

import unittest
from pathlib import Path

from benchmark_base.lib.run_outcome import classify_runner_status


class RunOutcomeTest(unittest.TestCase):
    def test_success_is_pass(self) -> None:
        self.assertEqual("PASS", classify_runner_status(0))

    def test_runtime_environment_exit_is_blocked_environment(self) -> None:
        self.assertEqual("BLOCKED_ENVIRONMENT", classify_runner_status(65))

    def test_other_nonzero_exit_is_algorithm_failure(self) -> None:
        for code in (1, 2, 66, 68, 70, 127):
            with self.subTest(code=code):
                self.assertEqual("FAIL_ALGORITHM", classify_runner_status(code))

    def test_main_cli_uses_shared_runner_status_classifier(self) -> None:
        root = Path(__file__).resolve().parents[2]
        paths = (
            root / "benchmark_base/bin/lio-benchmark",
            root / "benchmark_base/bin/lio-benchmark-core",
        )
        text = "\n".join(path.read_text(encoding="utf-8") for path in paths if path.is_file())
        self.assertIn(
            "from benchmark_base.lib.run_outcome import classify_runner_status",
            text,
        )
        self.assertIn(
            '"status": classify_runner_status(result.returncode)',
            text,
        )


if __name__ == "__main__":
    unittest.main()
