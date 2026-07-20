import struct
import pytest
from time_fields import read_scalar, relative_seconds

def test_float64_is_not_reinterpreted_as_uint64():
    raw=struct.pack("<d",123.25)
    assert read_scalar(raw,0,8)==123.25
    assert read_scalar(raw,0,8)!=struct.unpack("<Q",raw)[0]

def test_absolute_nanoseconds_become_relative_seconds():
    assert relative_seconds([1_000_000_000,1_100_000_000],"ns","absolute")==pytest.approx([0.0,0.1])
