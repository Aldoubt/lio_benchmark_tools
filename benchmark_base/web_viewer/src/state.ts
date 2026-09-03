export type ViewerLanguage = "zh-CN" | "en";
export type PointLod = "dense" | "medium" | "sparse";

export interface AnomalyWindow {
  window_id?: string;
  algorithm: string;
  start_bag_time_s: number;
  end_bag_time_s: number;
  event_count?: number;
  types?: string[];
  severity?: number;
  peak_position_step_m?: number;
  peak_yaw_step_deg?: number;
}

export interface ViewerConfig {
  grpcUrl: string;
  language: ViewerLanguage;
  algorithms: string[];
  baseline: string;
  worldAlgorithm: string;
  anomalyWindows: AnomalyWindow[];
}

export interface ViewerState {
  visibleAlgorithms: string[];
  worldAlgorithm: string;
  pointLod: PointLod;
  language: ViewerLanguage;
}

export type PartialViewerState = Partial<ViewerState>;

const VALID_LODS = new Set<PointLod>(["dense", "medium", "sparse"]);
const VALID_LANGUAGES = new Set<ViewerLanguage>(["zh-CN", "en"]);

export function anomalySeekNanoseconds(
  window: Pick<AnomalyWindow, "start_bag_time_s" | "end_bag_time_s">,
): number {
  const start = Number(window.start_bag_time_s);
  const end = Number(window.end_bag_time_s);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) {
    throw new Error("invalid anomaly window time range");
  }
  return Math.round(((start + end) * 0.5) * 1_000_000_000);
}

export function normalizeState(
  config: ViewerConfig,
  partial: PartialViewerState = {},
): ViewerState {
  if (!config.algorithms.includes(config.baseline)) {
    throw new Error(`baseline is not in algorithms: ${config.baseline}`);
  }
  const configuredWorld = config.algorithms.includes(config.worldAlgorithm)
    ? config.worldAlgorithm
    : config.baseline;

  const requestedVisible = partial.visibleAlgorithms ?? [...config.algorithms];
  const uniqueVisible = [...new Set(requestedVisible)].filter((algorithm) =>
    config.algorithms.includes(algorithm),
  );
  const visibleAlgorithms = uniqueVisible.length > 0
    ? uniqueVisible
    : [config.baseline];

  const requestedWorld = partial.worldAlgorithm ?? configuredWorld;
  const worldAlgorithm = config.algorithms.includes(requestedWorld)
    ? requestedWorld
    : configuredWorld;

  const pointLod = partial.pointLod && VALID_LODS.has(partial.pointLod)
    ? partial.pointLod
    : "medium";
  const requestedLanguage = partial.language ?? config.language;
  const language = VALID_LANGUAGES.has(requestedLanguage)
    ? requestedLanguage
    : config.language;

  return {visibleAlgorithms, worldAlgorithm, pointLod, language};
}
