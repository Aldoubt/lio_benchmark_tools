from lio_benchmark.registry import ALGORITHMS,comparison_groups

def test_all_required_algorithms_registered_and_groups_separate():
    assert {"kiss_icp","mola_lo","mola_lio","lio_sam_no_loop","lio_sam_loop","fast_livo2","point_lio","dlio","glim_odometry","glim_full_slam"}==set(ALGORITHMS)
    groups=comparison_groups(list(ALGORITHMS))
    assert "kiss_icp" in groups["lidar_only_odometry"]
    assert "mola_lio" in groups["lidar_imu_odometry"]
    assert "lio_sam_loop" in groups["full_slam"]
