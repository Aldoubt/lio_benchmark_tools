from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from visualization.presets import CameraPreset, RoiPreset, load_camera, load_roi, orthographic_like_camera, save_camera, save_roi


class VisualizationPresetTest(unittest.TestCase):
    def test_roi_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "roi.json"
            expected = RoiPreset("rows", (0, 1, 2), (3, 4, 5))
            save_roi(path, expected)
            self.assertEqual(expected, load_roi(path))

    def test_camera_vector_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "camera.json"
            expected = CameraPreset("view", 50.0, lookat=(0, 0, 0), eye=(1, -2, 3), up=(0, 0, 1))
            save_camera(path, expected)
            self.assertEqual(expected, load_camera(path))

    def test_camera_matrix_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "camera.json"
            matrix = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, -2), (0, 0, 0, 1))
            expected = CameraPreset("captured", 60.0, view_matrix=matrix, viewport_width_px=800, viewport_height_px=600)
            save_camera(path, expected)
            self.assertEqual(expected, load_camera(path))

    def test_default_views_are_deterministic(self) -> None:
        first = orthographic_like_camera("XY", (0, 0, 0), (10, 20, 4), "xy")
        second = orthographic_like_camera("XY", (0, 0, 0), (10, 20, 4), "xy")
        self.assertEqual(first, second)
        self.assertEqual((5.0, 10.0, 2.0), first.lookat)

    def test_invalid_roi_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RoiPreset("bad", (0, 0, 0), (0, 1, 1))


if __name__ == "__main__":
    unittest.main()
