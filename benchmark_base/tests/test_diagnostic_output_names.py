from __future__ import annotations

import unittest

from reporting.diagnostics import warmup_suffix


class DiagnosticOutputNameTest(unittest.TestCase):
    def test_full_run_keeps_backward_compatible_names(self) -> None:
        self.assertEqual("", warmup_suffix(0.0))

    def test_warmup_view_gets_deterministic_suffix(self) -> None:
        self.assertEqual("_warmup_2s", warmup_suffix(2.0))
        self.assertEqual("_warmup_2p5s", warmup_suffix(2.5))

    def test_invalid_warmup_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            warmup_suffix(-0.1)


if __name__ == "__main__":
    unittest.main()
