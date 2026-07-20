# 故障排查

- `doctor` 报路径错误：只修改 manifest 中的 workspace/source/setup/config，不改 runner。
- MOLA 报 `name 'false' is not defined`：参与 PythonExpression 的 launch 参数必须使用 `True/False`；统一 runner 已处理。
- MOLA 关闭时报 `Resource deadlock avoided`：避免 timeout 和人工操作重复发送 SIGINT；保留日志并按 shutdown defect 分类，不能当作运行期轨迹成功证据。
- FAST-LIVO2 报缺少 `camera.model`：该 fork 即使 `img_en=0` 也构造相机；当前配置包含仅用于启动的参数，不会订阅图像。
- GLIM 加载 GPU 模块失败：确认 materialized config 指向 `*_cpu.json`，并加载 gtsam_points/GTSAM prefix。
- LIO-SAM 无轨迹或崩溃：先查 adapter 的 ring/time 统计；不要虚构 ring，必要时标记 `BLOCKED_INPUT_MODEL`。
- 出现旧机器人话题：确认 runner 的 `ROS_DOMAIN_ID` 未被覆盖。
