#!/usr/bin/env python3
"""Deterministic injection manifest, raw observations and regression evidence."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

from flight_bag_audit import audit_records, render_markdown


def build_cases():
    base = [dict(topic='/odom', recorded_s=100.0 + i / 10 + 0.02,
                 header_s=100.0 + i / 10, position=[i / 10, 0, 0],
                 quaternion_xyzw=[0, 0, 0, 1], frame_id='odom', child_frame_id='base_link')
            for i in range(80)]
    cases = {}

    def case(name, injection, **expected):
        cases[name] = dict(records=copy.deepcopy(base), known_injected_faults=injection,
                           expected=dict(header_backtracks=0, recorded_backtracks=0,
                                         header_duplicates=0, header_gaps=0, recorded_gaps=0,
                                         high_offsets=0, negative_offsets=0,
                                         position_jumps=0, yaw_jumps=0, rotation_jumps=0) | expected)
        return cases[name]['records']

    case('normal', [])
    rows = case('header_backtrack', ['Subtract 0.4 s from headers at original indices 20..79; record clock unchanged.'],
                header_backtracks=1, high_offsets=60)
    for row in rows[20:]:
        row['header_s'] -= 0.4
    rows = case('recorded_backtrack', ['Subtract 0.3 s from record timestamp at index 20; preserve fixture reader order.'],
                recorded_backtracks=1, negative_offsets=1)
    rows[20]['recorded_s'] -= 0.3
    rows = case('duplicate_header', ['Copy header 19 to header 20; retain both records.'], header_duplicates=1)
    rows[20]['header_s'] = rows[19]['header_s']
    rows = case('dropout', ['Remove original indices 20..29 (10 messages); remaining timestamps unchanged.'],
                header_gaps=1, recorded_gaps=1)
    del rows[20:30]
    rows = case('delay_step', ['Add 0.35 s to record timestamps at indices 20..79, simulating delayed recording.'], high_offsets=60)
    for row in rows[20:]:
        row['recorded_s'] += 0.35
    rows = case('constant_delay', ['Add 0.35 s to all record times: designated synthetic buffering delay.'], high_offsets=80)
    for row in rows:
        row['recorded_s'] += 0.35
    rows = case('clock_offset', ['Add 0.35 s to all record times: designated clock offset; observationally identical to constant_delay.'], high_offsets=80)
    for row in rows:
        row['recorded_s'] += 0.35
    rows = case('negative_offset', ['Add 10 s to all header timestamps: distinct clock domains.'], negative_offsets=80)
    for row in rows:
        row['header_s'] += 10
    rows = case('position_jump', ['Add 2 m to x at original indices 40..79.'], position_jumps=1)
    for row in rows[40:]:
        row['position'][0] += 2
    rows = case('yaw_jump', ['Apply a 90 degree yaw step at original indices 40..79.'], yaw_jumps=1, rotation_jumps=1)
    for row in rows[40:]:
        row['quaternion_xyzw'] = [0, 0, math.sin(math.pi / 4), math.cos(math.pi / 4)]
    for axis, name in ((0, 'roll_jump'), (1, 'pitch_jump')):
        rows = case(name, [f'Apply a 60 degree {name} at original indices 40..79; yaw unchanged.'], rotation_jumps=1)
        for row in rows[40:]:
            row['quaternion_xyzw'] = [0, 0, 0, math.cos(math.pi / 6)]
            row['quaternion_xyzw'][axis] = math.sin(math.pi / 6)
    rows = case('quaternion_sign', ['Negate all quaternion components at indices 40..79; same physical orientation.'])
    for row in rows[40:]:
        row['quaternion_xyzw'] = [0, 0, 0, -1]
    rows = case('combined', ['Remove indices 20..29; subtract 0.4 s from headers at original 40..79; add 2 m x at original 50..79.'],
                header_backtracks=1, header_gaps=1, recorded_gaps=1, high_offsets=40, position_jumps=1)
    for row in rows[40:]:
        row['header_s'] -= 0.4
    for row in rows[50:]:
        row['position'][0] += 2
    del rows[20:30]
    return cases


def observations(report):
    timing = report['topics']['/odom']['timing']
    pose = report['topics']['/odom']['pose']
    return dict(header_backtracks=timing['clocks']['header']['backtrack_count'],
                recorded_backtracks=timing['clocks']['recorded']['backtrack_count'],
                header_duplicates=timing['clocks']['header']['duplicate_count'],
                header_gaps=timing['clocks']['header']['gap_count'],
                recorded_gaps=timing['clocks']['recorded']['gap_count'],
                high_offsets=sum(e['type'] == 'offset_above_threshold' for e in timing['events']),
                negative_offsets=sum(e['type'] == 'negative_offset' for e in timing['events']),
                position_jumps=pose['position_jump_count'], yaw_jumps=pose['yaw_jump_count'],
                rotation_jumps=pose['rotation_jump_count'])


def run_suite(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for name, case in build_cases().items():
        folder = output / name
        folder.mkdir()
        payload = dict(schema_version=1, source_kind='synthetic/message-sequence', records=case['records'])
        source = json.dumps(payload, indent=2, allow_nan=False) + '\n'
        # Hash exactly the persisted bytes on Windows as well as Linux.
        (folder / 'input.json').write_bytes(source.encode('utf-8'))
        manifest = dict(known_injected_faults=case['known_injected_faults'], expected=case['expected'],
                        input_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest(),
                        thresholds=dict(gap_s=0.5, offset_s=0.2), independent_ground_truth=False)
        (folder / 'injection.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        report = audit_records(case['records'])
        report['source_kind'] = payload['source_kind']
        observed = observations(report)
        passed = observed == case['expected']
        result = dict(case=name, passed=passed, known_injected_faults=case['known_injected_faults'],
                      expected=case['expected'], tool_observations=observed,
                      cause_status='UNCONFIRMED_BY_TOOL', input_sha256=manifest['input_sha256'])
        results.append(result)
        (folder / 'audit.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        (folder / 'audit.md').write_text(render_markdown(report), encoding='utf-8')
    summary = dict(schema_version=1, source_kind='synthetic/message-sequence',
                   metric_class='diagnostic/non-ground-truth', passed=all(r['passed'] for r in results), cases=results)
    (output / 'regression.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    lines = ['# Synthetic bag regression', '',
             'Synthetic message sequences, not real flight bags or a ROS/DDS runtime test.',
             'Known mutations are generator facts. Observed events do not establish real-world causes or drift accuracy.', '',
             '| Case | Known injected change | Tool observations (nonzero) | Regression |',
             '|---|---|---|---|']
    for result in results:
        lines.append('| ' + ' | '.join([result['case'], '; '.join(result['known_injected_faults']) or 'None',
                     ', '.join(f'{k}={v}' for k, v in result['tool_observations'].items() if v) or 'No threshold events',
                     'PASS' if result['passed'] else 'FAIL']) + ' |')
    lines += ['', 'All proposed causes remain UNCONFIRMED_BY_TOOL. Constant delay and clock offset intentionally produce identical observations.',
              'Dropout only proves an observed inter-record gap; its exact removed count is known solely from the injection manifest.',
              'Position/rotation steps are diagnostics; relocalization or loop correction may legitimately produce them.',
              'Each case contains input.json, injection.json, audit.json and audit.md. Outputs refuse directory reuse.']
    (output / 'regression.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = run_suite(args.output_dir)
    print(f"{sum(r['passed'] for r in result['cases'])}/{len(result['cases'])} cases passed: {args.output_dir / 'regression.md'}")
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
