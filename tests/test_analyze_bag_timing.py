"""Reader plumbing contract using test doubles; not a ROS integration claim."""
import json
import sys
from types import SimpleNamespace as NS

import analyze_bag
from flight_bag_audit import read_bag_records


def install_fake_reader(monkeypatch):
    def stamped(time):
        return NS(header=NS(stamp=NS(sec=int(time), nanosec=round((time - int(time)) * 1e9)), frame_id='sensor'))
    sequence = [('/lidar', stamped(2), 2100000000),
                ('/unknown', b'unknown', 2200000000),
                ('/imu', stamped(3), 3100000000),
                ('/imu', stamped(1), 3200000000),
                ('/lidar', NS(), 3300000000),
                ('/lidar', stamped(4), 4100000000)]
    class Reader:
        def __init__(self):
            self.rows = iter(sequence)
            self.remaining = len(sequence)
        def open(self, *args):
            pass
        def get_all_topics_and_types(self):
            return [NS(name=t, type=t) for t in ('/lidar', '/imu', '/unknown', '/empty')]
        def has_next(self):
            return self.remaining > 0
        def read_next(self):
            self.remaining -= 1
            return next(self.rows)
    def get_message(name):
        if name == '/unknown':
            raise ModuleNotFoundError('unknown custom type')
        return object
    monkeypatch.setitem(sys.modules, 'rosbag2_py', NS(SequentialReader=Reader, StorageOptions=NS, ConverterOptions=lambda *a: a))
    monkeypatch.setitem(sys.modules, 'rclpy.serialization', NS(deserialize_message=lambda raw, cls: raw))
    monkeypatch.setitem(sys.modules, 'rosidl_runtime_py.utilities', NS(get_message=get_message))


def test_existing_bag_audit_counts_unknown_and_pairs_missing_header(monkeypatch, tmp_path):
    install_fake_reader(monkeypatch)
    output = tmp_path / 'audit.json'
    monkeypatch.setattr(sys, 'argv', ['analyze_bag', str(tmp_path), '--output', str(output)])
    assert analyze_bag.main() == 0
    report = json.loads(output.read_text(encoding='utf-8'))
    unknown = report['topics']['/unknown']
    assert unknown['count'] == 1
    assert unknown['decode_status'] == 'unavailable_type'
    assert unknown['timing_audit']['clocks']['header']['missing_count'] == 1
    lidar = report['topics']['/lidar']
    assert lidar['record_minus_header_s']['count'] == 2
    assert abs(lidar['record_minus_header_s']['mean'] - 0.1) < 1e-9
    assert lidar['timing_audit']['clocks']['header']['gap_count'] == 0


def test_flight_reader_preserves_unknown_and_reports_expected_empty_topic(monkeypatch, tmp_path):
    install_fake_reader(monkeypatch)
    rows, metadata = read_bag_records(tmp_path, ['/unknown', '/empty', '/lidar'])
    assert len(rows) == 4
    assert '/unknown' in metadata['unavailable_message_types']
    assert metadata['empty_topics'] == ['/empty']
    assert rows[1]['header_s'] is None
