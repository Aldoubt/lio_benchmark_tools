#!/usr/bin/env python3
"""Offline audit of paired bag observations. No nodes, playback or GT metrics."""
from __future__ import annotations

import argparse
from collections import defaultdict
import itertools
import json
import math
from pathlib import Path

import numpy as np

from timing_audit import audit_timestamps
from trajectory_discontinuity import robust_jump_threshold, summarize_discontinuities


def read_bag_records(path, topics):
    """Read only; unavailable types retain record times and missing headers."""
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(path), storage_id="sqlite3"),
                rosbag2_py.ConverterOptions("cdr", "cdr"))
    types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    missing = set(topics) - types.keys()
    if missing:
        raise ValueError(f"requested topics absent: {sorted(missing)}")
    classes, unavailable = {}, {}
    for topic in topics:
        try:
            classes[topic] = get_message(types[topic])
        except (ImportError, ModuleNotFoundError) as exc:
            unavailable[topic] = str(exc)
    records = []
    while reader.has_next():
        topic, raw, timestamp = reader.read_next()
        if topic not in topics:
            continue
        row = dict(topic=topic, recorded_s=timestamp * 1e-9, header_s=None)
        records.append(row)
        if topic not in classes:
            continue
        msg = deserialize_message(raw, classes[topic])
        if hasattr(msg, "header"):
            row.update(header_s=msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9,
                       frame_id=msg.header.frame_id,
                       child_frame_id=getattr(msg, "child_frame_id", ""))
        pose = getattr(msg, "pose", None)
        if hasattr(pose, "pose"):
            pose = pose.pose
        if hasattr(pose, "position") and hasattr(pose, "orientation"):
            row["position"] = [pose.position.x, pose.position.y, pose.position.z]
            row["quaternion_xyzw"] = [pose.orientation.x, pose.orientation.y,
                                      pose.orientation.z, pose.orientation.w]
    return records, dict(storage="sqlite3", unavailable_message_types=unavailable,
                         requested_topics=topics,
                         empty_topics=[topic for topic in topics if not any(r['topic'] == topic for r in records)])


def _vector(value, length):
    if value is None:
        return None
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    return result if result.shape == (length,) and np.isfinite(result).all() else None


def audit_poses(records, gap_threshold_s):
    """Use existing position/yaw detector plus full quaternion rotation steps.

    No sorting, interpolation or differencing across frame changes, invalid
    poses, nonpositive time intervals, or large gaps. q and -q are equivalent.
    """
    events, rotations, invalid, excluded = [], [], 0, 0
    frame_key = lambda row: (row.get("frame_id", ""), row.get("child_frame_id", ""))
    segments = []
    offset = 0
    for frame, group in itertools.groupby(records, key=frame_key):
        rows = list(group)
        times, positions, yaws, quaternions = [], [], [], []
        for row in rows:
            p = _vector(row.get("position"), 3)
            q = _vector(row.get("quaternion_xyzw"), 4)
            t = row.get("header_s")
            valid = p is not None and q is not None and t is not None and math.isfinite(t)
            if valid:
                norm = float(np.linalg.norm(q))
                valid = math.isfinite(norm) and norm > 1e-12
            if not valid:
                invalid += 1
                times.append(float('nan'))
                positions.append([float('nan')] * 3)
                yaws.append(float('nan'))
                quaternions.append(None)
                continue
            q = q / norm
            x, y, z, w = q
            times.append(t)
            positions.append(p)
            yaws.append(math.atan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z)))
            quaternions.append(q)
        if len(rows) >= 2:
            trajectory = dict(timestamp_s=times, positions=positions, yaw_rad=yaws)
            summary = summarize_discontinuities('recorded_pose', trajectory, 0.0,
                                                max_gap_s=gap_threshold_s)
            segments.append(dict(frame_id=frame[0], child_frame_id=frame[1],
                                 first_sample_index=offset, **summary))
            events.extend(summary['events'])
        for index in range(1, len(rows)):
            previous, current = quaternions[index - 1:index + 1]
            dt = times[index] - times[index - 1]
            if previous is None or current is None or not (0 < dt <= gap_threshold_s):
                excluded += 1
                continue
            dot = min(1.0, max(0.0, abs(float(np.dot(previous, current)))))
            rotations.append(dict(sample_index=offset + index, timestamp_s=times[index],
                                  rotation_step_deg=math.degrees(2 * math.acos(dot))))
        offset += len(rows)
    threshold = robust_jump_threshold(np.asarray([r['rotation_step_deg'] for r in rotations]), 10.0)
    events.extend(dict(type='rotation_jump', threshold=threshold, **row)
                  for row in rotations if row['rotation_step_deg'] > threshold)
    frame_changes = sum(frame_key(a) != frame_key(b) for a, b in zip(records, records[1:]))
    return dict(metric_class='diagnostic/non-ground-truth', segments=segments, events=events,
                invalid_pose_samples=invalid, frame_change_count=frame_changes,
                excluded_pair_count=excluded + frame_changes,
                rotation_jump_threshold_deg=threshold,
                rotation_jump_count=sum(e['type'] == 'rotation_jump' for e in events),
                position_jump_count=sum(e['type'] == 'position_jump' for e in events),
                yaw_jump_count=sum(e['type'] == 'yaw_jump' for e in events),
                max_rotation_step_deg=max((r['rotation_step_deg'] for r in rotations), default=None))


def audit_records(records, *, gap_threshold_s=0.5, offset_threshold_s=0.2):
    # Validate thresholds even for an empty input.
    audit_timestamps([], [], gap_threshold_s=gap_threshold_s, offset_threshold_s=offset_threshold_s)
    grouped = defaultdict(list)
    for index, row in enumerate(records):
        if not isinstance(row.get('topic'), str) or not row['topic']:
            raise ValueError(f'record {index}: topic is required')
        for field in ('recorded_s', 'header_s'):
            if field not in row or (row[field] is not None and
                                   (isinstance(row[field], bool) or not isinstance(row[field], (int, float)))):
                raise ValueError(f'record {index}: {field} must be numeric or null')
        grouped[row['topic']].append(row)
    result = {}
    for topic, rows in grouped.items():
        timing = audit_timestamps([r['recorded_s'] for r in rows], [r['header_s'] for r in rows],
                                  gap_threshold_s=gap_threshold_s, offset_threshold_s=offset_threshold_s)
        pose = audit_poses(rows, gap_threshold_s) if any('position' in r for r in rows) else None
        result[topic] = dict(timing=timing, pose=pose)
    return dict(schema_version=1, metric_class='diagnostic/non-ground-truth', topics=result,
                sample_count=len(records), status='OBSERVED' if records else 'NO_DATA',
                hypotheses=dict(status='UNCONFIRMED', candidates=[
                    'Timestamp reversal: clock reset, replay ordering, or recorder ordering.',
                    'Gap: source pause, recording omission, scheduling or transport interruption.',
                    'Offset: clock-domain mismatch, buffering, scheduling or transport delay.',
                    'Pose step: genuine fast motion, estimator reset, relocalization or loop correction.']),
                limitations=[
                    'No independent ground truth; no ATE/RPE or drift accuracy is computed.',
                    'Injected faults belong to the fixture manifest, never inferred by the detector.',
                    'No leading/trailing outage detection without an expected observation window.',
                    'Missing topics require an explicit expected topic list; absence is not proof of sensor failure.',
                    'Thresholds are review triggers, not flight acceptance limits.',
                    'A frame change excludes the connecting pose pair; cross-frame motion is not comparable.'])


def render_markdown(report):
    lines = ['# Offline bag audit', '',
             f"Input: `{report.get('source_kind', 'unspecified')}`; status: `{report['status']}`.",
             '', '## Tool observations', '',
             '| Topic | Samples | Header backtracks | Header duplicates | Header gaps | Offset max (s) | Position / yaw / rotation jumps |',
             '|---|---:|---:|---:|---:|---:|---|']
    for topic, item in report['topics'].items():
        t, p = item['timing'], item['pose']
        h = t['clocks']['header']
        jumps = 'not available' if p is None else ' / '.join(str(p[k + '_jump_count']) for k in ('position', 'yaw', 'rotation'))
        lines.append(f"| {topic.replace('|', '/') } | {t['sample_count']} | {h['backtrack_count']} | {h['duplicate_count']} | {h['gap_count']} | {t['record_minus_header_s']['max']} | {jumps} |")
    lines += ['', '## Known injected faults', '',
              'Not inferred. For synthetic runs, see the separate fixture manifest.',
              '', '## Unconfirmed possible causes', '']
    lines += ['- ' + text for text in report['hypotheses']['candidates']]
    lines += ['', '## Limits', ''] + ['- ' + text for text in report['limitations']]
    lines += ['', 'Full per-topic timing events, reader-order indices, clock coverage and excluded pose pairs are in audit.json.',
              'Record minus header is an offset observation, not a proven transport latency.']
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--input-json', type=Path)
    source.add_argument('--bag', type=Path)
    parser.add_argument('--topic', action='append', default=[])
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--gap-threshold-s', type=float, default=0.5)
    parser.add_argument('--offset-threshold-s', type=float, default=0.2)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error('output directory exists; choose a new run directory')
    metadata = {}
    if args.bag:
        if not args.topic:
            parser.error('--bag requires at least one explicit --topic')
        records, metadata = read_bag_records(args.bag, args.topic)
        kind = 'rosbag2/sqlite3/read-only'
    else:
        payload = json.loads(args.input_json.read_text(encoding='utf-8'))
        if payload.get('schema_version') != 1:
            parser.error('input schema_version must be 1')
        records = payload['records']
        kind = payload.get('source_kind', 'external-json/unverified-origin')
    report = audit_records(records, gap_threshold_s=args.gap_threshold_s,
                           offset_threshold_s=args.offset_threshold_s)
    report.update(source_kind=kind, reader_metadata=metadata)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / 'audit.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    (args.output_dir / 'audit.md').write_text(render_markdown(report), encoding='utf-8')
    print(f"{report['status']}: {args.output_dir / 'audit.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
