import json

import pytest

from timing_audit import audit_timestamps, nearest_header_offsets


def test_raw_order_distinguishes_backtrack_duplicate_gap_and_retains_indices():
    result = audit_timestamps([10, 10.1, 10.2, 10.3, 11.4], [10, 10.1, 9.9, 9.9, 11])
    header = result['clocks']['header']
    assert (header['backtrack_count'], header['duplicate_count'], header['gap_count']) == (1, 1, 1)
    assert [(e['type'], e['sample_index']) for e in result['events'] if e['type'].startswith('header_')] == [
        ('header_backtrack', 2), ('header_duplicate', 3), ('header_gap', 4)]


def test_missing_headers_remain_paired_and_do_not_bridge():
    report = audit_timestamps([10, 11, 12, 13], [9.9, None, float('nan'), 12.9])
    assert report['record_minus_header_s']['count'] == 2
    assert report['record_minus_header_s']['mean'] == pytest.approx(0.1)
    assert report['clocks']['header']['gap_count'] == 0
    assert report['clocks']['header']['nonfinite_count'] == 1
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('values', [[], [0.0]])
def test_empty_singleton_and_zero_sim_time(values):
    result = audit_timestamps(values, values)
    assert result['events'] == []
    assert result['clocks']['header']['zero_count'] == len(values)


@pytest.mark.parametrize('threshold', [0, -1, float('nan'), float('inf')])
def test_invalid_threshold(threshold):
    with pytest.raises(ValueError):
        audit_timestamps([], [], gap_threshold_s=threshold)


def test_threshold_boundary_and_negative_offset():
    result = audit_timestamps([1, 1.5], [0.75, 1.75], gap_threshold_s=1, offset_threshold_s=0.25)
    assert [e['type'] for e in result['events']] == ['negative_offset']


def test_mismatched_pairs_are_rejected():
    with pytest.raises(ValueError, match='paired'):
        audit_timestamps([1, 2], [1])


def test_nearest_lookup_handles_both_clocks_backtracking_and_ties():
    assert nearest_header_offsets([10, 1, 5], [11, 0, 2, 9]) == [1, 1, 3]
    assert nearest_header_offsets([1], []) == []
