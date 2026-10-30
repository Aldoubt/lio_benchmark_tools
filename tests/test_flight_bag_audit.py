import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from flight_bag_audit import audit_records
from synthetic_bag_regression import build_cases, observations, run_suite


@pytest.mark.parametrize('name,case', list(build_cases().items()))
def test_injected_faults_and_negative_controls(name, case):
    before = copy.deepcopy(case['records'])
    report = audit_records(case['records'])
    assert observations(report) == case['expected'], name
    assert case['records'] == before
    assert report['hypotheses']['status'] == 'UNCONFIRMED'
    assert report['metric_class'] == 'diagnostic/non-ground-truth'
    json.dumps(report, allow_nan=False)


def test_delay_and_clock_offset_cannot_be_distinguished():
    cases = build_cases()
    assert audit_records(cases['constant_delay']['records']) == audit_records(cases['clock_offset']['records'])
    assert cases['constant_delay']['known_injected_faults'] != cases['clock_offset']['known_injected_faults']


def test_gap_does_not_create_pose_step_from_motion_during_outage():
    report = audit_records(build_cases()['dropout']['records'])
    pose = report['topics']['/odom']['pose']
    assert pose['excluded_pair_count'] == 1
    assert pose['position_jump_count'] == 0  # 1.1 m across gap exceeds ordinary 0.5 m floor


def test_bad_pose_does_not_hide_later_jump_or_bridge_invalid_samples():
    rows = build_cases()['position_jump']['records']
    rows[10]['quaternion_xyzw'] = [0, 0, 0, 0]
    rows[20]['position'] = [float('nan'), 0, 0]
    pose = audit_records(rows)['topics']['/odom']['pose']
    assert pose['invalid_pose_samples'] == 2
    assert pose['excluded_pair_count'] == 4
    assert pose['position_jump_count'] == 1


def test_frame_switch_is_not_pose_jump():
    rows = build_cases()['position_jump']['records']
    for row in rows[40:]:
        row['frame_id'] = 'map'
    pose = audit_records(rows)['topics']['/odom']['pose']
    assert pose['frame_change_count'] == 1
    assert pose['position_jump_count'] == 0


def test_empty_and_multiple_topic_coverage():
    assert audit_records([])['status'] == 'NO_DATA'
    rows = [dict(topic='/imu', recorded_s=1, header_s=None),
            dict(topic='/odom', recorded_s=2, header_s=2)]
    report = audit_records(rows)
    assert report['topics']['/imu']['timing']['clocks']['header']['missing_count'] == 1
    assert report['topics']['/odom']['pose'] is None


def test_outputs_and_cli_reproducible_without_ros_and_no_overwrite(tmp_path):
    suite = tmp_path / 'suite'
    result = run_suite(suite)
    assert result['passed'] and len(result['cases']) == 15
    for case in result['cases']:
        folder = suite / case['case']
        manifest = json.loads((folder / 'injection.json').read_text(encoding='utf-8'))
        assert manifest['input_sha256'] == hashlib.sha256((folder / 'input.json').read_bytes()).hexdigest()
        assert case['input_sha256'] == manifest['input_sha256']
    script = Path(__file__).resolve().parents[1] / 'evaluators' / 'flight_bag_audit.py'
    output = tmp_path / 'single'
    command = [sys.executable, str(script), '--input-json', str(suite / 'combined' / 'input.json'), '--output-dir', str(output)]
    completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
    assert completed.returncode == 0, completed.stderr
    report = json.loads((output / 'audit.json').read_text(encoding='utf-8'))
    assert observations(report) == build_cases()['combined']['expected']
    assert 'Known injected faults' in (output / 'audit.md').read_text(encoding='utf-8')
    assert subprocess.run(command, capture_output=True).returncode != 0
    with pytest.raises(FileExistsError):
        run_suite(suite)
