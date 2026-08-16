from __future__ import annotations

import unittest

from benchmark_base.lib.runtime_provenance import build_runtime_provenance_record


class RuntimeSourceQualityTest(unittest.TestCase):
    @staticmethod
    def _algorithm() -> dict:
        return {
            "algorithm_id": "unit_algo",
            "execution_implementation": {
                "repository": "example/runtime",
                "package": "unit_pkg",
                "executable": "unit_exec",
            },
            "trajectory_contract": {
                "pose_semantics": "T_PARENT_TRACKED",
                "tracked_frame_physical": "IMU_BODY",
                "world_gauge": "INITIAL_BODY_ALIGNED",
                "expected_parent_frames": ["odom"],
                "expected_child_frames": ["sensor"],
            },
        }

    @staticmethod
    def _frame() -> dict:
        return {
            "status": "AVAILABLE",
            "parent_frame_ids": ["odom"],
            "child_frame_ids": ["sensor"],
        }

    def _record(self, dirty_marker) -> dict:
        source = {
            "path": "/workspace/src/runtime",
            "remote_origin": "https://github.com/example/runtime.git",
            "commit": "abc123",
            "branch": "main",
        }
        if dirty_marker != "MISSING":
            source["dirty"] = dirty_marker
        identity = {
            "identity_status": "FROZEN",
            "resolution_method": "REGISTRY_DEFAULT_EXECUTION",
            "resolved_executable": "/workspace/install/unit_pkg/lib/unit_pkg/unit_exec",
            "executable_sha256": "deadbeef",
            "runtime_package": "unit_pkg",
            "runtime_package_prefix": "/workspace/install/unit_pkg",
            "source": source,
        }
        return build_runtime_provenance_record(
            algorithm=self._algorithm(),
            frame_audit=self._frame(),
            ros_package_prefix="/workspace/install/unit_pkg",
            source_state=None,
            runtime_identity=identity,
        )

    def test_clean_source_is_explicitly_clean_without_changing_match(self) -> None:
        record = self._record(False)
        self.assertEqual("MATCH", record["status"])
        self.assertEqual("CLEAN_SOURCE", record["source_reproducibility_status"])
        self.assertEqual([], record["source_reproducibility_reasons"])

    def test_dirty_source_is_warning_without_redefining_runtime_match(self) -> None:
        record = self._record(True)
        self.assertEqual("MATCH", record["status"])
        self.assertEqual("DIRTY_SOURCE_WARNING", record["source_reproducibility_status"])
        self.assertTrue(record["source_reproducibility_reasons"])
        self.assertIn("binary hash is frozen", record["source_reproducibility_reasons"][0])

    def test_missing_source_cleanliness_is_unknown_not_silently_clean(self) -> None:
        record = self._record("MISSING")
        self.assertEqual("MATCH", record["status"])
        self.assertEqual("UNKNOWN_SOURCE_CLEANLINESS", record["source_reproducibility_status"])
        self.assertTrue(record["source_reproducibility_reasons"])


if __name__ == "__main__":
    unittest.main()
