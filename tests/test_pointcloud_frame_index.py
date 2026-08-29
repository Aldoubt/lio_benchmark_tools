import sqlite3

import pytest

from pointcloud_frame_index import frame_index_row, select_topic_message_rows


def test_frame_index_row_uses_exact_header_time_for_bag_relative_lookup():
    row = frame_index_row(
        message_id=17,
        recorded_timestamp_ns=100_600_000_000,
        header_timestamp_s=100.5,
        origin_timestamp_s=100.0,
    )
    assert row["message_id"] == 17
    assert row["recorded_timestamp_s"] == 100.6
    assert row["header_timestamp_s"] == 100.5
    assert row["bag_time_s"] == 0.5


def test_select_topic_message_rows_reads_only_selected_topic(tmp_path):
    db = tmp_path / "bag.db3"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE topics(id INTEGER PRIMARY KEY, name TEXT, type TEXT)")
    connection.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, topic_id INTEGER, timestamp INTEGER, data BLOB)")
    connection.execute("INSERT INTO topics VALUES (1, '/lidar', 'pkg/msg/Lidar')")
    connection.execute("INSERT INTO topics VALUES (2, '/imu', 'pkg/msg/Imu')")
    connection.execute("INSERT INTO messages VALUES (10, 1, 1000000000, X'01')")
    connection.execute("INSERT INTO messages VALUES (11, 2, 1100000000, X'02')")
    connection.execute("INSERT INTO messages VALUES (12, 1, 1200000000, X'03')")
    connection.commit()

    topic_type, rows = select_topic_message_rows(connection, "/lidar")
    selected = [(row[0], row[1]) for row in rows]
    connection.close()

    assert topic_type == "pkg/msg/Lidar"
    assert selected == [
        (10, 1000000000),
        (12, 1200000000),
    ]


def test_select_topic_message_rows_rejects_missing_topic(tmp_path):
    db = tmp_path / "bag.db3"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE topics(id INTEGER PRIMARY KEY, name TEXT, type TEXT)")
    connection.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, topic_id INTEGER, timestamp INTEGER, data BLOB)")
    connection.commit()
    with pytest.raises(ValueError, match="missing topic"):
        select_topic_message_rows(connection, "/lidar")
    connection.close()
