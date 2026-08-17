from __future__ import annotations

import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.diagnostic_bundle import create_diagnostic_bundle


class DiagnosticBundleTest(unittest.TestCase):
    def _write(self, root: Path, relative: str, content: str = "x\n") -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _make_run(self, root: Path) -> Path:
        run = root / "run"
        run.mkdir()
        manifest = {
            "run_id": "unit_smoke_001",
            "dataset": {"dataset_id": "unit_dataset", "bag_dir": "/data/unit"},
            "algorithms": {
                "algo_a": {"display_name": "Algorithm A"},
                "unexpected_algo_name": {"display_name": "Unexpected Algorithm"},
            },
        }
        self._write(run, "manifest.json", json.dumps(manifest))
        self._write(run, "RUN_STATUS.md", "# run\n")
        self._write(run, "metrics/runtime_provenance.csv", "algorithm_id,status\nalgo_a,MATCH\n")
        self._write(run, "metrics/trajectory_frame_audit.csv", "algorithm_id,status\nalgo_a,AVAILABLE\n")
        self._write(run, "metrics/smoke_diagnostics.csv", "algorithm_id,duration_s\nalgo_a,15\n")
        self._write(run, "metrics/smoke_diagnostics_warmup_2s.csv", "algorithm_id,duration_s\nalgo_a,13\n")
        self._write(run, "metrics/pairwise_disagreement.csv", "algorithm_a,algorithm_b\nalgo_a,unexpected_algo_name\n")
        self._write(run, "metrics/pairwise_disagreement_warmup_2s.csv", "algorithm_a,algorithm_b\nalgo_a,unexpected_algo_name\n")
        self._write(run, "metadata/frame_audit/algo_a.json", json.dumps({"algorithm_id": "algo_a", "status": "AVAILABLE"}))
        self._write(run, "metadata/runtime_provenance/algo_a.json", json.dumps({"algorithm_id": "algo_a", "status": "MATCH"}))
        self._write(
            run,
            "metadata/algorithms/algo_a/runtime_identity.json",
            json.dumps({
                "algorithm_id": "algo_a",
                "identity_status": "FROZEN",
                "resolution_method": "REGISTRY_DEFAULT_EXECUTION",
                "executable_sha256": "abc123",
            }),
        )
        self._write(
            run,
            "metadata/algorithms/algo_a/trajectory_standardization.json",
            json.dumps({
                "schema_version": 1,
                "algorithm_id": "algo_a",
                "source_kind": "RUN_LOCAL_ROS2_BAG",
                "sample_count": 100,
            }),
        )
        self._write(
            run,
            "standardized/map_sampling/metadata.json",
            json.dumps({"selected_scan_count": 30, "window": {"duration_s": 15}}),
        )
        self._write(run, "standardized/map_sampling/selected_scans.csv", "scan_index,timestamp_s\n0,1.0\n")
        self._write(
            run,
            "standardized/map_sampling/common_matched_scans.csv",
            "scan_index,timestamp_s\n0,1.0\n",
        )
        self._write(
            run,
            "standardized/map_sampling/common_matched_metadata.json",
            json.dumps({
                "policy": "STRICT_ALL_ALGORITHM_TRAJECTORY_INTERSECTION",
                "common_matched_scan_count": 1,
            }),
        )
        self._write(
            run,
            "standardized/maps/algo_a/unified/metadata.json",
            json.dumps({"tracked_frame_physical": "IMU_BODY", "world_gauge": "GRAVITY_ALIGNED"}),
        )
        self._write(
            run,
            "standardized/maps/unexpected_algo_name/unified/metadata.json",
            json.dumps({"tracked_frame_physical": "LIDAR", "world_gauge": "INITIAL_LIDAR_ALIGNED"}),
        )

        # These exist specifically to prove the minimal bundle cannot leak large/raw/report artifacts.
        self._write(run, "raw/algo_a/raw.db3", "not-a-real-db\n")
        self._write(run, "standardized/maps/algo_a/unified/map.ply", "ply\n")
        self._write(run, "standardized/maps/algo_a/native/map.pcd", "pcd\n")
        self._write(run, "reports/report.md", "# report\n")
        self._write(run, "reports/report.html", "<html></html>\n")
        self._write(run, "figures/plot.png", "fake png\n")
        return run

    def _make_git_repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "unit@example.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Unit Test"], check=True)
        file_path = repo / "tracked.txt"
        file_path.write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
        file_path.write_text("after\n", encoding="utf-8")
        return repo

    def test_default_bundle_contains_small_diagnostics_and_excludes_large_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._make_run(root)
            repo = self._make_git_repo(root)

            archive = create_diagnostic_bundle(run, repository_root=repo)

            self.assertEqual(run / "reports/bundles/unit_smoke_001_diagnostic_bundle.tar.gz", archive)
            with tarfile.open(archive, "r:gz") as stream:
                names = set(stream.getnames())
                bundle_manifest = json.loads(
                    stream.extractfile("metadata/bundle/bundle_manifest.json").read().decode("utf-8")
                )
                local_patch = stream.extractfile("metadata/bundle/benchmark_local.patch").read().decode("utf-8")

            self.assertIn("manifest.json", names)
            self.assertIn("metrics/runtime_provenance.csv", names)
            self.assertIn("metadata/algorithms/algo_a/runtime_identity.json", names)
            self.assertIn("metadata/algorithms/algo_a/trajectory_standardization.json", names)
            self.assertIn("standardized/maps/algo_a/unified/metadata.json", names)
            self.assertIn("standardized/maps/unexpected_algo_name/unified/metadata.json", names)
            self.assertIn("standardized/map_sampling/common_matched_scans.csv", names)
            self.assertIn("standardized/map_sampling/common_matched_metadata.json", names)
            self.assertIn("metadata/bundle/SUMMARY.txt", names)
            self.assertIn("metadata/bundle/bundle_manifest.json", names)
            self.assertIn("metadata/bundle/benchmark_git_head.txt", names)
            self.assertIn("metadata/bundle/benchmark_git_status.txt", names)
            self.assertIn("metadata/bundle/benchmark_local.patch", names)

            self.assertNotIn("raw/algo_a/raw.db3", names)
            self.assertNotIn("standardized/maps/algo_a/unified/map.ply", names)
            self.assertNotIn("standardized/maps/algo_a/native/map.pcd", names)
            self.assertNotIn("reports/report.md", names)
            self.assertNotIn("reports/report.html", names)
            self.assertNotIn("figures/plot.png", names)
            self.assertNotIn("reports/bundles/unit_smoke_001_diagnostic_bundle.tar.gz", names)

            self.assertEqual("lio_benchmark_diagnostic_bundle/v1", bundle_manifest["schema"])
            self.assertFalse(bundle_manifest["include_reports"])
            self.assertIn("metadata/bundle/SUMMARY.txt", bundle_manifest["included"])
            self.assertIn(
                "metadata/algorithms/unexpected_algo_name/runtime_identity.json",
                bundle_manifest["missing"],
            )
            self.assertIn(
                "metadata/algorithms/unexpected_algo_name/trajectory_standardization.json",
                bundle_manifest["missing"],
            )
            self.assertIn("tracked.txt", local_patch)

    def test_common_map_evidence_is_optional_for_historical_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._make_run(root)
            repo = self._make_git_repo(root)
            (run / "standardized/map_sampling/common_matched_scans.csv").unlink()
            (run / "standardized/map_sampling/common_matched_metadata.json").unlink()

            archive = create_diagnostic_bundle(run, repository_root=repo)
            with tarfile.open(archive, "r:gz") as stream:
                bundle_manifest = json.loads(
                    stream.extractfile("metadata/bundle/bundle_manifest.json").read().decode("utf-8")
                )

            self.assertNotIn(
                "standardized/map_sampling/common_matched_scans.csv",
                bundle_manifest["missing"],
            )
            self.assertNotIn(
                "standardized/map_sampling/common_matched_metadata.json",
                bundle_manifest["missing"],
            )

    def test_include_reports_adds_existing_reports_and_png_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._make_run(root)
            repo = self._make_git_repo(root)

            archive = create_diagnostic_bundle(run, repository_root=repo, include_reports=True)
            with tarfile.open(archive, "r:gz") as stream:
                names = set(stream.getnames())

            self.assertIn("reports/report.md", names)
            self.assertIn("reports/report.html", names)
            self.assertIn("figures/plot.png", names)
            self.assertNotIn("raw/algo_a/raw.db3", names)
            self.assertNotIn("standardized/maps/algo_a/unified/map.ply", names)

    def test_missing_optional_evidence_is_recorded_without_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._make_run(root)
            repo = self._make_git_repo(root)
            (run / "metrics/runtime_provenance.csv").unlink()
            (run / "metadata/runtime_provenance/algo_a.json").unlink()
            (run / "metadata/algorithms/algo_a/runtime_identity.json").unlink()
            (run / "metadata/algorithms/algo_a/trajectory_standardization.json").unlink()

            archive = create_diagnostic_bundle(run, repository_root=repo)
            with tarfile.open(archive, "r:gz") as stream:
                bundle_manifest = json.loads(
                    stream.extractfile("metadata/bundle/bundle_manifest.json").read().decode("utf-8")
                )
                summary = stream.extractfile("metadata/bundle/SUMMARY.txt").read().decode("utf-8")

            self.assertIn("metrics/runtime_provenance.csv", bundle_manifest["missing"])
            self.assertIn("metadata/runtime_provenance/algo_a.json", bundle_manifest["missing"])
            self.assertIn("metadata/algorithms/algo_a/runtime_identity.json", bundle_manifest["missing"])
            self.assertIn(
                "metadata/algorithms/algo_a/trajectory_standardization.json",
                bundle_manifest["missing"],
            )
            self.assertIn("runtime provenance: UNAVAILABLE", summary)

    def test_custom_output_never_recursively_includes_previous_archive_or_staging_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._make_run(root)
            repo = self._make_git_repo(root)
            output = run / "reports/bundles/custom.tar.gz"

            before = {path.relative_to(run).as_posix() for path in run.rglob("*")}
            first = create_diagnostic_bundle(run, repository_root=repo, output=output)
            second = create_diagnostic_bundle(run, repository_root=repo, output=output)
            after = {path.relative_to(run).as_posix() for path in run.rglob("*")}

            self.assertEqual(output, first)
            self.assertEqual(output, second)
            self.assertFalse((run / "metadata/bundle").exists())
            self.assertEqual(after - before, {"reports/bundles", "reports/bundles/custom.tar.gz"})
            with tarfile.open(output, "r:gz") as stream:
                self.assertNotIn("reports/bundles/custom.tar.gz", stream.getnames())

    def test_invalid_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            run.mkdir()
            self._write(run, "manifest.json", "[]\n")
            repo = self._make_git_repo(root)

            with self.assertRaises(ValueError):
                create_diagnostic_bundle(run, repository_root=repo)


if __name__ == "__main__":
    unittest.main()
