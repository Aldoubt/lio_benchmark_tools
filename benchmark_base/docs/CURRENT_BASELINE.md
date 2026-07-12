# 当前 MID360 基准样例

现有 `date/` 实验是本工具基座的首个参考样例，并未强制迁移到 `runs/`，以免复制约 2 GiB bag 和历史输出。

## 已完成结果

- 数据质量：`date/output/bag_analysis.json`
- FAST-LIVO2：`date/output/trajectory_statistics.json`
- Point-LIO：`date/output/point_lio/results/point_lio_trajectory_statistics.json`
- GLIM odometry：`date/output/glim_odometry/results/glim_odometry_trajectory_statistics.json`
- GLIM full SLAM：`date/output/glim_full_slam/REPORT.md`
- DLIO：`date/output/dlio_final/results/dlio_10hz_trajectory_statistics.json`
- 四前端地图/轨迹：`date/output/frontend_visual_comparison/REPORT.md`

## 基线结论

- Point-LIO 和 FAST-LIVO2 的统一重建地图整体最稳定。
- GLIM odometry 存在明显的长期 Z 趋势；本数据中全局优化未显著修正。
- DLIO 首尾 Z 差小，但中途 Z 极差最大。
- 当前没有可靠旧区域回环证据，也没有真值轨迹。

## 新数据集复用

1. 复制 `config/experiment.template.json`。
2. 填入 bag、话题、IMU 单位和外参来源。
3. 执行 `validate` 和 `init`。
4. 只在新 run 目录写输出。
5. 算法源代码修改必须单独记录 patch、原因、风险和回滚方法。

