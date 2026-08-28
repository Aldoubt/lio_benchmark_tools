from clock_anchor_recorder import AnchorBuffer, make_anchor


def test_make_anchor_has_wall_and_ros_time():
    anchor = make_anchor(1_700_000_000_123_456_789, 12, 345_000_000, 7)
    assert anchor["wall_time_ns"] == 1_700_000_000_123_456_789
    assert anchor["ros_time_ns"] == 12_345_000_000
    assert anchor["ros_time_s"] == 12.345
    assert anchor["sequence"] == 7
    assert "+00:00" in anchor["at"]


def test_buffer_tracks_backtracks_and_snapshot_contract():
    buffer = AnchorBuffer()
    buffer.append(make_anchor(1000, 10, 0, 0))
    buffer.append(make_anchor(2000, 11, 0, 1))
    buffer.append(make_anchor(1500, 9, 0, 2))
    snapshot = buffer.snapshot("finished")
    assert snapshot["schema_version"] == 1
    assert snapshot["status"] == "finished"
    assert snapshot["samples"] == 3
    assert snapshot["wall_time_backtracks"] == 1
    assert snapshot["ros_time_backtracks"] == 1
    assert snapshot["anchors"][1]["ros_time_s"] == 11.0
