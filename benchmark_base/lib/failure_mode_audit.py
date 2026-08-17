#!/usr/bin/env python3
"""Read-only temporal failure-mode audit over Representative Window V1 evidence.

The audit is deliberately descriptive: it relates trajectory temporal-coverage
large-gap events to already-frozen Relative SE(3) pairwise disagreement onsets.
It never reads the source ROS bag, reruns an estimator, recomputes Relative
SE(3), repairs timestamps, or mutates a child run.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "lio_benchmark_failure_mode_audit/v1"
SCHEMA_VERSION = 1
SCIENTIFIC_STATUS = "DESCRIPTIVE_NO_GROUND_TRUTH"
GAP_MULTIPLIER = 1.5
WINDOW_LABELS = (
    "initialization",
    "high_angular_motion",
    "geometric_degeneracy_candidate",
    "steady_translation_candidate",
)
EXPECTED_ALGORITHMS = ("fast_livo2", "fast_lio2", "kiss_icp")
TARGET_CASES = (
    ("high_angular_motion", "kiss_icp"),
    ("steady_translation_candidate", "fast_livo2"),
)

COVERAGE_CONTEXT_FIELDS = (
    "window_label",
    "algorithm_id",
    "input_lidar_count",
    "input_lidar_effective_hz",
    "input_lidar_median_period_s",
    "input_lidar_p95_period_s",
    "input_lidar_max_period_s",
    "input_lidar_large_gap_count",
    "trajectory_count",
    "trajectory_effective_hz",
    "trajectory_median_period_s",
    "trajectory_p95_period_s",
    "trajectory_max_period_s",
    "trajectory_large_gap_count",
    "first_trajectory_lag_from_input_s",
    "last_trajectory_delta_to_input_end_s",
    "trajectory_to_input_count_ratio",
    "computed_input_relative_degradation_event_count",
    "first_input_relative_degradation_onset_s",
)
COVERAGE_EVENT_FIELDS = (
    "window_label",
    "algorithm_id",
    "previous_output_timestamp_s",
    "current_output_timestamp_s",
    "interval_s",
    "input_lidar_median_period_s",
    "gap_multiplier",
    "gap_threshold_s",
    "degradation_onset_timestamp_s",
    "degradation_onset_relative_to_trajectory_start_s",
    "estimated_skipped_input_slots",
)
ONSET_RELATION_FIELDS = (
    "window_label",
    "algorithm_id",
    "left_algorithm_id",
    "right_algorithm_id",
    "metric",
    "threshold",
    "unit",
    "sustain_samples",
    "divergence_onset_timestamp_s",
    "divergence_onset_relative_time_s",
    "divergence_onset_value",
    "first_coverage_degradation_onset_s",
    "divergence_minus_first_coverage_s",
    "preceding_coverage_degradation_onset_s",
    "lead_from_preceding_coverage_s",
    "following_coverage_degradation_onset_s",
    "lag_to_following_coverage_s",
    "temporal_order",
)
TARGET_SUMMARY_FIELDS = (
    "window_label",
    "algorithm_id",
    "coverage_degradation_event_count",
    "first_coverage_degradation_onset_s",
    "crossed_relative_se3_onset_count",
    "earliest_relative_se3_onset_timestamp_s",
    "earliest_relative_se3_pair",
    "earliest_relative_se3_metric",
    "earliest_relative_se3_threshold",
    "earliest_divergence_minus_first_coverage_s",
    "temporal_order",
    "scientific_status",
)

_REQUIRED_COVERAGE_FIELDS = {
    "algorithm_id",
    "input_lidar_median_period_s",
    "trajectory_count",
    "trajectory_median_period_s",
    "trajectory_large_gap_count",
    "first_trajectory_lag_from_input_s",
    "last_trajectory_delta_to_input_end_s",
    "trajectory_to_input_count_ratio",
}
_REQUIRED_ONSET_FIELDS = {
    "left_algorithm_id",
    "right_algorithm_id",
    "metric",
    "threshold",
    "unit",
    "sustain_samples",
    "crossed",
    "onset_timestamp_s",
    "onset_relative_time_s",
    "onset_value",
}


def _finite_positive(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{label} must be a finite positive number")
    return parsed


def _finite(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be finite")
    return parsed


def _bool(value: Any) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _validated_timestamps(values: Sequence[float]) -> tuple[float, ...]:
    timestamps = tuple(float(value) for value in values)
    if not timestamps:
        raise ValueError("trajectory timestamps must not be empty")
    if not all(math.isfinite(value) for value in timestamps):
        raise ValueError("trajectory timestamps must be finite")
    if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("trajectory timestamps must be strictly increasing")
    return timestamps


def extract_coverage_events(
    *,
    window_label: str,
    algorithm_id: str,
    timestamps: Sequence[float],
    input_median_period_s: float,
) -> list[dict[str, Any]]:
    """Return input-relative large-gap events without repairing the trajectory."""
    values = _validated_timestamps(timestamps)
    input_period = _finite_positive(input_median_period_s, "input LiDAR median period")
    threshold = GAP_MULTIPLIER * input_period
    trajectory_start = values[0]
    events: list[dict[str, Any]] = []
    for previous, current in zip(values, values[1:]):
        interval = current - previous
        if interval <= threshold:
            continue
        onset = previous + threshold
        skipped = max(0, int(round(interval / input_period)) - 1)
        events.append(
            {
                "window_label": str(window_label),
                "algorithm_id": str(algorithm_id),
                "previous_output_timestamp_s": previous,
                "current_output_timestamp_s": current,
                "interval_s": interval,
                "input_lidar_median_period_s": input_period,
                "gap_multiplier": GAP_MULTIPLIER,
                "gap_threshold_s": threshold,
                "degradation_onset_timestamp_s": onset,
                "degradation_onset_relative_to_trajectory_start_s": onset - trajectory_start,
                "estimated_skipped_input_slots": skipped,
            }
        )
    return events


def _crossed_onsets_for_algorithm(
    algorithm_id: str,
    onset_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in onset_rows:
        left = str(raw.get("left_algorithm_id", "")).strip()
        right = str(raw.get("right_algorithm_id", "")).strip()
        if algorithm_id not in {left, right}:
            continue
        if not _bool(raw.get("crossed", "False")):
            continue
        timestamp = _finite(raw.get("onset_timestamp_s"), "crossed Relative SE(3) onset timestamp")
        row = {str(key): value for key, value in raw.items()}
        row["_timestamp"] = timestamp
        rows.append(row)
    rows.sort(
        key=lambda row: (
            float(row["_timestamp"]),
            str(row.get("left_algorithm_id", "")),
            str(row.get("right_algorithm_id", "")),
            str(row.get("metric", "")),
            float(row.get("threshold", 0.0)),
        )
    )
    return rows


def _temporal_order(first_coverage: float | None, divergence: float | None) -> str:
    if divergence is None:
        return "NO_CROSSED_RELATIVE_SE3_ONSET"
    if first_coverage is None:
        return "NO_COVERAGE_DEGRADATION_EVENT"
    if first_coverage < divergence:
        return "COVERAGE_DEGRADATION_FIRST"
    if first_coverage > divergence:
        return "DESCRIPTIVE_DIVERGENCE_FIRST"
    return "SAME_TIMESTAMP"


def relate_onsets_to_coverage(
    *,
    window_label: str,
    algorithm_id: str,
    coverage_events: Sequence[Mapping[str, Any]],
    onset_rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Relate existing sustained disagreement onsets to coverage events.

    The returned timing is an association only. No causal direction or
    estimator correctness is inferred.
    """
    event_times = sorted(
        _finite(event.get("degradation_onset_timestamp_s"), "coverage degradation onset")
        for event in coverage_events
    )
    crossed = _crossed_onsets_for_algorithm(algorithm_id, onset_rows)
    first_coverage = event_times[0] if event_times else None

    relations: list[dict[str, Any]] = []
    for onset in crossed:
        divergence = float(onset["_timestamp"])
        preceding = [value for value in event_times if value <= divergence]
        following = [value for value in event_times if value > divergence]
        previous = preceding[-1] if preceding else None
        next_value = following[0] if following else None
        relations.append(
            {
                "window_label": str(window_label),
                "algorithm_id": str(algorithm_id),
                "left_algorithm_id": str(onset.get("left_algorithm_id", "")),
                "right_algorithm_id": str(onset.get("right_algorithm_id", "")),
                "metric": str(onset.get("metric", "")),
                "threshold": onset.get("threshold"),
                "unit": str(onset.get("unit", "")),
                "sustain_samples": onset.get("sustain_samples"),
                "divergence_onset_timestamp_s": divergence,
                "divergence_onset_relative_time_s": (
                    None
                    if str(onset.get("onset_relative_time_s", "")).strip() == ""
                    else _finite(onset.get("onset_relative_time_s"), "Relative SE(3) onset relative time")
                ),
                "divergence_onset_value": (
                    None
                    if str(onset.get("onset_value", "")).strip() == ""
                    else _finite(onset.get("onset_value"), "Relative SE(3) onset value")
                ),
                "first_coverage_degradation_onset_s": first_coverage,
                "divergence_minus_first_coverage_s": (
                    None if first_coverage is None else divergence - first_coverage
                ),
                "preceding_coverage_degradation_onset_s": previous,
                "lead_from_preceding_coverage_s": (
                    None if previous is None else divergence - previous
                ),
                "following_coverage_degradation_onset_s": next_value,
                "lag_to_following_coverage_s": (
                    None if next_value is None else next_value - divergence
                ),
                "temporal_order": _temporal_order(first_coverage, divergence),
            }
        )

    if not crossed:
        summary = {
            "window_label": str(window_label),
            "algorithm_id": str(algorithm_id),
            "coverage_degradation_event_count": len(event_times),
            "first_coverage_degradation_onset_s": first_coverage,
            "crossed_relative_se3_onset_count": 0,
            "earliest_relative_se3_onset_timestamp_s": None,
            "earliest_relative_se3_pair": None,
            "earliest_relative_se3_metric": None,
            "earliest_relative_se3_threshold": None,
            "earliest_divergence_minus_first_coverage_s": None,
            "temporal_order": "NO_CROSSED_RELATIVE_SE3_ONSET",
            "scientific_status": SCIENTIFIC_STATUS,
        }
        return relations, summary

    earliest = relations[0]
    summary = {
        "window_label": str(window_label),
        "algorithm_id": str(algorithm_id),
        "coverage_degradation_event_count": len(event_times),
        "first_coverage_degradation_onset_s": first_coverage,
        "crossed_relative_se3_onset_count": len(crossed),
        "earliest_relative_se3_onset_timestamp_s": earliest["divergence_onset_timestamp_s"],
        "earliest_relative_se3_pair": (
            f"{earliest['left_algorithm_id']}<->{earliest['right_algorithm_id']}"
        ),
        "earliest_relative_se3_metric": earliest["metric"],
        "earliest_relative_se3_threshold": earliest["threshold"],
        "earliest_divergence_minus_first_coverage_s": earliest[
            "divergence_minus_first_coverage_s"
        ],
        "temporal_order": earliest["temporal_order"],
        "scientific_status": SCIENTIFIC_STATUS,
    }
    return relations, summary


def _read_csv(path: Path, required_fields: set[str] | None = None) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"missing required evidence: {path}")
    try:
        with path.open("r", newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            fields = set(reader.fieldnames or ())
            if required_fields and not required_fields.issubset(fields):
                missing = sorted(required_fields - fields)
                raise ValueError(f"evidence CSV missing fields {missing}: {path}")
            rows = list(reader)
    except OSError as exc:
        raise ValueError(f"unable to read evidence CSV {path}: {exc}") from exc
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"missing required evidence: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON evidence must be an object: {path}")
    return value


def _trajectory_timestamps(path: Path) -> tuple[float, ...]:
    rows = _read_csv(path, {"timestamp_s"})
    if not rows:
        raise ValueError(f"standardized trajectory has no samples: {path}")
    try:
        values = tuple(float(row["timestamp_s"]) for row in rows)
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError(f"invalid trajectory timestamp in {path}") from exc
    return _validated_timestamps(values)


def _fingerprint(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"unable to fingerprint evidence {path}: {exc}") from exc
    return {
        "path": str(path.resolve()),
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _coverage_row_by_algorithm(rows: Sequence[Mapping[str, str]], path: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        algorithm_id = str(row.get("algorithm_id", "")).strip()
        if not algorithm_id:
            raise ValueError(f"coverage row missing algorithm_id: {path}")
        if algorithm_id in result:
            raise ValueError(f"duplicate coverage row for {algorithm_id}: {path}")
        result[algorithm_id] = dict(row)
    if set(result) != set(EXPECTED_ALGORITHMS):
        raise ValueError(
            "trajectory coverage must contain exactly the Representative Window V1 algorithms: "
            f"expected={list(EXPECTED_ALGORITHMS)} actual={sorted(result)} path={path}"
        )
    return result


def _context_record(
    window_label: str,
    algorithm_id: str,
    coverage: Mapping[str, str],
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    record: dict[str, Any] = {"window_label": window_label, "algorithm_id": algorithm_id}
    for field in COVERAGE_CONTEXT_FIELDS:
        if field in {"window_label", "algorithm_id"}:
            continue
        if field == "computed_input_relative_degradation_event_count":
            record[field] = len(events)
        elif field == "first_input_relative_degradation_onset_s":
            record[field] = events[0]["degradation_onset_timestamp_s"] if events else None
        else:
            record[field] = coverage.get(field)
    return record


def _format_optional(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, float):
        return f"{value:.9f}"
    return str(value)


def _render_report(batch_id: str, summaries: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Failure-Mode Audit V1",
        "",
        f"Batch: `{batch_id}`",
        "",
        f"Scientific status: `{SCIENTIFIC_STATUS}`",
        "",
        "This audit is descriptive only. It compares timestamp coverage degradation with already-frozen Relative SE(3) pairwise disagreement onsets; it does not establish causality or ground-truth accuracy.",
        "",
        "## Focus cases",
        "",
    ]
    for summary in summaries:
        label = f"{summary['window_label']} / {summary['algorithm_id']}"
        lines.extend(
            [
                f"### {label}",
                "",
                f"- coverage degradation events: `{summary['coverage_degradation_event_count']}`",
                f"- first coverage degradation onset [s]: `{_format_optional(summary['first_coverage_degradation_onset_s'])}`",
                f"- crossed Relative SE(3) sustained onsets involving target: `{summary['crossed_relative_se3_onset_count']}`",
                f"- earliest Relative SE(3) onset [s]: `{_format_optional(summary['earliest_relative_se3_onset_timestamp_s'])}`",
                f"- earliest pair: `{_format_optional(summary['earliest_relative_se3_pair'])}`",
                f"- earliest metric / threshold: `{_format_optional(summary['earliest_relative_se3_metric'])} / {_format_optional(summary['earliest_relative_se3_threshold'])}`",
                f"- divergence onset minus first coverage degradation [s]: `{_format_optional(summary['earliest_divergence_minus_first_coverage_s'])}`",
                f"- temporal order: `{summary['temporal_order']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation boundary",
            "",
            "A positive signed delta means the first detected input-relative coverage degradation preceded that particular sustained pairwise disagreement onset. A negative delta means the descriptive disagreement onset occurred first. This ordering alone is not a causal diagnosis.",
            "",
        ]
    )
    return "\n".join(lines)


def audit_batch(run_root: str | Path, batch_id: str) -> Path:
    """Audit the four immutable Representative Window V1 child runs."""
    root = Path(run_root).expanduser().resolve()
    batch = str(batch_id).strip()
    if not batch:
        raise ValueError("batch_id must not be empty")
    if not root.is_dir():
        raise ValueError(f"run root does not exist: {root}")
    output = root / f"{batch}_failure_mode_audit_v1"
    if output.exists():
        raise ValueError(f"refusing to overwrite existing Failure-Mode Audit V1 output: {output}")

    child_runs: dict[str, Path] = {}
    for window in WINDOW_LABELS:
        child = root / f"{batch}_{window}"
        if not child.is_dir():
            raise ValueError(f"missing Representative Window V1 child run: {child}")
        child_runs[window] = child

    coverage_context: list[dict[str, Any]] = []
    coverage_events: list[dict[str, Any]] = []
    onset_by_window: dict[str, list[dict[str, str]]] = {}
    events_by_case: dict[tuple[str, str], list[dict[str, Any]]] = {}
    evidence_paths: list[Path] = []
    relative_contracts: dict[str, dict[str, Any]] = {}

    # Validate every input and construct all records before creating output.
    for window in WINDOW_LABELS:
        run = child_runs[window]
        manifest_path = run / "manifest.json"
        coverage_path = run / "metrics" / "trajectory_coverage.csv"
        relative_metadata_path = run / "metrics" / "relative_se3" / "metadata.json"
        onset_path = run / "metrics" / "relative_se3" / "onset_thresholds.csv"

        manifest = _read_json(manifest_path)
        algorithms = manifest.get("algorithms")
        if not isinstance(algorithms, dict) or set(algorithms) != set(EXPECTED_ALGORITHMS):
            raise ValueError(
                f"child manifest algorithms do not match Representative Window V1 contract: {manifest_path}"
            )
        coverage_rows = _read_csv(coverage_path, _REQUIRED_COVERAGE_FIELDS)
        coverage_map = _coverage_row_by_algorithm(coverage_rows, coverage_path)
        relative_metadata = _read_json(relative_metadata_path)
        if str(relative_metadata.get("ground_truth", "")).strip().upper() != "NONE":
            raise ValueError(f"Relative SE(3) ground_truth must be NONE: {relative_metadata_path}")
        if str(relative_metadata.get("terminology", "")).strip().upper() != "PAIRWISE_DISAGREEMENT":
            raise ValueError(
                f"Relative SE(3) terminology must be PAIRWISE_DISAGREEMENT: {relative_metadata_path}"
            )
        sample_period = _finite_positive(
            relative_metadata.get("sample_period_s"), "Relative SE(3) sample period"
        )
        try:
            sustain_samples = int(relative_metadata.get("sustain_samples"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid Relative SE(3) sustain_samples: {relative_metadata_path}") from exc
        if sustain_samples <= 0:
            raise ValueError(f"invalid Relative SE(3) sustain_samples: {relative_metadata_path}")
        relative_contracts[window] = {
            "sample_period_s": sample_period,
            "sustain_samples": sustain_samples,
            "ground_truth": "NONE",
            "terminology": "PAIRWISE_DISAGREEMENT",
        }
        onset_rows = _read_csv(onset_path, _REQUIRED_ONSET_FIELDS)
        onset_by_window[window] = onset_rows

        evidence_paths.extend(
            [manifest_path, coverage_path, relative_metadata_path, onset_path]
        )
        for algorithm_id in EXPECTED_ALGORITHMS:
            trajectory_path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
            timestamps = _trajectory_timestamps(trajectory_path)
            input_period = _finite_positive(
                coverage_map[algorithm_id].get("input_lidar_median_period_s"),
                f"{window}/{algorithm_id} input LiDAR median period",
            )
            events = extract_coverage_events(
                window_label=window,
                algorithm_id=algorithm_id,
                timestamps=timestamps,
                input_median_period_s=input_period,
            )
            coverage_events.extend(events)
            events_by_case[(window, algorithm_id)] = events
            coverage_context.append(
                _context_record(window, algorithm_id, coverage_map[algorithm_id], events)
            )
            evidence_paths.append(trajectory_path)

    onset_relations: list[dict[str, Any]] = []
    target_summaries: list[dict[str, Any]] = []
    for window, algorithm_id in TARGET_CASES:
        relations, summary = relate_onsets_to_coverage(
            window_label=window,
            algorithm_id=algorithm_id,
            coverage_events=events_by_case[(window, algorithm_id)],
            onset_rows=onset_by_window[window],
        )
        onset_relations.extend(relations)
        target_summaries.append(summary)

    fingerprints = [_fingerprint(path) for path in evidence_paths]
    metadata = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch,
        "run_root": str(root),
        "scientific_status": SCIENTIFIC_STATUS,
        "ground_truth": "NONE",
        "interpretation": "TEMPORAL_ASSOCIATION_ONLY",
        "coverage_degradation_definition": {
            "source": "standardized trajectory timestamps + existing trajectory_coverage.csv input median",
            "large_gap_multiplier": GAP_MULTIPLIER,
            "criterion": "trajectory interval > 1.5 * input_lidar_median_period_s",
            "onset": "previous_output_timestamp_s + 1.5 * input_lidar_median_period_s",
            "timestamp_repair": "NONE",
        },
        "relative_se3_source": "EXISTING_ONSET_THRESHOLDS_ONLY",
        "relative_se3_contracts": relative_contracts,
        "window_labels": list(WINDOW_LABELS),
        "expected_algorithms": list(EXPECTED_ALGORITHMS),
        "target_cases": [
            {"window_label": window, "algorithm_id": algorithm_id}
            for window, algorithm_id in TARGET_CASES
        ],
        "child_runs": [
            {"window_label": window, "path": str(child_runs[window])}
            for window in WINDOW_LABELS
        ],
        "evidence_files": fingerprints,
    }

    staging = Path(tempfile.mkdtemp(prefix=f".{batch}_failure_mode_audit_v1.", dir=root))
    try:
        (staging / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_csv(
            staging / "coverage_context.csv", COVERAGE_CONTEXT_FIELDS, coverage_context
        )
        _write_csv(staging / "coverage_events.csv", COVERAGE_EVENT_FIELDS, coverage_events)
        _write_csv(staging / "onset_relations.csv", ONSET_RELATION_FIELDS, onset_relations)
        _write_csv(staging / "target_summary.csv", TARGET_SUMMARY_FIELDS, target_summaries)
        (staging / "FAILURE_MODE_AUDIT_V1.md").write_text(
            _render_report(batch, target_summaries), encoding="utf-8"
        )
        staging.replace(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output
