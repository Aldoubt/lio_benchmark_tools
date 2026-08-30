from web_rerun_recorder import log_recording_web_safe, web_profile_layers


def test_web_recording_profiles_form_a_cumulative_diagnostic_ladder():
    assert web_profile_layers("empty") == frozenset()
    assert web_profile_layers("trajectory") == frozenset({"trajectory"})
    assert web_profile_layers("scalar") == frozenset({"trajectory", "scalar"})
    assert web_profile_layers("pose") == frozenset({"trajectory", "scalar", "pose"})
    assert web_profile_layers("full") == frozenset(
        {"trajectory", "scalar", "pose", "anomaly", "heavy"}
    )


def test_web_recording_profile_rejects_unknown_value():
    try:
        web_profile_layers("unknown")
    except ValueError as exc:
        assert "unknown web recording profile" in str(exc)
    else:
        raise AssertionError("unknown web recording profile must be rejected")


class ForbiddenRerun:
    def __getattr__(self, name):
        raise AssertionError(f"empty profile must not access rerun API: {name}")


def test_empty_web_recording_profile_logs_zero_benchmark_data(tmp_path):
    result = log_recording_web_safe(
        ForbiddenRerun(),
        tmp_path,
        ["fast_livo2"],
        baseline="fast_livo2",
        with_maps=False,
        map_point_step=4,
        pointcloud_mode="none",
        pointcloud_period_s=1.0,
        point_lods={"dense": 10, "medium": 20, "sparse": 80},
        world_pointcloud_mode="none",
        world_algorithm="fast_livo2",
        language="en",
        web_profile="empty",
    )
    assert result["web_profile"] == "empty"
    assert result["columnar_rows"] == 0
    assert result["columnar_chunks"] == 0
    assert result["pointcloud_frames_logged"] == 0
    assert result["world_pointcloud_frames_logged"] == 0
