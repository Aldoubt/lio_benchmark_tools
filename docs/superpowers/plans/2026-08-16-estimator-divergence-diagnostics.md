# Estimator Divergence Diagnostics Implementation Plan

**Goal:** Turn the first real FAST-LIVO2 / FAST-LIO2 / KISS-ICP smoke result into a reusable descriptive diagnostics layer that explains when and how estimators diverge before expanding the baseline count.

**Scope:** This plan adds trajectory diagnostics, pairwise disagreement summaries, warmup-aware views, and report figures. It does not add ground-truth accuracy claims, does not change standardized trajectories/maps, and does not add new algorithm adapters.

## Scientific boundary

- No ground truth is assumed.
- Pairwise quantities are named `disagreement`, never `error` or `accuracy`.
- `START_XY_YAW` may be used only as an explicitly recorded comparison/display transform.
- Z, roll, pitch, later drift, scale and non-rigid distortion are never fitted away.
- Initialization data remains in the raw/full diagnostics. A configurable `warmup_s` may additionally produce post-warmup summaries; it never deletes original samples.
- Existing `standardized/trajectories/*.csv`, Native Maps and Unified Maps are read-only inputs.

## Outputs

Under a run directory:

```text
metrics/
  smoke_diagnostics.csv
  pairwise_disagreement.csv
figures/
  trajectory_z_vs_time.png
  trajectory_roll_vs_time.png
  trajectory_pitch_vs_time.png
  trajectory_yaw_relative_vs_time.png
  pairwise_xy_disagreement.png
  pairwise_z_disagreement.png
```

`smoke_diagnostics.csv` records descriptive per-algorithm fields such as sample count, duration, path length, delta XYZ, Z/roll/pitch ranges, yaw change, map points, scan matching and calibration/run status.

`pairwise_disagreement.csv` records the alignment mode, overlap interval, common sample count and descriptive XY/Z/3D disagreement statistics for every available trajectory pair.

## Task 1 — Pure diagnostics contracts

Create `reporting/diagnostics.py` and tests in `benchmark_base/tests/test_diagnostics.py`.

Required behavior:

1. Per-trajectory summary uses strictly the standardized trajectory contract.
2. Warmup is relative to each trajectory start and must fail if it removes all usable samples.
3. Pairwise comparison uses the common time overlap and timestamp interpolation, never index matching.
4. Pairwise comparison supports `NONE` and `START_XY_YAW` only.
5. `START_XY_YAW` is applied independently from each trajectory initial pose and preserves Z.
6. Angle differences are wrap-safe.

## Task 2 — CSV writers and run-level collection

Add run-level helpers that:

- collect per-algorithm diagnostics for all valid standardized trajectories;
- preserve MISSING/INVALID states rather than writing zero;
- merge map matching/runtime/calibration status from existing run artifacts when available;
- generate all unique algorithm pairs deterministically.

## Task 3 — Report figures

Extend `reporting/generate_report.py` with:

- Z vs relative time;
- roll vs relative time;
- pitch vs relative time;
- relative yaw vs time;
- pairwise XY disagreement vs common relative time;
- pairwise absolute Z disagreement vs common relative time.

All figures must include the selected display alignment / warmup in their title or metadata where relevant.

## Task 4 — CLI

Extend:

```bash
lio-benchmark report --run <run> --warmup-s <seconds>
```

Default `warmup_s=0.0` so historical behavior is unchanged.

## Task 5 — Verification

Run the full existing contract suite plus new diagnostics tests:

```bash
python3 -m unittest benchmark_base.tests.test_diagnostics -v
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
for f in evaluators/*.sh; do bash -n "$f"; done
```

Then use the existing green-house three-algorithm smoke run on the real machine to regenerate the report. The framework is considered contract-complete when CI is green; the real diagnostic interpretation remains a separate machine/data verification step.
