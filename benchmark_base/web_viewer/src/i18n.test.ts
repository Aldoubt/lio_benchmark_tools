import {expect, test} from "vitest";
import {anomalyTypeLabel, t} from "./i18n";

test("chinese viewer labels are repository owned", () => {
  expect(t("zh-CN", "view.map_trajectories")).toBe("地图与轨迹");
  expect(t("zh-CN", "view.anomaly_windows")).toBe("异常时间窗口");
  expect(anomalyTypeLabel("zh-CN", "position_jump")).toBe("位置突变");
});

test("english viewer labels remain available", () => {
  expect(t("en", "view.map_trajectories")).toBe("Map + trajectories");
  expect(t("en", "view.anomaly_windows")).toBe("Anomaly windows");
  expect(anomalyTypeLabel("en", "position_jump")).toBe("Position jump");
});
