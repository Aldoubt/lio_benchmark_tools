from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from benchmark_base.lib.diagnostic_bundle import create_diagnostic_bundle


class CalibrationBundleEvidenceTest(unittest.TestCase):
    @staticmethod
    def _write(root: Path, relative: str, content: str = "x\n") -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _git_repo(root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "unit@example.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Unit Test"], check=True)
        (repo / "tracked.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
        return repo

    def test_generated_calibration_and_effective_configs_are_optional_bundle_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            run.mkdir()
            manifest = {
                "run_id": "factory_config_bundle",
                "dataset": {"dataset_id": "green_house_mid360"},
                "algorithms": {
                    "fast_livo2": {},
                    "fast_lio2": {},
                    "kiss_icp": {},
                },
            }
            self._write(run, "manifest.json", json.dumps(manifest))
            self._write(run, "RUN_STATUS.md", "# run\n")
            self._write(run, "configs/generated/fast_livo2/calibration.json", "{}\n")
            self._write(run, "configs/generated/fast_livo2/adapter_config_metadata.json", "{}\n")
            self._write(run, "configs/generated/fast_livo2/runtime_params.yaml", "extrinsic_T: [-0.011, -0.02329, 0.04412]\n")
            self._write(run, "configs/generated/fast_lio2/calibration.json", "{}\n")
            self._write(run, "configs/generated/fast_lio2/adapter_config_metadata.json", "{}\n")
            self._write(run, "configs/generated/fast_lio2/benchmark.yaml", "extrinsic_T: [-0.011, -0.02329, 0.04412]\n")

            archive = create_diagnostic_bundle(run, repository_root=self._git_repo(root))
            with tarfile.open(archive, "r:gz") as stream:
                names = set(stream.getnames())
                bundle_manifest = json.loads(
                    stream.extractfile("metadata/bundle/bundle_manifest.json").read().decode("utf-8")
                )

            expected = {
                "configs/generated/fast_livo2/calibration.json",
                "configs/generated/fast_livo2/adapter_config_metadata.json",
                "configs/generated/fast_livo2/runtime_params.yaml",
                "configs/generated/fast_lio2/calibration.json",
                "configs/generated/fast_lio2/adapter_config_metadata.json",
                "configs/generated/fast_lio2/benchmark.yaml",
            }
            self.assertTrue(expected.issubset(names))
            self.assertTrue(expected.issubset(set(bundle_manifest["included"])))
            self.assertFalse(any(path.startswith("configs/generated/kiss_icp/") for path in bundle_manifest["missing"]))


if __name__ == "__main__":
    unittest.main()
