from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reporting.diagnostics import warmup_suffix, write_run_diagnostics


class DiagnosticOutputNameTest(unittest.TestCase):
    def test_full_run_keeps_backward_compatible_names(self) -> None:
        self.assertEqual("", warmup_suffix(0.0))

    def test_warmup_view_gets_deterministic_suffix(self) -> None:
        self.assertEqual("_warmup_2s", warmup_suffix(2.0))
        self.assertEqual("_warmup_2p5s", warmup_suffix(2.5))

    def test_invalid_warmup_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            warmup_suffix(-0.1)

    def test_full_and_warmup_csv_outputs_coexist(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            full = write_run_diagnostics(run, [], [], warmup_s=0.0)
            warm = write_run_diagnostics(run, [], [], warmup_s=2.0)
            self.assertEqual("smoke_diagnostics.csv", full[0].name)
            self.assertEqual("pairwise_disagreement.csv", full[1].name)
            self.assertEqual("smoke_diagnostics_warmup_2s.csv", warm[0].name)
            self.assertEqual("pairwise_disagreement_warmup_2s.csv", warm[1].name)
            self.assertTrue(all(path.is_file() for path in (*full, *warm)))


if __name__ == "__main__":
    unittest.main()
