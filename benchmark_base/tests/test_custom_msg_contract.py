import unittest
from types import SimpleNamespace

from benchmark_base.lib.cloud_contract import cloud_rows, scan_timestamp


class CustomMsgContractTest(unittest.TestCase):
    def test_livox_custom_points_are_downsampled_and_filtered(self):
        msg = SimpleNamespace(
            points=[
                SimpleNamespace(x=1.0, y=0.0, z=0.0, reflectivity=10),
                SimpleNamespace(x=2.0, y=0.0, z=0.0, reflectivity=20),
                SimpleNamespace(x=0.1, y=0.0, z=0.0, reflectivity=30),
            ],
            point_num=3,
        )
        result = cloud_rows(msg, point_step=1, near_range_m=0.5)
        self.assertEqual(result.tolist(), [[1.0, 0.0, 0.0, 10.0], [2.0, 0.0, 0.0, 20.0]])

    def test_livox_custom_timebase_and_offset_are_absolute_seconds(self):
        msg = SimpleNamespace(
            header=SimpleNamespace(stamp=SimpleNamespace(sec=0, nanosec=0)),
            timebase=1_700_000_000_000_000_000,
            points=[SimpleNamespace(offset_time=25_000)],
        )
        timestamp, source = scan_timestamp(msg, 0, "offset_time", "ns_relative_to_timebase")
        self.assertAlmostEqual(timestamp, 1_700_000_000.000025)
        self.assertEqual(source, "CUSTOM_POINT:offset_time:ns_relative_to_timebase")


if __name__ == "__main__":
    unittest.main()
