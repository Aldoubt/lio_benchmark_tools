import {expect, test} from "vitest";
import {
  anomalySeekNanoseconds,
  normalizeState,
  type ViewerConfig,
} from "./state";

const config: ViewerConfig = {
  grpcUrl: "rerun+http://127.0.0.1:9876/proxy",
  language: "zh-CN",
  algorithms: ["fast_livo2", "glim_full_slam"],
  baseline: "fast_livo2",
  worldAlgorithm: "fast_livo2",
  anomalyWindows: [],
};

test("anomaly midpoint becomes rerun nanoseconds", () => {
  expect(
    anomalySeekNanoseconds({
      start_bag_time_s: 353.0,
      end_bag_time_s: 354.0,
    }),
  ).toBe(353500000000);
});

test("empty algorithm selection is normalized to baseline", () => {
  expect(normalizeState(config, {visibleAlgorithms: []}).visibleAlgorithms).toEqual([
    "fast_livo2",
  ]);
});

test("unknown world algorithm falls back to configured algorithm", () => {
  expect(normalizeState(config, {worldAlgorithm: "unknown"}).worldAlgorithm).toBe(
    "fast_livo2",
  );
});
