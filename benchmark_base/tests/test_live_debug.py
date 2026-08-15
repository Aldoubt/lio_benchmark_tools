from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.live_debug import append_marker, prepare_session, render_algorithm_script
from benchmark_base.lib.registry import Registry


class LiveDebugTest(unittest.TestCase):
    def test_render_algorithm_script_keeps_processes_visible(self) -> None:
        algorithm = Registry().load_algorithm("point_lio")
        script = render_algorithm_script(algorithm)
        self.assertIn("pointcloud2_to_livox_custom.py", script)
        self.assertIn("pointlio_mapping", script)
        self.assertIn("tee", script)

    def test_prepare_and_mark_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry_root = root / "registry"
            (registry_root / "algorithms").mkdir(parents=True)
            (registry_root / "datasets").mkdir()
            source_registry = Registry()
            algorithm = source_registry.load_algorithm("fast_livo2")
            (registry_root / "algorithms" / "fast_livo2.json").write_text(json.dumps(algorithm), encoding="utf-8")
            bag = root / "bag"
            bag.mkdir()
            (bag / "metadata.yaml").write_text("rosbag2_bagfile_information: {}\n", encoding="utf-8")
            dataset = source_registry.load_dataset("example_mid360")
            dataset["dataset_id"] = "fixture"
            dataset["bag_dir"] = str(bag)
            (registry_root / "datasets" / "fixture.json").write_text(json.dumps(dataset), encoding="utf-8")
            workspace = root / "ws"
            workspace.mkdir()
            session = prepare_session(
                registry=Registry(registry_root),
                dataset_id="fixture",
                algorithm_ids=("fast_livo2",),
                workspace=workspace,
                session_root=root / "sessions",
                benchmark_root=root / "benchmark",
                rate=0.5,
                session_id="unit",
            )
            self.assertTrue((session / "01_bag_play.sh").is_file())
            payload = json.loads((session / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(0.5, payload["bag_playback_rate"])
            marker = append_marker(
                session=session,
                algorithm_id="fast_livo2",
                event="map_doubling",
                bag_time_s=12.3,
                note="unit",
            )
            self.assertEqual(12.3, marker["bag_time_s"])
            self.assertIn("map_doubling", (session / "markers" / "events.jsonl").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
