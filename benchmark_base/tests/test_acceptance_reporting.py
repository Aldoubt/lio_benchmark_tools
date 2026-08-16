from __future__ import annotations

import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.diagnostic_bundle import collect_bundle_files, create_diagnostic_bundle


class AcceptanceReportingTest(unittest.TestCase):
    def _write(self, root: Path, relative: str, content: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "unit@example.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Unit"], check=True)
        (repo / "tracked.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
        return repo

    def _run(self, root: Path) -> tuple[Path, dict]:
        run = root / "run"
        run.mkdir()
        manifest = {
            "run_id": "acceptance_unit",
            "dataset": {"dataset_id": "unit"},
            "algorithms": {"algo_a": {}, "algo_b": {}},
        }
        self._write(run, "manifest.json", json.dumps(manifest))
        self._write(
            run,
            "RUN_STATUS.md",
            "# Run acceptance_unit\n\n- status: initialized\n- frontend runs: pending\n",
        )
        for algorithm in ("algo_a", "algo_b"):
            self._write(
                run,
                f"metadata/run_{algorithm}.json",
                json.dumps({"algorithm_id": algorithm, "status": "PASS", "returncode": 0}),
            )
            self._write(
                run,
                f"metadata/algorithms/{algorithm}/runtime_identity.json",
                json.dumps({"algorithm_id": algorithm, "identity_status": "FROZEN"}),
            )
            self._write(
                run,
                f"metadata/algorithms/{algorithm}/trajectory_standardization.json",
                json.dumps({"algorithm_id": algorithm, "sample_count": 10}),
            )
            self._write(
                run,
                f"metadata/frame_audit/{algorithm}.json",
                json.dumps({"algorithm_id": algorithm, "status": "AVAILABLE"}),
            )
            self._write(
                run,
                f"metadata/runtime_provenance/{algorithm}.json",
                json.dumps({"algorithm_id": algorithm, "status": "MATCH"}),
            )
            self._write(
                run,
                f"standardized/maps/{algorithm}/unified/metadata.json",
                json.dumps({"matched_scan_count": 5}),
            )
        self._write(
            run,
            "metrics/runtime_provenance.csv",
            "algorithm_id,status,frame_contract_status\n"
            "algo_a,MATCH,MATCH\n"
            "algo_b,MATCH,MATCH\n",
        )
        self._write(
            run,
            "metrics/trajectory_frame_audit.csv",
            "algorithm_id,status\nalgo_a,AVAILABLE\nalgo_b,AVAILABLE\n",
        )
        self._write(run, "standardized/map_sampling/metadata.json", "{}\n")
        self._write(run, "standardized/map_sampling/selected_scans.csv", "scan_index,timestamp_s\n")
        self._write(run, "metrics/relative_se3/metadata.json", "{}\n")
        return run, manifest

    def test_legacy_diagnostics_are_optional_not_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run, manifest = self._run(Path(tmp))
            selection = collect_bundle_files(run, manifest, include_reports=False)
            self.assertNotIn("metrics/smoke_diagnostics.csv", selection.missing)
            self.assertNotIn("metrics/pairwise_disagreement.csv", selection.missing)

    def test_summary_separates_frame_evidence_from_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run, _ = self._run(root)
            archive = create_diagnostic_bundle(run, repository_root=self._repo(root))
            with tarfile.open(archive, "r:gz") as stream:
                summary = stream.extractfile("metadata/bundle/SUMMARY.txt").read().decode("utf-8")
            self.assertIn("frame evidence: AVAILABLE", summary)
            self.assertIn("frame contract: MATCH", summary)
            self.assertNotIn("frame audit: AVAILABLE", summary)

    def test_bundle_refreshes_stale_run_status_from_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run, _ = self._run(root)
            create_diagnostic_bundle(run, repository_root=self._repo(root))
            text = (run / "RUN_STATUS.md").read_text(encoding="utf-8")
            self.assertIn("- status: complete", text)
            self.assertIn("- frontends: 2/2", text)
            self.assertIn("- trajectories: 2/2", text)
            self.assertIn("- frame audit: AVAILABLE", text)
            self.assertIn("- runtime provenance: AVAILABLE", text)
            self.assertIn("- relative se3: AVAILABLE", text)
            self.assertNotIn("pending", text)


if __name__ == "__main__":
    unittest.main()
