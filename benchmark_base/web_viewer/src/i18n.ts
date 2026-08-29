import type {ViewerLanguage} from "./state";

const TRANSLATIONS: Record<ViewerLanguage, Record<string, string>> = {
  "zh-CN": {
    "app.title": "LIO 离线诊断",
    "control.algorithms": "算法显示",
    "control.world_algorithm": "世界点云算法",
    "control.point_lod": "点云密度",
    "control.language": "语言",
    "view.map_trajectories": "地图与轨迹",
    "view.raw_lidar": "当前原始激光点云",
    "view.world_lidar": "世界坐标点云",
    "view.anomaly_windows": "异常时间窗口",
    "anomaly.position_jump": "位置突变",
    "anomaly.yaw_jump": "航向突变",
    "lod.dense": "稠密",
    "lod.medium": "中等",
    "lod.sparse": "稀疏",
    "state.connecting": "正在连接实验记录…",
    "state.ready": "已连接",
    "state.no_recording": "当前没有活动的 Rerun 记录",
  },
  en: {
    "app.title": "LIO Offline Diagnostics",
    "control.algorithms": "Algorithms",
    "control.world_algorithm": "World LiDAR algorithm",
    "control.point_lod": "Point density",
    "control.language": "Language",
    "view.map_trajectories": "Map + trajectories",
    "view.raw_lidar": "Current raw LiDAR",
    "view.world_lidar": "World LiDAR",
    "view.anomaly_windows": "Anomaly windows",
    "anomaly.position_jump": "Position jump",
    "anomaly.yaw_jump": "Yaw jump",
    "lod.dense": "Dense",
    "lod.medium": "Medium",
    "lod.sparse": "Sparse",
    "state.connecting": "Connecting to experiment recording…",
    "state.ready": "Connected",
    "state.no_recording": "No active Rerun recording",
  },
};

export function t(language: ViewerLanguage, key: string): string {
  const value = TRANSLATIONS[language][key];
  if (value === undefined) {
    throw new Error(`missing translation key: ${key}`);
  }
  return value;
}

export function anomalyTypeLabel(language: ViewerLanguage, value: string): string {
  const key = `anomaly.${value}`;
  return TRANSLATIONS[language][key] ?? value;
}
