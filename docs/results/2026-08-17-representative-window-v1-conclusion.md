# Representative Benchmark V1 — Frozen Conclusion

Date: 2026-08-17
Branch: `feat/lio-baseline-suite`

## Scientific status

```text
DESCRIPTIVE_NO_GROUND_TRUTH
```

This document freezes the accepted Representative Window V1 and Failure-Mode Audit V1 results before the repository moves to Same-Bag Mapping Benchmark V1. It is a stage conclusion, not a new metric or a reinterpretation of accepted artifacts.

## Representative Window V1 — FINAL acceptance

Accepted target-machine evidence:

```text
Representative Window V1 FINAL acceptance = PASS
windows = 4
a lgorithms per window = 3
fresh estimator runs = 12 / 12 runtime PASS
timestamp regression = 0
frame contract = all MATCH
runtime provenance = all MATCH
strict common-map = 4 / 4 PASS
Relative SE(3) = 3 pairwise comparisons in each of 4 windows
trajectory immutability = PASS
final package = generated
```

The four frozen representative windows are:

```text
initialization
high_angular_motion
geometric_degeneracy_candidate
steady_translation_candidate
```

The final portable package excludes raw estimator bags and large point-cloud payloads, including:

```text
raw/
*.db3
*.mcap
*.ply
*.pcd
```

### What this establishes

Representative Window V1 establishes that the accepted three-algorithm benchmark execution/standardization/audit/common-map chain can be exercised reproducibly on fixed raw-sensor windows from the same greenhouse MID360 bag.

It supports using the representative suite as the development/adapter gate before an expensive full-bag run.

### What this does not establish

It does not establish:

- ground-truth trajectory accuracy
- ground-truth map accuracy
- objective estimator ranking
- causal failure labels
- universal performance on other bags or environments

## Failure-Mode Audit V1 — FINAL acceptance

Accepted machine contract:

```text
FAILURE_MODE_AUDIT_V1_TARGET_CONTRACT=PASS
```

### high_angular_motion / kiss_icp

```text
first coverage degradation = 1767659802.2546015
first sustained Relative SE(3) onset = 1767659801.8461776
divergence minus coverage = -0.4084239 s
temporal order = DESCRIPTIVE_DIVERGENCE_FIRST
```

### steady_translation_candidate / fast_livo2

```text
first coverage degradation = 1767660082.330995
first sustained Relative SE(3) onset = 1767660081.9209733
divergence minus coverage = -0.4100218 s
temporal order = DESCRIPTIVE_DIVERGENCE_FIRST
```

In both audited focus cases the sustained pairwise Relative SE(3) descriptive disagreement onset occurred approximately 0.41 s before the first detected input-relative temporal coverage degradation under the frozen V1 definitions.

This temporal ordering is descriptive only. It does **not** demonstrate that disagreement caused later coverage degradation, that coverage degradation caused estimator drift, or that either estimator was inaccurate at that timestamp.

## Frozen development interpretation

The accepted result is sufficient to close the local representative-window diagnostic phase. The next benchmark question is different:

> Given one complete frozen MID360 bag, what trajectories, Native Maps when naturally provided, strict Unified Maps, and single-run resource costs do the accepted baseline adapters produce under one auditable comparison contract?

That question is handled by `Same-Bag Mapping Benchmark V1`.

## Development gate going forward

For new baseline adapters, the intended progression is:

```text
adapter implementation
        |
        v
Representative Window V1-compatible acceptance
        |
        v
full-bag Same-Bag Mapping Benchmark
```

The current Same-Bag Mapping Benchmark V1 full-bag gate intentionally contains only:

```text
fast_livo2
fast_lio2
kiss_icp
```

Point-LIO, DLIO, LIO-SAM, Leg-KILO, GLIM, Faster-LIO and SLICT are not added until this three-algorithm full-bag chain is accepted.
