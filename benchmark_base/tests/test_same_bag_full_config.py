from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "benchmark_base" / "config"


class SameBagFullConfigContractTest(unittest.TestCase):
    def test_full_bag_config_preserves_accepted_runtime_contract(self) -> None:
        smoke = json.loads(
            (CONFIG_DIR / "green_house_three_runtime_smoke.json").read_text(encoding="utf-8")
        )
        full = json.loads(
            (CONFIG_DIR / "green_house_three_full_bag_v1.json").read_text(encoding="utf-8")
        )

        self.assertEqual(full["name"], "green_house_three_full_bag_v1")
        self.assertEqual(full["dataset"], "green_house_mid360")
        self.assertEqual(full["algorithms"], ["fast_livo2", "fast_lio2", "kiss_icp"])
        self.assertEqual(full["workspace"], smoke["workspace"])
        self.assertEqual(full["output_root"], smoke["output_root"])
        self.assertEqual(full["execution_overrides"], smoke["execution_overrides"])
        self.assertEqual(full["runtime_overlays"], smoke["runtime_overlays"])
        self.assertEqual(full["standardization"], smoke["standardization"])
        self.assertEqual(
            full["replay"],
            {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 622.99},
        )


if __name__ == "__main__":
    unittest.main()
