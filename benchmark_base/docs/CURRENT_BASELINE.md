# 当前 MID360 基准状态

当前基准正在从历史 smoke 结果切换到 **Mid-360 factory-extrinsic closure 后的 fresh three-algorithm comparison**。

## 当前固定传感器合同

本数据集使用同一台 Livox Mid-360 的点云与内部 IMU，不把这组内部几何关系视为待重新估计的外接传感器标定。

统一记号：

```text
T_AB maps frame B coordinates into frame A
p_A = R_AB * p_B + t_AB
```

Mid-360 厂家内部几何证据单独记录为：

```text
^L p_I = [+0.011, +0.02329, -0.04412] m
axes aligned
```

benchmark canonical LiDAR→IMU transform 固定为：

```text
T_IL
p_I = R_IL * p_L + t_IL
R_IL = I
t_IL = [-0.011, -0.02329, +0.04412] m
```

其逆变换为：

```text
T_LI = inverse(T_IL)
t_LI = [+0.011, +0.02329, -0.04412] m
```

Calibration provenance：

```text
status      = MANUFACTURER_SPEC
source_type = MANUFACTURER_SPEC
sensor      = Livox Mid-360
imu_relation = INTERNAL_IMU
online extrinsic estimation = false
```

FAST-LIO2 和 FAST-LIVO2 都直接消费固定 `T_IL`；KISS-ICP 运行时保持 LiDAR-only，在需要统一到 `IMU_BODY` 的 Relative SE(3) 中使用 `T_LI = inverse(T_IL)`。

## 已完成工程合同

当前三算法主比较链已经具备：

```text
runtime identity / provenance
trajectory-from-run
frame contract audit
trajectory coverage diagnostics
strict common matched scan intersection
strict Unified Map reconstruction
Relative SE(3) pairwise disagreement
factory Mid-360 internal extrinsic provenance
run-local effective FAST-LIO2 / FAST-LIVO2 configs
diagnostic bundle with generated calibration/config evidence
```

## 历史结果边界

此前 frozen run 和 bundle 保留为历史证据，不修改、不覆盖、不重新解释。

尤其是 factory-extrinsic closure 之前使用旧正号 canonical `LIDAR_TO_IMU` 含义生成的：

```text
KISS <-> LIO Relative SE(3)
Unified Maps using IMU_BODY conversion
```

不能作为后续正式数值比较的基准。它们仍可用于证明当时的 runner / provenance / pipeline 行为。

## 下一轮正式基线

必须创建一个 **fresh run**，重新执行：

```text
FAST-LIVO2
FAST-LIO2
KISS-ICP
```

并要求：

```text
preflight without --allow-diagnostic-calibration
MANUFACTURER_SPEC frozen in manifest
FAST-LIVO2 effective T_IL = [-0.011,-0.02329,+0.04412]
FAST-LIO2 effective T_IL = [-0.011,-0.02329,+0.04412]
strict common scan population identical for all maps
Relative SE(3) target frame = IMU_BODY
ground truth = NONE
terminology = PAIRWISE_DISAGREEMENT
```

这轮成功后，新的结果成为当前统一对比基线。

## 科学边界

厂家规格外参闭环后，`BLOCKED_CALIBRATION` 不再是当前 Mid-360 数据集的 blocker。

但当前仍没有 ground-truth trajectory，因此：

允许：

```text
descriptive trajectory comparison
pairwise disagreement
strict-common-scan map comparison
runtime / coverage / robustness comparison
```

禁止在没有独立真值时写成：

```text
ATE/RPE truth error
accuracy ranking
某算法客观上“更准”
```

新数据集复用时仍必须独立冻结其传感器身份、外参来源、方向约定和 calibration status，不能把 Mid-360 factory specification 泛化到其它 LiDAR/IMU 组合。
