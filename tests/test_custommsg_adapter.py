from dataclasses import dataclass
from custommsg_to_pointcloud2 import POINT_STRUCT,Validation,convert_points
import pytest

@dataclass
class P:
    x:float;y:float;z:float;reflectivity:int;tag:int;line:int;offset_time:int

def test_converter_sorts_real_offsets_and_preserves_lines():
    stats=Validation(); raw=convert_points([P(1,2,3,4,0,3,20),P(5,6,7,8,0,1,10)],True,stats)
    first=POINT_STRUCT.unpack_from(raw,0);second=POINT_STRUCT.unpack_from(raw,POINT_STRUCT.size)
    assert first[4]==1 and first[5]==pytest.approx(1e-8)
    assert second[4]==3 and second[5]==pytest.approx(2e-8)
    assert stats.input_time_backtracks==1 and stats.output_time_backtracks==0
