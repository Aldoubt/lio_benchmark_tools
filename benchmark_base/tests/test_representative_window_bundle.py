from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmark_base.lib.diagnostic_bundle import collect_bundle_files


class RepresentativeWindowBundleTest(unittest.TestCase):
    def _run(self, root: Path) -> tuple[Path, dict]:
        run = root / "selector"
        run.mkdir()
        manifest = {"run_id": "selector", "algorithms": []}
        (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run, manifest

    def test_selector_evidence_is_optional_and_included_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run, manifest = self._run(Path(tmp))
            paths = (
                "metadata/representative_windows/window_features.csv",
                "metadata/representative_windows/selected_windows.json",
                "metadata/representative_windows/selection_metadata.json",
                "configs/representative_windows/initialization.json",
                "configs/representative_windows/high_angular_motion.json",
                "configs/representative_windows/geometric_degeneracy_candidate.json",
                "configs/representative_windows/steady_translation_candidate.json",
                "reports/REPRESENTATIVE_WINDOW_PLAN.md",
            )
            for relative in paths:
                path = run / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("evidence\n", encoding="utf-8")

            selection = collect_bundle_files(run, manifest, include_reports=False)
            for relative in paths:
                self.assertIn(relative, selection.included)
                self.assertNotIn(relative, selection.missing)

    def test_historical_run_does_not_report_selector_evidence_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run, manifest = self._run(Path(tmp))
            selection = collect_bundle_files(run, manifest, include_reports=False)
            self.assertFalse(
                any("representative_windows" in value for value in selection.missing),
                selection.missing,
            )
            self.assertNotIn("reports/REPRESENTATIVE_WINDOW_PLAN.md", selection.missing)

    def test_large_artifact_exclusions_remain_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run, manifest = self._run(Path(tmp))
            for relative in (
                "raw/source.db3",
                "configs/representative_windows/raw.mcap",
                "metadata/representative_windows/map.ply",
                "metadata/representative_windows/cloud.pcd",
            ):
                path = run / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"large")
            selection = collect_bundle_files(run, manifest, include_reports=False)
            self.assertFalse(any(value.endswith((".db3", ".mcap", ".ply", ".pcd")) for value in selection.included))


if __name__ == "__main__":
    unittest.main()
