import numpy as np

from diagnostic_timeline import (
    aligned_resource_rows,
    cluster_anomaly_windows,
    nearest_resource_sample,
    resample_fixed_rate,
)


def trajectory(times, positions, yaw):
    return {
        "timestamp_s": np.asarray(times, dtype=np.float64),
        "positions": np.asarray(positions, dtype=np.float64),
        "yaw_rad": np.asarray(yaw, dtype=np.float64),
    }


def test_resample_fixed_rate_normalizes_algorithm_output_frequency():
    data = trajectory(
        [100.0, 100.05, 100.20],
        [[0.0, 0.0, 0.0], [0.05, 0.0, 0.0], [0.20, 0.0, 0.0]],
        [0.0, 0.0, 0.0],
    )
    rows = resample_fixed_rate(data, origin_timestamp_s=100.0, hz=10.0)
    assert [round(row["timestamp_s"], 3) for row in rows] == [100.0, 100.1, 100.2]
    assert [round(row["bag_time_s"], 3) for row in rows] == [0.0, 0.1, 0.2]
    assert np.isclose(rows[1]["delta_position_m"], 0.1)
    assert np.isclose(rows[2]["delta_position_m"], 0.1)
    assert np.isclose(rows[1]["speed_mps"], 1.0)
    assert np.isclose(rows[2]["speed_mps"], 1.0)


def test_cluster_anomaly_windows_merges_dense_events_but_keeps_later_event_separate():
    events = [
        {
            "algorithm": "glim_full_slam",
            "type": "position_jump",
            "bag_time_s": 353.10,
            "timestamp_s": 1000.0,
            "position_step_m": 0.70,
            "yaw_step_deg": 1.0,
            "threshold": 0.50,
        },
        {
            "algorithm": "glim_full_slam",
            "type": "position_jump",
            "bag_time_s": 353.90,
            "timestamp_s": 1000.8,
            "position_step_m": 0.85,
            "yaw_step_deg": 0.9,
            "threshold": 0.50,
        },
        {
            "algorithm": "glim_full_slam",
            "type": "position_jump",
            "bag_time_s": 356.50,
            "timestamp_s": 1003.4,
            "position_step_m": 0.60,
            "yaw_step_deg": 0.2,
            "threshold": 0.50,
        },
    ]
    windows = cluster_anomaly_windows(events, max_gap_s=1.0, context_s=0.5)
    assert len(windows) == 2
    assert windows[0]["start_bag_time_s"] == 353.10
    assert windows[0]["end_bag_time_s"] == 353.90
    assert windows[0]["event_count"] == 2
    assert windows[0]["peak_position_step_m"] == 0.85
    assert windows[0]["view_start_bag_time_s"] == 352.60
    assert windows[0]["view_end_bag_time_s"] == 354.40
    assert windows[1]["event_count"] == 1


def test_aligned_resource_rows_convert_header_time_to_bag_relative_time():
    aligned = [
        {
            "trajectory_time_s": 100.5,
            "recorded_time_s": 100.6,
            "cpu_percent": 125.0,
            "rss_bytes": 104857600,
            "threads": 8,
            "write_bytes": 42,
        }
    ]
    rows = aligned_resource_rows(aligned, origin_timestamp_s=100.0)
    assert len(rows) == 1
    assert np.isclose(rows[0]["bag_time_s"], 0.5)
    assert np.isclose(rows[0]["rss_mib"], 100.0)
    assert rows[0]["cpu_percent"] == 125.0
    assert rows[0]["threads"] == 8


def test_nearest_resource_sample_respects_max_age():
    resources = [
        {"bag_time_s": 1.0, "cpu_percent": 10.0},
        {"bag_time_s": 1.5, "cpu_percent": 20.0},
    ]
    sample, age = nearest_resource_sample(resources, 1.42, max_age_s=0.25)
    assert sample["cpu_percent"] == 20.0
    assert np.isclose(age, 0.08)
    missing, missing_age = nearest_resource_sample(resources, 3.0, max_age_s=0.25)
    assert missing is None
    assert missing_age is None
