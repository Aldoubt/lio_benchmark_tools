# Same-Bag Mapping Benchmark V1 Design

## Status

APPROVED BASELINE — implementation may proceed on `feat/lio-baseline-suite`.

## Goal

Turn the existing three-algorithm green-house MID360 acceptance chain into one reproducible full-bag mapping benchmark that can later be extended by adapters without changing the comparison contract.

V1 stops at the target-machine gate where Codex must replay the existing 622.99 s bag. Repository-side implementation and tests must be complete before that gate.

## Frozen predecessor evidence

Representative Window V1 is accepted: 4 windows × 3 algorithms = 12/12 runtime PASS, zero timestamp regressions, frame contracts MATCH, runtime provenance MATCH, strict common-map 4/4 PASS, trajectory immutability PASS, and the final diagnostic package excludes raw bags and point-cloud payloads.

Failure-Mode Audit V1 is accepted with `FAILURE_MODE_AUDIT_V1_TARGET_CONTRACT=PASS`. Both audited focus cases were `DESCRIPTIVE_DIVERGENCE_FIRST`; this remains descriptive, no-ground-truth evidence and is not promoted into a causal or accuracy claim.

These predecessor artifacts are frozen. This feature does not modify Representative Window V1, Failure-Mode Audit V1, their thresholds, or their child runs.

## V1 algorithms

Only these already target-accepted runtime paths are in the first full-bag gate:

- `fast_livo2`
- `fast_lio2`
- `kiss_icp`

Point-LIO, DLIO, LIO-SAM, Leg-KILO, GLIM, Faster-LIO and SLICT remain registered future adapters but are outside V1 implementation and target-machine execution.

## Fairness contract

### Same dataset and interval

All three algorithms consume the same frozen `green_house_mid360` dataset and the full replay interval:

- replay rate: `1.0`
- start offset: `0.0 s`
- duration: `622.99 s`

The existing frozen dataset identity, topics, bag path/hash evidence, canonical MID360 calibration and algorithm-specific extrinsic conversion rules are reused unchanged.

### Sequential execution

Algorithms are executed sequentially by the existing runner. V1 does not run estimators concurrently. Resource measurements therefore describe one estimator run at a time and are not contaminated by deliberate multi-baseline contention.

### DEFAULT_ADAPTED profile

V1 formalizes the current adapter behavior as `DEFAULT_ADAPTED`:

Allowed changes are only the compatibility changes needed to make the frozen dataset consumable and auditable, including topic names, message conversion, frame/config wiring, LiDAR model, canonical extrinsic convention conversion, output paths and ROS execution wiring.

V1 must not tune algorithmic thresholds, voxel/feature/optimizer parameters or backend behavior merely to improve the green-house result. A future `GREENHOUSE_TUNED` profile, if created, must be a separate experiment identity.

### Sensor modality transparency

The report must preserve effective modalities:

- FAST-LIVO2: LiDAR + IMU for this profile; camera is not silently claimed
- FAST-LIO2: LiDAR + IMU
- KISS-ICP: LiDAR-only control

No single overall accuracy ranking is produced from heterogeneous modality roles.

## Map comparison contract

### Native Map

Native Map means the upstream/runtime algorithm's own map artifact when it is naturally produced under the frozen run profile.

V1 must not enable an optional native-map mode solely to make the comparison table look complete if that mode changes runtime cost. Missing native map is reported explicitly as `NOT_PROVIDED` / missing artifact.

### Unified Map

Unified Map remains the formal visual comparison surface:

1. same original LiDAR bag
2. same strict common matched-scan manifest
3. same canonical calibration
4. each algorithm's immutable standardized trajectory
5. same point sampling, near-range filter and voxel reconstruction rules

The existing strict common-intersection reconstruction remains authoritative. V1 does not weaken it.

### Map-quality language

Without external ground truth, V1 must not output a field called `map_accuracy` or a single accuracy score. It reports artifact/descriptive fields only: native map availability, unified map point count, strict matched scan count/ratio, trajectory coverage evidence and visual comparison artifacts.

## Runtime performance contract

Every estimator execution writes one immutable resource record:

`metrics/runtime/<algorithm>.json`

Schema: `lio_benchmark_runtime_performance/v1`.

Required fields:

- `algorithm_id`
- `measurement_method`
- `started_at`
- `finished_at`
- `wall_time_s`
- `cpu_user_s`
- `cpu_system_s`
- `cpu_total_s`
- `max_rss_kib`
- `returncode`
- `status`

V1 uses the repository process itself to measure the launched runner and its descendants. It must not add a third-party Python dependency merely for metrics. If a platform cannot provide a metric, the value is `null` and the method/limitation is explicit; a missing metric must never become zero.

The performance record is descriptive single-run evidence. V1 does not claim statistical stability and does not add repeated full-bag runs.

## Algorithm I/O inventory

After a run has artifacts, a read-only summarizer generates:

- `reports/algorithm_io_matrix.csv`
- `reports/algorithm_io_matrix.md`
- `metrics/runtime_performance.csv`
- `reports/same_bag_mapping_v1.json`

It consumes the frozen run manifest, per-algorithm runtime identity, run status/resource record, standardized trajectory, Native/Unified Map metadata and existing coverage/common-map evidence.

Each algorithm row records at least:

- algorithm id/display name/role
- required/effective sensor modalities
- input topics
- trajectory/native-map/registered-cloud output declarations
- runtime resolution/executable identity when available
- trajectory artifact status
- native map artifact status
- unified map artifact status and point count
- wall/CPU/RSS metrics when available
- run status

Unknown or not-yet-produced values are represented as `UNKNOWN`, `NOT_PROVIDED`, `MISSING` or null according to meaning, never fabricated.

The summarizer is read-only with respect to estimator, trajectory and map evidence. It may create only its own report/summary files and must refuse silent semantic invention.

## CLI surface

Add one additive post-run command:

```bash
benchmark_base/bin/lio-benchmark summarize same-bag --run /path/to/run
```

Existing commands remain authoritative for estimator execution and map generation. V1 does not add a second hidden supervisor.

The target-machine full-bag workflow is therefore explicit:

```text
validate -> init -> snapshot -> preflight
        -> run fast_livo2
        -> run fast_lio2
        -> run kiss_icp
        -> standardize trajectories
        -> trajectory/frame/provenance audits
        -> strict common-map manifest
        -> Unified Maps
        -> summarize same-bag
        -> inspect/report/demo
```

Repository implementation stops before the first full-bag `run` is executed in this session.

## Full-bag experiment manifest

Add `benchmark_base/config/green_house_three_full_bag_v1.json` by preserving the already accepted runtime executable/overlay and standardization settings from `green_house_three_runtime_smoke.json`, changing only experiment identity and replay duration from 15 s to 622.99 s, plus an explicit benchmark profile label if the manifest schema permits passthrough metadata without changing runtime semantics.

No new machine paths are guessed.

## Acceptance gates

### Repository gate

Must pass without ROS bag replay:

- new unit tests for runtime performance serialization/measurement behavior
- new unit tests for same-bag summary generation from synthetic frozen-run artifacts
- new CLI contract tests
- manifest/config contract tests
- entire `benchmark_base/tests` suite
- Python compile checks
- shell adapter syntax checks
- registry smoke

### Target-machine gate

The repository phase ends when a Codex prompt can safely run one new immutable full-bag run using `green_house_three_full_bag_v1.json`.

Codex must then perform the existing execution/standardization/audit/common-map chain and return the generated I/O/performance/map summary. It must not overwrite Representative Window V1 or Failure-Mode Audit V1 artifacts.

## Non-goals

V1 does not:

- add new SLAM algorithms
- tune algorithms for the greenhouse
- rerun or reinterpret Failure-Mode Audit V1
- create a ground-truth accuracy ranking
- force optional native-map publication if it changes runtime semantics
- introduce GPU benchmarking
- add statistical repeated full-bag trials
- hide ROS processes in a new supervisor
- modify the source bag or previously accepted run artifacts
