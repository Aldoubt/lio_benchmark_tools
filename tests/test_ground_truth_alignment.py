import numpy as np
from evaluation import align_positions,ate_metrics

def test_se3_alignment_recovers_rigid_transform():
    est=np.array([[0,0,0],[1,0,0],[0,1,0]],float)
    r=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
    truth=(r@est.T).T+np.array([3,4,5])
    aligned,meta=align_positions(est,truth,"SE3")
    assert np.allclose(aligned,truth)
    assert ate_metrics(aligned,truth)["ate_rmse_m"]<1e-12
    assert meta["scale"]==1
