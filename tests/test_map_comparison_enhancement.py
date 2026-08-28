import numpy as np

from enhance_map_comparison import choose_map_sets, shared_projection_limits


def test_primary_map_set_is_health_gated_but_all_retains_failures():
    algorithms = ["fast_livo2", "point_lio", "dlio"]
    health = {
        "fast_livo2": {"status": "SUCCESS", "health_flags": []},
        "point_lio": {"status": "SUCCESS", "health_flags": []},
        "dlio": {"status": "RUNTIME_CRASH", "health_flags": ["trajectory_short"]},
    }
    primary, all_algorithms = choose_map_sets(algorithms, health)
    assert primary == ["fast_livo2", "point_lio"]
    assert all_algorithms == algorithms


def test_projection_limits_are_shared_across_clouds():
    clouds = {
        "a": np.array([[0.0, 0.0, 0.0, 1.0], [1.0, 2.0, 3.0, 2.0]]),
        "b": np.array([[-2.0, 1.0, -1.0, 1.0], [4.0, 5.0, 6.0, 2.0]]),
    }
    limits = shared_projection_limits(clouds, ["a", "b"])
    assert limits["x"] == (-2.0, 4.0)
    assert limits["y"] == (0.0, 5.0)
    assert limits["z"] == (-1.0, 6.0)
