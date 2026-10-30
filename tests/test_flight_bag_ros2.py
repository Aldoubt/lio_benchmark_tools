"""Optional real CDR/sqlite3 round trip; writes/reads files only, no ROS graph."""
import pytest

from flight_bag_audit import audit_records, read_bag_records
from synthetic_bag_regression import build_cases, observations


@pytest.mark.parametrize('name', ['normal', 'header_backtrack', 'dropout', 'delay_step', 'position_jump', 'roll_jump'])
def test_real_rosbag_roundtrip(tmp_path, name):
    rosbag = pytest.importorskip('rosbag2_py', reason='ROS 2 storage/serialization integration not available')
    serialization = pytest.importorskip('rclpy.serialization')
    messages = pytest.importorskip('nav_msgs.msg')
    bag = tmp_path / 'bag'
    case = build_cases()[name]
    writer = rosbag.SequentialWriter()
    writer.open(rosbag.StorageOptions(uri=str(bag), storage_id='sqlite3'), rosbag.ConverterOptions('cdr', 'cdr'))
    writer.create_topic(rosbag.TopicMetadata(name='/odom', type='nav_msgs/msg/Odometry', serialization_format='cdr'))
    for row in case['records']:
        msg = messages.Odometry()
        stamp = round(row['header_s'] * 1e9)
        msg.header.stamp.sec, msg.header.stamp.nanosec = divmod(stamp, 10**9)
        msg.header.frame_id, msg.child_frame_id = 'odom', 'base_link'
        msg.pose.pose.position.x, msg.pose.pose.position.y, msg.pose.pose.position.z = map(float, row['position'])
        q = msg.pose.pose.orientation
        q.x, q.y, q.z, q.w = map(float, row['quaternion_xyzw'])
        writer.write('/odom', serialization.serialize_message(msg), round(row['recorded_s'] * 1e9))
    del writer
    rows, metadata = read_bag_records(bag, ['/odom'])
    assert not metadata['unavailable_message_types']
    assert observations(audit_records(rows)) == case['expected']
