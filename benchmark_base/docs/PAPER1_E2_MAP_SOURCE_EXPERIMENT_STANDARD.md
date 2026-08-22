# Paper I E2 — Mapping-Source Robustness Experiment Standard

## Status

**EXECUTION STANDARD v1 / READY TO START IN PARALLEL WITH E1**

本文件定义 Paper I 的 B 组（E2）实验目标、方法边界、输入输出、对齐规则、指标、证据目录和验收门槛。

本实验的任务不是继续开发新的 LIO 算法，而是把已经能够产生可用温室全局地图的方案冻结为 Paper I 可引用的科研证据。

---

# 1. Scientific Goal

E2 回答：

> 当全局点云由不同但合理的建图来源产生时，Paper I 的 row / aisle / traversability 结构化地图输出是否保持稳定？

E2 不试图证明某一个 SLAM / LIO 算法在所有指标上“最好”。

核心论证链：

```text
Different mapping source
  -> different local density / noise / edge completeness
  -> same Paper I semantic-map pipeline
  -> compare row / aisle / traversability structure
```

---

# 2. Candidate Map Sources

Paper I E2 第一版仅考虑已经有真实可用结果的来源：

1. `FAST-LIVO2 LIO-only`
2. `Kilo-Map`
3. `Handheld scanner + FAST-LIO`

方法 ID 必须使用实际仓库/实验中的固定名称；如果 `Kilo-Map` 的正式实现名称不同，在冻结 manifest 时记录 canonical implementation name、repository、commit 和 Paper-facing alias。

不因为 Paper I 临时增加第四、第五种 LIO 方法。

---

# 3. E2 Is Split into B1 and B2

## B1 — Same-input mapping benchmark

B1 只允许比较**真正共享可比输入条件**的方法。

必须尽可能共享：

- same ROS bag / raw dataset；
- same LiDAR / IMU source；
- same time window；
- same calibration；
- same timestamp interpretation；
- same trajectory reference / ground truth definition；
- same evaluation coordinate convention。

在满足这些条件时，可比较：

- APE；
- RPE；
- final drift / closure consistency；
- successful trajectory duration；
- map physical extent / completeness；
- runtime；
- CPU / memory（仅当采样方法一致）。

### B1 hard rule

如果某方法使用不同采集设备、不同轨迹、不同 reference，则不得把 APE/RPE 数字直接放在同一 ranking 表中。

因此手持扫描仪通常属于 B2 map-source comparison，而不是 B1 trajectory ranking。

---

## B2 — Cross-map-source downstream robustness

B2 是 Paper I RQ2 的主要证据。

将每一个冻结 global map 经过：

```text
Frozen map source
  -> explicit rigid alignment / common ROI
  -> same Paper I pipeline commit
  -> same algorithm policy
  -> same metric definitions
  -> structural comparison
```

重点比较最终农业结构，而不是要求原始点云逐点一致。

---

# 4. Required Source Identity

每一个纳入 E2 的 map source 必须记录：

```yaml
method_id: ...
implementation:
  repository: ...
  commit: ...
  branch_or_tag: ...
dataset:
  id: ...
  source_type: rosbag2 | scanner_dataset | other
  source_sha256: ...
  start_time: ...
  end_time: ...
calibration:
  id: ...
  sha256: ...
configuration:
  path: ...
  sha256: ...
output_map:
  path_or_artifact_id: ...
  sha256: ...
  frame_id: ...
  point_count: ...
  bounds_xyz_m: ...
```

未知字段必须写 `null` / `unavailable` 并说明原因，禁止补猜。

---

# 5. Alignment Standard for B2

不同建图来源通常具有不同 map origin / orientation，因此 B2 允许进行明确记录的**刚性对齐**。

允许：

- SE(3) rigid transform；
- 对最终二维结构评估使用由已记录 3D alignment 投影得到的 SE(2) relation；
- 基于固定设施、人工确认对应点或可信 registration 方法得到 alignment。

禁止：

- non-rigid warp；
- 局部拉伸；
- 为了提高 IoU 对某一张地图单独手工变形；
- 未记录的 scale correction。

### Metric-scale rule

LiDAR / scanner 地图原则上应是 metric scale。

如果需要显著 scale correction 才能重合：

- 不得静默修正；
- 将其记录为 map-source failure / scale inconsistency；
- 如需研究 scale-aligned variant，应作为附加分析，不替代原始结果。

每个 alignment 必须输出：

```yaml
schema: agt_paper1_map_alignment/v1
source_map_sha256: ...
reference_map_sha256: ...
method: ...
transform_4x4: [...]
scale: 1.0
correspondence_or_registration_evidence: ...
```

---

# 6. Common ROI Rule

B2 必须冻结共同的 `comparison_roi`。

目的：避免一张地图覆盖更多区域而另一张地图未扫描该区域时，把“未采集”误算为结构识别失败。

共同 ROI 应：

- 位于三种来源均有有效覆盖的温室区域；
- 包含多个 row / aisle，而不是只选一个最容易的局部；
- 覆盖至少一个明显 vegetation occlusion 区域；
- 在运行 Paper I pipeline 前冻结；
- 写入 polygon / bounds 文件并 hash。

如果只能找到两种来源共同覆盖的完整 ROI，应明确使用 pairwise ROI，并在论文中说明。

---

# 7. Same-Pipeline Rule

所有 B2 map source 必须使用：

- 同一 `agt_navigation_v2` Paper I pipeline commit；
- 同一 semantic/traversability schema；
- 同一 default parameter policy；
- 同一 grid policy / comparison resolution；
- 同一 Site Boundary policy；
- 同一 metric script version。

### Parameter rule

首轮 B2 不允许针对每一个 map source 单独调出“最佳参数”。

如果一个统一参数组无法工作，必须首先记录失败。

后续可以增加 sensitivity analysis，但不能用 per-source tuning 替代统一参数的主结果。

---

# 8. B1 Metrics

仅对满足同输入条件的方法计算。

至少记录：

## Trajectory

- APE RMSE；
- APE median / P95；
- RPE translation；
- RPE rotation；
- final position / closure error（若定义合理）。

## Map output

- total valid trajectory duration；
- map point count；
- physical XYZ bounds；
- gross map completeness / usable extent；
- catastrophic map failure flag。

## Runtime

仅当采样方式一致时报告：

- total processing time；
- real-time factor；
- CPU；
- RSS / peak memory。

不一致的 runtime instrumentation 必须分表，不做直接 ranking。

---

# 9. B2 Primary Structural Metrics

B2 主要指标：

## 9.1 Row dominant direction deviation

比较各 map source 输出的主 row orientation。

报告：

- absolute deviation in degrees；
- median / max where multiple row groups exist。

## 9.2 Row spacing deviation

对于能够建立对应关系的相邻 row：

- absolute spacing difference；
- normalized spacing difference。

## 9.3 Row topology agreement

比较：

- detected row count；
- missing row；
- merged row；
- split row；
- adjacency consistency。

不仅报告一个 aggregate score，也保留错误类型。

## 9.4 Aisle centerline deviation

在对应 aisle 上计算中心线距离，例如：

- median lateral deviation；
- P95 lateral deviation；
- maximum deviation。

必须记录 centerline correspondence 规则。

## 9.5 Aisle topology agreement

比较：

- aisle count；
- connectivity；
- branch / endpoint relationship；
- missing / false aisle。

## 9.6 Traversable-area agreement

使用统一 comparison grid，在 common ROI 内比较：

- traversable IoU between sources；
- agreement ratio；
- disagreement area；
- UNKNOWN disagreement。

这不是 Ground Truth accuracy，而是 cross-source consistency。

## 9.7 Connectedness

记录：

- largest connected traversable component；
- reachable aisle count；
- disconnected aisle count。

---

# 10. Reference Source Policy

B2 不强制把某一种 map source 称为“绝对真值”。

建议角色：

- 手持三维扫描地图可作为高质量几何参考来源之一；
- 人工 reference /现场证据继续作为 traversability correctness 的独立依据；
- FAST-LIVO2 / Kilo-Map 作为机器人在线/离线建图来源。

如果论文中将某 map source 称为 reference map，必须解释其精度来源和限制。

---

# 11. Required Evidence Directory

正式输出建议：

```text
paper1_evidence/greenhouse_map_sources_v01/
├── evidence_manifest.yaml
├── comparison_roi.yaml
├── alignments/
│   ├── fastlivo2_to_reference.yaml
│   ├── kilomap_to_reference.yaml
│   └── handheld_to_reference.yaml
├── B1_same_input/
│   ├── summary.csv
│   ├── summary.md
│   └── figures/
├── B2_structural_consistency/
│   ├── summary.csv
│   ├── summary.md
│   ├── row_metrics.csv
│   ├── aisle_metrics.csv
│   ├── traversability_metrics.csv
│   └── figures/
├── maps/
│   ├── fastlivo2_lio_only.yaml
│   ├── kilo_map.yaml
│   └── handheld_fastlio.yaml
└── failure_cases.yaml
```

大体积 PCD 不进入 Git；metadata / manifest / metrics / figures 可以进入 Git。

---

# 12. `evidence_manifest.yaml` Minimum Contract

```yaml
schema: agt_lio_paper1_evidence/v1
snapshot_id: greenhouse_map_sources_v01
repository_commit: <lio_benchmark_tools commit>
paper1_pipeline_commit: <agt_navigation_v2 commit>
comparison_roi_sha256: <sha>
methods:
  - id: fastlivo2_lio_only
    map_sha256: <sha>
    config_sha256: <sha>
    dataset_sha256: <sha>
    b1_eligible: true
  - id: kilo_map
    map_sha256: <sha>
    config_sha256: <sha>
    dataset_sha256: <sha>
    b1_eligible: true_or_false
  - id: handheld_fastlio
    map_sha256: <sha>
    config_sha256: <sha>
    dataset_sha256: <sha>
    b1_eligible: false
```

所有 `true_or_false` 在正式文件中必须变成实际布尔值，并附 eligibility reason。

---

# 13. Required Figures

至少输出：

## Fig. B1 — Trajectory comparison

仅包含 B1 eligible 方法。

## Fig. B2 — Global map overview

三种 map source 使用相同 viewpoint / common ROI 可视化。

## Fig. B3 — Row / aisle overlay

在 common ROI 中叠加对应 row centerline / aisle centerline。

## Fig. B4 — Traversability agreement map

显示：

- agreement；
- source-specific traversable；
- source-specific UNKNOWN；
- structural disagreement regions。

## Fig. B5 — Failure cases

至少展示一个 map-source 差异真正影响 downstream structure 的区域。

---

# 14. Experimental Validity Gate

这里的 PASS 只表示实验**有效且可用于论文**，不表示算法结果必须漂亮。

B 实验达到 `E2_EVIDENCE_FROZEN` 必须满足：

- [ ] 所有纳入方法都有 repository + commit identity；
- [ ] 所有纳入 map 都有 SHA256；
- [ ] config / dataset identity 可追溯；
- [ ] B1 只包含满足同输入条件的方法；
- [ ] handheld / non-common trajectory 没有被错误放入 APE/RPE ranking；
- [ ] B2 rigid alignment 全部有显式 transform 文件；
- [ ] 不存在未记录的 scale / non-rigid correction；
- [ ] common ROI 已在看结果前冻结；
- [ ] 三种 map source 使用同一 Paper I pipeline commit；
- [ ] 主结果没有 per-source hand tuning；
- [ ] row / aisle / traversability 主指标全部自动生成；
- [ ] failure cases 有记录；
- [ ] evidence_manifest.yaml 完整；
- [ ] summary.csv / figures 可从记录的输入重新生成；
- [ ] Git 中没有提交 multi-GB PCD；
- [ ] `agt_navigation_v2` 可以通过 repo commit + manifest SHA 引用该 snapshot。

---

# 15. Scientific Success Is Not a Gate

不要预先规定“只有 deviation < 某个数才允许发表”。

正式结果可能出现三种情况：

### Outcome A — High consistency

不同 map source 的农业结构和 traversability 输出高度一致。

支持：方法具有较好的 map-source robustness。

### Outcome B — Topology stable, local geometry differs

row / aisle topology 一致，但 centerline / boundary 有局部偏差。

支持：方法对全局结构稳定，但精细几何仍依赖 map quality。

### Outcome C — Significant downstream inconsistency

某一种 map source 导致 row / aisle / traversability 明显错误。

这不是实验失败；它定义了 Paper I 方法对上游全局地图质量的适用边界。

三种 outcome 都必须保留原始证据，不允许为了得到 Outcome A 修改数据或排除失败来源。

---

# 16. Stop Rule

一旦 `greenhouse_map_sources_v01` 达到 `E2_EVIDENCE_FROZEN`：

停止为 Paper I 增加新的 LIO / SLAM 方法。

后续新的建图算法比较进入：

- 独立 `lio_benchmark_tools` 研究；或
- Paper II / future work。

Paper I 只引用冻结 snapshot。

---

# 17. Immediate B Execution Checklist

现在按顺序执行：

```text
B0  保存并提交本机 lio_benchmark_tools 未同步改动
B1  列出历史有效 runs
B2  判断各 run 的 B1 eligibility
B3  锁定 FAST-LIVO2 / Kilo-Map / handheld 三张 map
B4  计算 map/config/dataset SHA256
B5  固定 common ROI
B6  生成 rigid alignments
B7  输出 B1 summary（仅 eligible）
B8  三张 map 输入同一 Paper I pipeline
B9  输出 B2 row / aisle / traversability metrics
B10  生成 figures + failure_cases
B11  写 evidence_manifest.yaml
B12  标记 E2_EVIDENCE_FROZEN
```

V3 runtime 在 B12 和 E1 主实验冻结之后再启动。
