import numpy as np

from trajectory_discontinuity import (
    robust_jump_threshold,
    step_series,
    summarize_discontinuities,
)


def trajectory(times, positions, yaw):
    return {
        "timestamp_s": np.asarray(times, dtype=np.float64),
        "positions": np.asarray(positions, dtype=np.float64),
        "yaw_rad": np.asarray(yaw, dtype=np.float64),
    }


def test_robust_jump_threshold_respects_floor():
    values = np.asarray([0.01, 0.02, 0.01, 0.02], dtype=np.float64)
    assert robust_jump_threshold(values, floor=0.5) == 0.5


def test_step_series_unwraps_yaw_boundary_without_false_jump():
    data = trajectory(
        [100.0, 101.0, 102.0],
        [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.2, 0.0, 0.0]],
        [3.13, -3.13, -3.12],
    )
    series = step_series(data, origin_timestamp_s=100.0)
    assert np.max(series["yaw_step_deg"]) < 2.0
    assert np.allclose(series["relative_time_s"], [1.0, 2.0])


def test_summary_emits_timestamped_position_jump_event():
    data = trajectory(
        [100.0, 101.0, 102.0, 103.0],
        [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.2, 0.0, 0.0], [5.2, 0.0, 0.0]],
        [0.0, 0.0, 0.0, 0.0],
    )
    summary = summarize_discontinuities("candidate", data, origin_timestamp_s=100.0)
    assert summary["position_jump_count"] == 1
    assert summary["yaw_jump_count"] == 0
    event = summary["events"][0]
    assert event["algorithm"] == "candidate"
    assert event["type"] == "position_jump"
    assert event["timestamp_s"] == 103.0
    assert event["relative_time_s"] == 3.0
    assert np.isclose(event["position_step_m"], 5.0)
    assert event["x_m"] == 5.2


def test_summary_reports_large_yaw_jump_without_marking_normal_steps():
    data = trajectory(
        [0.0, 1.0, 2.0, 3.0],
        [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.2, 0.0, 0.0], [0.3, 0.0, 0.0]],
        [0.0, 0.01, 0.02, 1.0],
    )
    summary = summarize_discontinuities("candidate", data, origin_timestamp_s=0.0)
    assert summary["position_jump_count"] == 0
    assert summary["yaw_jump_count"] == 1
    assert summary["events"][0]["type"] == "yaw_jump"
    assert summary["events"][0]["yaw_step_deg"] > 50.0
