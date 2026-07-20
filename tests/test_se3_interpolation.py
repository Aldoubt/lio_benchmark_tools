import math
import numpy as np
import pytest
from lio_benchmark.geometry import Pose,interpolate_pose,quaternion_matrix

def test_translation_and_rotation_slerp():
    a=Pose(0,np.array([0.,0,0]),np.array([0.,0,0,1]))
    b=Pose(2,np.array([2.,0,0]),np.array([0.,0,1,0]))
    p=interpolate_pose(a,b,1,3)
    assert np.allclose(p.translation,[1,0,0])
    assert np.allclose(quaternion_matrix(p.quaternion_xyzw)@np.array([1,0,0]),[0,1,0],atol=1e-7)
    assert np.isclose(np.linalg.norm(p.quaternion_xyzw),1)

def test_boundary_gap_and_time_order():
    a=Pose(0,np.zeros(3),np.array([0,0,0,1.]));b=Pose(2,np.ones(3),np.array([0,0,0,1.]))
    assert interpolate_pose(a,b,0,2).timestamp_s==0
    with pytest.raises(ValueError):interpolate_pose(a,b,1,1)
    with pytest.raises(ValueError):interpolate_pose(b,a,1,3)
