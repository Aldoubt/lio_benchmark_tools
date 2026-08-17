from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmark_base.lib.failure_mode_audit import (
    EXPECTED_ALGORITHMS,
    GAP_MULTIPLIER,
    TARGET_CASES,
    WINDOW_LABELS,
    audit_batch,
    extract_coverage_events,
    relate_onsets_to_coverage,
)


class FailureModeAuditTest(unittest.TestCase):
    def test_extract_coverage_events_uses_frozen_input_relative_1p5x_threshold(self) -> None:
        events = extract_coverage_events(
            window_label="high_angular_motion",
            algorithm_id="kiss_icp",
            timestamps=(10.0, 10.1, 10.2, 10.5, 10.6),
            input_median_period_s=0.1,
        )
        self.assertEqual(1.5, GAP_MULTIPLIER)
        self.assertEqual(1, len(events))
        event = events[0]
        self.assertEqual("high_angular_motion", event["window_label"])
        self.assertEqual("kiss_icp", event["algorithm_id"])
        self.assertAlmostEqual(0.3, event["interval_s"])
        self.assertAlmostEqual(0.15, event["gap_threshold_s"])
        self.assertAlmostEqual(10.35, event["degradation_onset_timestamp_s"])
        self.assertEqual(2, event["estimated_skipped_input_slots"])

    def test_exact_threshold_is_not_a_degradation_event(self) -> None:
        events = extract_coverage_events(
            window_label="initialization",
            algorithm_id="fast_lio2",
            timestamps=(0.0, 0.15, 0.25),
            input_median_period_s=0.1,
        )
        self.assertEqual([], events)

    def test_non_increasing_trajectory_timestamps_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            extract_coverage_events(
                window_label="high_angular_motion",
                algorithm_id="kiss_icp",
                timestamps=(0.0, 0.1, 0.1, 0.2),
                input_median_period_s=0.1,
            )

    def test_relation_records_first_and_nearest_coverage_events_without_causal_claim(self) -> None:
        events = [
            {
                "window_label": "high_angular_motion",
                "algorithm_id": "kiss_icp",
                "degradation_onset_timestamp_s": 10.35,
            },
            {
                "window_label": "high_angular_motion",
                "algorithm_id": "kiss_icp",
                "degradation_onset_timestamp_s": 10.75,
            },
        ]
        onset_rows = [
            {
                "left_algorithm_id": "fast_lio2",
                "right_algorithm_id": "kiss_icp",
                "metric": "xyz_m",
                "threshold": "0.05",
                "unit": "m",
                "sustain_samples": "3",
                "crossed": "True",
                "onset_timestamp_s": "10.60",
                "onset_relative_time_s": "0.60",
                "onset_value": "0.06",
            },
            {
                "left_algorithm_id": "fast_lio2",
                "right_algorithm_id": "fast_lio2",
                "metric": "xyz_m",
                "threshold": "0.05",
                "unit": "m",
                "sustain_samples": "3",
                "crossed": "True",
                "onset_timestamp_s": "10.40",
                "onset_relative_time_s": "0.40",
                "onset_value": "0.07",
            },
        ]
        relations, summary = relate_onsets_to_coverage(
            window_label="high_angular_motion",
            algorithm_id="kiss_icp",
            coverage_events=events,
            onset_rows=onset_rows,
        )
        self.assertEqual(1, len(relations))
        row = relations[0]
        self.assertEqual("COVERAGE_DEGRADATION_FIRST", row["temporal_order"])
        self.assertAlmostEqual(0.25, row["divergence_minus_first_coverage_s"])
        self.assertAlmostEqual(10.35, row["preceding_coverage_degradation_onset_s"])
        self.assertAlmostEqual(0.25, row["lead_from_preceding_coverage_s"])
        self.assertAlmostEqual(10.75, row["following_coverage_degradation_onset_s"])
        self.assertAlmostEqual(0.15, row["lag_to_following_coverage_s"])
        self.assertEqual("COVERAGE_DEGRADATION_FIRST", summary["temporal_order"])
        self.assertNotIn("cause", json.dumps(summary).lower())
        self.assertNotIn("failure", json.dumps(summary).lower())

    def test_relation_explicitly_handles_no_coverage_event(self) -> None:
        onset_rows = [
            {
                "left_algorithm_id": "fast_lio2",
                "right_algorithm_id": "kiss_icp",
                "metric": "rotation_deg",
                "threshold": "1.0",
                "unit": "deg",
                "sustain_samples": "3",
                "crossed": "True",
                "onset_timestamp_s": "4.0",
                "onset_relative_time_s": "1.0",
                "onset_value": "1.2",
            }
        ]
        relations, summary = relate_onsets_to_coverage(
            window_label="high_angular_motion",
            algorithm_id="kiss_icp",
            coverage_events=[],
            onset_rows=onset_rows,
        )
        self.assertEqual("NO_COVERAGE_DEGRADATION_EVENT", relations[0]["temporal_order"])
        self.assertEqual("NO_COVERAGE_DEGRADATION_EVENT", summary["temporal_order"])

    def test_relation_explicitly_handles_no_crossed_relative_se3_onset(self) -> None:
        relations, summary = relate_onsets_to_coverage(
            window_label="steady_translation_candidate",
            algorithm_id="fast_livo2",
            coverage_events=[
                {
                    "window_label": "steady_translation_candidate",
                    "algorithm_id": "fast_livo2",
                    "degradation_onset_timestamp_s": 3.0,
                }
            ],
            onset_rows=[
                {
                    "left_algorithm_id": "fast_livo2",
                    "right_algorithm_id": "fast_lio2",
                    "metric": "xyz_m",
                    "threshold": "0.05",
                    "unit": "m",
                    "sustain_samples": "3",
                    "crossed": "False",
                    "onset_timestamp_s": "",
                    "onset_relative_time_s": "",
                    "onset_value": "",
                }
            ],
        )
        self.assertEqual([], relations)
        self.assertEqual("NO_CROSSED_RELATIVE_SE3_ONSET", summary["temporal_order"])

    def test_audit_batch_requires_all_four_child_runs_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_id = "repv1_test"
            for window in WINDOW_LABELS[:-1]:
                (root / f"{batch_id}_{window}").mkdir()
            with self.assertRaisesRegex(ValueError, "missing Representative Window V1 child run"):
                audit_batch(root, batch_id)

            for child in root.iterdir():
                if child.is_dir():
                    for nested in child.iterdir():
                        if nested.is_file():
                            nested.unlink()
            # Build a valid batch, then prove immutable output refusal.
            for window in WINDOW_LABELS:
                self._write_child(root, batch_id, window)
            output = audit_batch(root, batch_id)
            self.assertTrue(output.is_dir())
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                audit_batch(root, batch_id)

    def test_audit_batch_writes_all_window_context_target_summaries_and_evidence_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_id = "repv1_test"
            for window in WINDOW_LABELS:
                self._write_child(root, batch_id, window)

            output = audit_batch(root, batch_id)
            self.assertEqual(root / f"{batch_id}_failure_mode_audit_v1", output)
            self.assertEqual(
                {
                    "metadata.json",
                    "coverage_context.csv",
                    "coverage_events.csv",
                    "onset_relations.csv",
                    "target_summary.csv",
                    "FAILURE_MODE_AUDIT_V1.md",
                },
                {path.name for path in output.iterdir()},
            )

            with (output / "coverage_context.csv").open(newline="", encoding="utf-8") as stream:
                context_rows = list(csv.DictReader(stream))
            self.assertEqual(len(WINDOW_LABELS) * len(EXPECTED_ALGORITHMS), len(context_rows))
            self.assertEqual(set(WINDOW_LABELS), {row["window_label"] for row in context_rows})

            with (output / "target_summary.csv").open(newline="", encoding="utf-8") as stream:
                target_rows = list(csv.DictReader(stream))
            self.assertEqual(set(TARGET_CASES), {(row["window_label"], row["algorithm_id"]) for row in target_rows})

            metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual("lio_benchmark_failure_mode_audit/v1", metadata["schema"])
            self.assertEqual("DESCRIPTIVE_NO_GROUND_TRUTH", metadata["scientific_status"])
            self.assertEqual(4, len(metadata["child_runs"]))
            self.assertGreaterEqual(len(metadata["evidence_files"]), 20)
            for evidence in metadata["evidence_files"]:
                self.assertEqual(64, len(evidence["sha256"]))
                self.assertEqual(
                    evidence["sha256"],
                    hashlib.sha256(Path(evidence["path"]).read_bytes()).hexdigest(),
                )

            report = (output / "FAILURE_MODE_AUDIT_V1.md").read_text(encoding="utf-8")
            self.assertIn("DESCRIPTIVE_NO_GROUND_TRUTH", report)
            self.assertIn("high_angular_motion / kiss_icp", report)
            self.assertIn("steady_translation_candidate / fast_livo2", report)
            self.assertNotIn("accuracy ranking", report.lower())

    @staticmethod
    def _write_child(root: Path, batch_id: str, window: str) -> None:
        run = root / f"{batch_id}_{window}"
        (run / "metrics/relative_se3").mkdir(parents=True, exist_ok=True)
        (run / "standardized/trajectories").mkdir(parents=True, exist_ok=True)
        (run / "manifest.json").write_text(
            json.dumps({"run_id": run.name, "algorithms": {algorithm: {} for algorithm in EXPECTED_ALGORITHMS}}) + "\n",
            encoding="utf-8",
        )

        coverage_fields = [
            "algorithm_id",
            "input_lidar_count",
            "input_lidar_effective_hz",
            "input_lidar_median_period_s",
            "input_lidar_p95_period_s",
            "input_lidar_max_period_s",
            "input_lidar_large_gap_count",
            "adapter_status",
            "adapter_output_count",
            "adapter_output_effective_hz",
            "adapter_output_median_period_s",
            "adapter_output_p95_period_s",
            "adapter_output_max_period_s",
            "adapter_output_large_gap_count",
            "trajectory_count",
            "trajectory_effective_hz",
            "trajectory_median_period_s",
            "trajectory_p95_period_s",
            "trajectory_max_period_s",
            "trajectory_large_gap_count",
            "first_trajectory_lag_from_input_s",
            "last_trajectory_delta_to_input_end_s",
            "trajectory_to_input_count_ratio",
            "adapter_to_input_count_ratio",
            "trajectory_to_adapter_count_ratio",
        ]
        with (run / "metrics/trajectory_coverage.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=coverage_fields)
            writer.writeheader()
            for algorithm in EXPECTED_ALGORITHMS:
                writer.writerow(
                    {
                        "algorithm_id": algorithm,
                        "input_lidar_count": 450,
                        "input_lidar_effective_hz": 10.0,
                        "input_lidar_median_period_s": 0.1,
                        "input_lidar_p95_period_s": 0.1,
                        "input_lidar_max_period_s": 0.11,
                        "input_lidar_large_gap_count": 0,
                        "adapter_status": "NOT_APPLICABLE",
                        "trajectory_count": 5,
                        "trajectory_effective_hz": 6.7,
                        "trajectory_median_period_s": 0.1,
                        "trajectory_p95_period_s": 0.3,
                        "trajectory_max_period_s": 0.3,
                        "trajectory_large_gap_count": 1,
                        "first_trajectory_lag_from_input_s": 0.0,
                        "last_trajectory_delta_to_input_end_s": -0.1,
                        "trajectory_to_input_count_ratio": 5 / 450,
                    }
                )

        base = float(WINDOW_LABELS.index(window) * 100)
        for algorithm in EXPECTED_ALGORITHMS:
            with (run / f"standardized/trajectories/{algorithm}.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=["timestamp_s", "x_m", "y_m", "z_m", "qx", "qy", "qz", "qw"],
                )
                writer.writeheader()
                for timestamp in (base, base + 0.1, base + 0.2, base + 0.5, base + 0.6):
                    writer.writerow(
                        {
                            "timestamp_s": timestamp,
                            "x_m": 0.0,
                            "y_m": 0.0,
                            "z_m": 0.0,
                            "qx": 0.0,
                            "qy": 0.0,
                            "qz": 0.0,
                            "qw": 1.0,
                        }
                    )

        (run / "metrics/relative_se3/metadata.json").write_text(
            json.dumps(
                {
                    "schema": "lio_benchmark_relative_se3/v1",
                    "ground_truth": "NONE",
                    "terminology": "PAIRWISE_DISAGREEMENT",
                    "sample_period_s": 0.1,
                    "sustain_samples": 3,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        onset_fields = [
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
        ]
        with (run / "metrics/relative_se3/onset_thresholds.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=onset_fields)
            writer.writeheader()
            writer.writerow(
                {
                    "left_algorithm_id": "fast_lio2",
                    "right_algorithm_id": "kiss_icp",
                    "metric": "xyz_m",
                    "threshold": 0.05,
                    "unit": "m",
                    "sustain_samples": 3,
                    "crossed": True,
                    "onset_timestamp_s": base + 0.4,
                    "onset_relative_time_s": 0.4,
                    "onset_value": 0.06,
                }
            )
            writer.writerow(
                {
                    "left_algorithm_id": "fast_lio2",
                    "right_algorithm_id": "fast_livo2",
                    "metric": "rotation_deg",
                    "threshold": 1.0,
                    "unit": "deg",
                    "sustain_samples": 3,
                    "crossed": True,
                    "onset_timestamp_s": base + 0.45,
                    "onset_relative_time_s": 0.45,
                    "onset_value": 1.2,
                }
            )


if __name__ == "__main__":
    unittest.main()
