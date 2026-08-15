from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.registry import FIXED_BASELINES, Registry, RegistryError, validate_fixed_baselines


class RegistryTest(unittest.TestCase):
    def test_tracked_fixed_baselines_are_valid(self) -> None:
        registry = Registry()
        self.assertTrue(set(FIXED_BASELINES).issubset(set(registry.list_algorithms())))
        validate_fixed_baselines(registry)
        for algorithm_id in FIXED_BASELINES:
            record = registry.load_algorithm(algorithm_id)
            self.assertEqual(algorithm_id, record["algorithm_id"])

    def test_example_dataset_is_valid(self) -> None:
        record = Registry().load_dataset("example_mid360")
        self.assertTrue(record["portable_example"])
        self.assertEqual("/livox/lidar", record["topics"]["lidar"])

    def test_unknown_record_fails_closed(self) -> None:
        with self.assertRaises(RegistryError):
            Registry().load_algorithm("not_a_real_algorithm")

    def test_record_id_must_match_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "algorithms").mkdir(); (root / "datasets").mkdir()
            record = Registry().load_algorithm("fast_livo2")
            record["algorithm_id"] = "wrong_id"
            (root / "algorithms" / "fast_livo2.json").write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "algorithm_id mismatch"):
                Registry(root).load_algorithm("fast_livo2")

    def test_malformed_json_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "algorithms").mkdir(); (root / "datasets").mkdir()
            (root / "algorithms" / "broken.json").write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "invalid JSON"):
                Registry(root).load_algorithm("broken")


if __name__ == "__main__":
    unittest.main()
