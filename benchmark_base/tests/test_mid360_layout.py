from __future__ import annotations

import unittest

from benchmark_base.lib.mid360_layout import (
    MID360_POINT_STEP,
    MID360_POINT_STRUCT,
    absolute_ns_float_to_uint64,
    offset_ns_uint32,
)


class Mid360LayoutTest(unittest.TestCase):
    def test_declared_layout_is_26_bytes_and_float64_timestamp(self) -> None:
        self.assertEqual(26, MID360_POINT_STEP)
        packed = MID360_POINT_STRUCT.pack(1.0, 2.0, 3.0, 4.0, 5, 6, 1_700_000_000_123_456_768.0)
        values = MID360_POINT_STRUCT.unpack(packed)
        self.assertAlmostEqual(1.0, values[0])
        self.assertIsInstance(values[6], float)

    def test_float_nanoseconds_convert_to_livox_integer_timebase(self) -> None:
        value = 1_700_000_000_123_456_768.0
        self.assertEqual(int(round(value)), absolute_ns_float_to_uint64(value))

    def test_offset_contract(self) -> None:
        self.assertEqual(50, offset_ns_uint32(1050, 1000))
        with self.assertRaises(ValueError):
            offset_ns_uint32(999, 1000)
        with self.assertRaises(ValueError):
            offset_ns_uint32(1000 + 0x1_0000_0000, 1000)


if __name__ == "__main__":
    unittest.main()
