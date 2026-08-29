import {WebViewer} from "@rerun-io/web-viewer";
import "./style.css";
import {anomalyTypeLabel, t} from "./i18n";
import {
  anomalySeekNanoseconds,
  normalizeState,
  type AnomalyWindow,
  type PointLod,
  type ViewerConfig,
  type ViewerLanguage,
  type ViewerState,
} from "./state";

const controls = document.querySelector<HTMLElement>("#controls");
const viewerHost = document.querySelector<HTMLElement>("#rerun-viewer");
if (controls === null || viewerHost === null) {
  throw new Error("web viewer host elements are missing");
}

let config: ViewerConfig;
let state: ViewerState;
const viewer = new WebViewer();

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  text?: string,
  className?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className !== undefined) node.className = className;
  return node;
}

function setStatus(message: string): void {
  const target = controls.querySelector<HTMLElement>("[data-role='status']");
  if (target !== null) target.textContent = message;
}

async function postState(next: ViewerState): Promise<void> {
  const response = await fetch("/api/state", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(next),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`viewer state update failed (${response.status}): ${detail}`);
  }
}

function group(title: string): HTMLElement {
  const root = element("section", undefined, "control-group");
  root.append(element("h2", title));
  return root;
}

function renderAlgorithmControls(root: HTMLElement): void {
  const list = element("div", undefined, "control-list");
  for (const algorithm of config.algorithms) {
    const label = element("label", undefined, "control-row");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = state.visibleAlgorithms.includes(algorithm);
    input.addEventListener("change", () => {
      const nextVisible = input.checked
        ? [...state.visibleAlgorithms, algorithm]
        : state.visibleAlgorithms.filter((item) => item !== algorithm);
      void updateState(normalizeState(config, {...state, visibleAlgorithms: nextVisible}));
    });
    label.append(input, document.createTextNode(algorithm));
    list.append(label);
  }
  root.append(list);
}

function renderWorldAlgorithm(root: HTMLElement): void {
  const select = document.createElement("select");
  for (const algorithm of config.algorithms) {
    const option = document.createElement("option");
    option.value = algorithm;
    option.textContent = algorithm;
    option.selected = algorithm === state.worldAlgorithm;
    select.append(option);
  }
  select.addEventListener("change", () => {
    void updateState(normalizeState(config, {...state, worldAlgorithm: select.value}));
  });
  root.append(select);
}

function renderLod(root: HTMLElement): void {
  const select = document.createElement("select");
  for (const lod of ["dense", "medium", "sparse"] as PointLod[]) {
    const option = document.createElement("option");
    option.value = lod;
    option.textContent = t(state.language, `lod.${lod}`);
    option.selected = lod === state.pointLod;
    select.append(option);
  }
  select.addEventListener("change", () => {
    void updateState(
      normalizeState(config, {...state, pointLod: select.value as PointLod}),
    );
  });
  root.append(select);
}

function renderLanguage(root: HTMLElement): void {
  const select = document.createElement("select");
  const choices: Array<[ViewerLanguage, string]> = [
    ["zh-CN", "中文"],
    ["en", "English"],
  ];
  for (const [language, label] of choices) {
    const option = document.createElement("option");
    option.value = language;
    option.textContent = label;
    option.selected = language === state.language;
    select.append(option);
  }
  select.addEventListener("change", () => {
    void updateState(
      normalizeState(config, {...state, language: select.value as ViewerLanguage}),
    );
  });
  root.append(select);
}

function anomalyButton(window: AnomalyWindow): HTMLButtonElement {
  const button = element("button");
  const types = (window.types ?? [])
    .map((value) => anomalyTypeLabel(state.language, value))
    .join(" / ");
  const title = `${window.algorithm}  ${window.start_bag_time_s.toFixed(2)}–${window.end_bag_time_s.toFixed(2)} s`;
  button.append(document.createTextNode(title));
  const meta = element(
    "span",
    `${types || "—"} · severity=${(window.severity ?? 0).toFixed(2)}`,
    "anomaly-meta",
  );
  button.append(meta);
  button.addEventListener("click", () => void seekAnomaly(window));
  return button;
}

function renderControls(): void {
  document.documentElement.lang = state.language;
  controls.replaceChildren();
  controls.append(element("h1", t(state.language, "app.title")));

  const algorithms = group(t(state.language, "control.algorithms"));
  renderAlgorithmControls(algorithms);
  controls.append(algorithms);

  const world = group(t(state.language, "control.world_algorithm"));
  renderWorldAlgorithm(world);
  controls.append(world);

  const lod = group(t(state.language, "control.point_lod"));
  renderLod(lod);
  controls.append(lod);

  const language = group(t(state.language, "control.language"));
  renderLanguage(language);
  controls.append(language);

  const anomalies = group(t(state.language, "view.anomaly_windows"));
  const list = element("div", undefined, "control-list");
  for (const window of config.anomalyWindows) list.append(anomalyButton(window));
  anomalies.append(list);
  controls.append(anomalies);

  const status = element("div", t(state.language, "state.ready"), "status");
  status.dataset.role = "status";
  controls.append(status);
}

async function updateState(next: ViewerState): Promise<void> {
  try {
    await postState(next);
    state = next;
    renderControls();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  }
}

async function seekAnomaly(window: AnomalyWindow): Promise<void> {
  const recordingId = viewer.get_active_recording_id();
  if (recordingId === null) {
    setStatus(t(state.language, "state.no_recording"));
    return;
  }
  viewer.set_active_timeline(recordingId, "bag_time");
  viewer.set_playing(recordingId, false);
  viewer.set_current_time(
    recordingId,
    "bag_time",
    anomalySeekNanoseconds(window),
  );
  const visibleAlgorithms = state.visibleAlgorithms.includes(window.algorithm)
    ? state.visibleAlgorithms
    : [...state.visibleAlgorithms, window.algorithm];
  await updateState(
    normalizeState(config, {
      ...state,
      visibleAlgorithms,
      worldAlgorithm: window.algorithm,
    }),
  );
}

async function main(): Promise<void> {
  const response = await fetch("/viewer-config.json", {cache: "no-store"});
  if (!response.ok) throw new Error(`failed to load viewer config: ${response.status}`);
  config = await response.json() as ViewerConfig;
  state = normalizeState(config);
  renderControls();
  setStatus(t(state.language, "state.connecting"));
  await viewer.start(config.grpcUrl, viewerHost, {
    width: "",
    height: "",
    hide_welcome_screen: true,
  });
  setStatus(t(state.language, "state.ready"));
}

void main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  controls.replaceChildren(element("div", message, "status"));
});
