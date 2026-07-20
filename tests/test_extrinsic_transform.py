import numpy as np
from lio_benchmark.geometry import Pose,invert_transform,transform_points

def test_full_rotation_and_translation_are_applied():
    pose=Pose(0,np.array([10.,0,0]),np.array([0,0,0,1.]))
    r=[0,-1,0,1,0,0,0,0,1]
    out=transform_points(np.array([[1.,0,0]]),pose,r,[1,2,3])
    assert np.allclose(out,[[11,3,3]])

def test_transform_inverse():
    r=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
    t=np.array([1.,2,3]);ri,ti=invert_transform(r,t)
    assert np.allclose(ri@(r@np.array([4.,5,6])+t)+ti,[4,5,6])
