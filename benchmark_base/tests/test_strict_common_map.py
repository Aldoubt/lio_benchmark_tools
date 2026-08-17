from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.common_map_manifest import validate_common_map_manifest


class StrictCommonMapContractTest(unittest.TestCase):
    @staticmethod
    def _standardize_map_text() -> str:
        root = Path(__file__).resolve().parents[2]
        return (root / "evaluators" / "standardize_map.py").read_text(encoding="utf-8")

    def test_missing_common_manifest_reports_explicit_precondition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            run.mkdir()
            with self.assertRaisesRegex(ValueError, "standardize common-map-manifest"):
                validate_common_map_manifest(run)

    def test_standardize_map_consumes_validated_common_manifest_not_selected_manifest_builder(self) -> None:
        text = self._standardize_map_text()
        self.assertIn("validate_common_map_manifest", text)
        self.assertIn("common_matched_scans.csv", text)
        self.assertNotIn("from evaluators.build_scan_manifest import build_manifest", text)
        self.assertNotIn("sampling_path = build_manifest(run)", text)

    def test_common_intersection_revalidation_is_hard_failure_not_unmatched_skip(self) -> None:
        text = self._standardize_map_text()
        self.assertIn("COMMON INTERSECTION CONTRACT VIOLATION", text)
        self.assertNotIn("unmatched += 1", text)

    def test_strict_unified_map_metadata_records_policy_sha_and_zero_unmatched(self) -> None:
        text = self._standardize_map_text()
        self.assertIn('metadata["scan_set_policy"] = "STRICT_COMMON_INTERSECTION"', text)
        self.assertIn('metadata["common_manifest"]', text)
        self.assertIn('metadata["common_manifest_sha256"]', text)
        self.assertIn('"unmatched_scan_count": 0', text)
        self.assertIn("matched != selected", text)


if __name__ == "__main__":
    unittest.main()
