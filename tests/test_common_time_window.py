import numpy as np
from evaluation import common_time_window,crop_common

def test_common_window_and_crop_accounting():
    start,end=common_time_window({"a":np.array([0,1,2,3]),"b":np.array([1,2,3,4])})
    assert (start,end)==(1,3)
    out,meta=crop_common(np.array([[0,0],[1,0],[2,0],[3,0],[4,0]],float),start,end)
    assert len(out)==3 and meta["discarded_samples"]==2
