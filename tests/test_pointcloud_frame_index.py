import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from pointcloud_frame_index import (
    build_pointcloud_frame_index,
    frame_index_row,
    select_topic_message_rows,
)


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


def test_builder_resolves_relative_historical_bag_from_original_run_when_writing_frozen_source(tmp_path):
    original_run = tmp_path / "original-run"
    bag = original_run / "bag"
    bag.mkdir(parents=True)
    db = bag / "bag.db3"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE topics(id INTEGER PRIMARY KEY, name TEXT, type TEXT)")
    connection.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, topic_id INTEGER, timestamp INTEGER, data BLOB)")
    connection.execute("INSERT INTO topics VALUES (1, '/livox/lidar', 'pkg/msg/Lidar')")
    connection.execute("INSERT INTO messages VALUES (10, 1, 100100000000, X'01')")
    connection.execute("INSERT INTO messages VALUES (11, 1, 101100000000, X'02')")
    connection.commit()
    connection.close()

    frozen = tmp_path / "frozen"
    source = frozen / "source"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "dataset": {
                    "bag_dir": "bag",
                    "lidar_topic": "/livox/lidar",
                }
            }
        ),
        encoding="utf-8",
    )
    (frozen / "freeze_manifest.json").write_text(
        json.dumps({"source_run": {"path": str(original_run)}}),
        encoding="utf-8",
    )

    header_times = iter([100.0, 101.0])

    def fake_deserialize(_payload, _message_class):
        value = next(header_times)
        sec = int(value)
        nanosec = int(round((value - sec) * 1e9))
        return SimpleNamespace(
            header=SimpleNamespace(stamp=SimpleNamespace(sec=sec, nanosec=nanosec))
        )

    result = build_pointcloud_frame_index(
        source,
        deserialize_message_fn=fake_deserialize,
        get_message_fn=lambda _type: object,
    )

    payload = json.loads(
        (source / "metrics/pointcloud_frame_index.json").read_text(encoding="utf-8")
    )
    assert Path(payload["sqlite_db"]) == db.resolve()
    assert payload["frame_count"] == 2
    assert [item["bag_time_s"] for item in payload["frames"]] == pytest.approx([0.0, 1.0])
    assert result["artifacts"] == [
        "metrics/pointcloud_frame_index.json",
        "metrics/pointcloud_frame_index.csv",
    ]
