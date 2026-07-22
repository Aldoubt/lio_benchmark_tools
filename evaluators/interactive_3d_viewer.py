#!/usr/bin/env python3
"""Interactive VTK viewer for aligned LIO trajectories and point-cloud maps."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation, Slerp
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk
from PIL import Image, ImageTk
from matplotlib import font_manager, rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import vtk
from vtkmodules.tk.vtkTkRenderWindowInteractor import vtkTkRenderWindowInteractor


LABELS = {
    "kiss_icp": "KISS-ICP",
    "mola_lo": "MOLA-LO",
    "mola_lio": "MOLA-LIO",
    "fast_livo2": "FAST-LIVO2",
    "point_lio": "Point-LIO",
    "dlio": "DLIO",
    "glim_odometry": "GLIM odometry",
    "glim_full_slam": "GLIM full SLAM",
    "lio_sam_no_loop": "LIO-SAM no-loop",
    "lio_sam_loop": "LIO-SAM loop",
}

COLORS = {
    "kiss_icp": "#7f8c8d",
    "mola_lo": "#9b59b6",
    "mola_lio": "#8e44ad",
    "fast_livo2": "#e67e22",
    "point_lio": "#2980b9",
    "dlio": "#c0392b",
    "glim_odometry": "#27ae60",
    "glim_full_slam": "#16a085",
    "lio_sam_no_loop": "#34495e",
    "lio_sam_loop": "#2c3e50",
}

MAX_PATH_POINTS = 20000


def configure_plot_fonts() -> None:
    for font_path in (
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    ):
        if not font_path.is_file():
            continue
        font_manager.fontManager.addfont(str(font_path))
        rcParams["font.family"] = [font_manager.FontProperties(fname=str(font_path)).get_name()]
        rcParams["axes.unicode_minus"] = False
        break


configure_plot_fonts()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_trajectory(path: Path) -> dict[str, np.ndarray]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if len(rows) < 2:
        raise ValueError(f"trajectory has fewer than two rows: {path}")
    fields = ("timestamp_s", "x_m", "y_m", "z_m", "qx", "qy", "qz", "qw")
    data = {key: np.asarray([float(row[key]) for row in rows], dtype=np.float64) for key in fields}
    valid = np.isfinite(np.column_stack(tuple(data.values()))).all(axis=1)
    data = {key: value[valid] for key, value in data.items()}
    order = np.argsort(data["timestamp_s"], kind="stable")
    data = {key: value[order] for key, value in data.items()}
    _, unique = np.unique(data["timestamp_s"], return_index=True)
    unique = np.sort(unique)
    data = {key: value[unique] for key, value in data.items()}
    data["positions"] = np.column_stack((data["x_m"], data["y_m"], data["z_m"]))
    data["rotations"] = Rotation.from_quat(np.column_stack((data["qx"], data["qy"], data["qz"], data["qw"])))
    data["slerp"] = Slerp(data["timestamp_s"], data["rotations"])
    return data


def pose_at(trajectory: dict[str, np.ndarray], timestamp: float) -> tuple[np.ndarray, np.ndarray]:
    position = np.asarray([
        np.interp(timestamp, trajectory["timestamp_s"], trajectory["positions"][:, axis])
        for axis in range(3)
    ], dtype=np.float64)
    rotation = trajectory["slerp"](np.asarray([timestamp])).as_matrix()[0]
    return position, rotation


def align_trajectory(reference: dict[str, np.ndarray], candidate: dict[str, np.ndarray], origin: np.ndarray) -> np.ndarray:
    start = max(float(reference["timestamp_s"][0]), float(candidate["timestamp_s"][0]))
    reference_position, reference_rotation = pose_at(reference, start)
    candidate_position, candidate_rotation = pose_at(candidate, start)
    reference_yaw = math.atan2(reference_rotation[1, 0], reference_rotation[0, 0])
    candidate_yaw = math.atan2(candidate_rotation[1, 0], candidate_rotation[0, 0])
    yaw = reference_yaw - candidate_yaw
    rotation = np.array([[math.cos(yaw), -math.sin(yaw), 0.0], [math.sin(yaw), math.cos(yaw), 0.0], [0.0, 0.0, 1.0]])
    translation = reference_position - rotation @ candidate_position
    positions = (rotation @ candidate["positions"].T).T + translation - origin
    if len(positions) > MAX_PATH_POINTS:
        indices = np.linspace(0, len(positions) - 1, MAX_PATH_POINTS, dtype=np.int64)
        positions = positions[indices]
    return positions


def make_path_actor(positions: np.ndarray) -> vtk.vtkActor:
    points = vtk.vtkPoints()
    points.SetNumberOfPoints(len(positions))
    for index, point in enumerate(positions):
        points.SetPoint(index, float(point[0]), float(point[1]), float(point[2]))
    line = vtk.vtkPolyLine()
    line.GetPointIds().SetNumberOfIds(len(positions))
    for index in range(len(positions)):
        line.GetPointIds().SetId(index, index)
    cells = vtk.vtkCellArray()
    cells.InsertNextCell(line)
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(points)
    polydata.SetLines(cells)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(polydata)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    return actor


def make_map_actor(path: Path) -> vtk.vtkActor:
    reader = vtk.vtkPLYReader()
    reader.SetFileName(str(path))
    reader.Update()
    polydata = reader.GetOutput()
    input_port = reader.GetOutputPort()
    # The generated binary PLY stores vertex records without a vertex-cell
    # section. VTK needs explicit vertex cells for a point-only cloud to render.
    if polydata.GetNumberOfPoints() and not polydata.GetNumberOfVerts():
        glyph = vtk.vtkVertexGlyphFilter()
        glyph.SetInputData(polydata)
        glyph.Update()
        input_port = glyph.GetOutputPort()
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(input_port)
    mapper.ScalarVisibilityOff()
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    return actor


class InteractiveViewer:
    def __init__(self, root: tk.Tk, run: Path, algorithms: list[str] | None = None) -> None:
        self.root = root
        self.run = run.resolve()
        self.maps_dir = self.run / "figures" / "fast_livo2_baseline_maps"
        self._actors: dict[str, dict[str, vtk.vtkActor]] = {}
        self._health_flags: dict[str, list[str]] = {}
        self._color_vars: dict[str, str] = {}
        self._visible_vars: dict[str, tk.BooleanVar] = {}
        self._show_maps = tk.BooleanVar(value=True)
        self._show_paths = tk.BooleanVar(value=True)
        self._point_size = tk.DoubleVar(value=2.0)
        self._line_width = tk.DoubleVar(value=3.0)
        self._status = tk.StringVar(value="正在加载...")
        self._resources: dict[str, dict[str, Any]] = {}
        self._performance_metric = tk.StringVar(value="CPU")
        self._performance_metric_options = {
            "CPU": "cpu_percent",
            "RSS 内存": "rss_mib",
            "线程数": "threads",
        }
        self._performance_figure: Figure | None = None
        self._performance_axes: Any = None
        self._performance_canvas: FigureCanvasTkAgg | None = None
        self._performance_table: ttk.Treeview | None = None
        self._performance_info = tk.StringVar(value="")
        self._load_data(algorithms)
        self._load_resources()
        self._build_ui()
        self._apply_visibility()
        self._fit_camera()

    def _load_data(self, requested: list[str] | None) -> None:
        metadata = read_json(self.maps_dir / "visualization_metadata.json")
        metrics = read_json(self.run / "metrics" / "full_comparison.json")
        self._health_flags = {
            item.get("algorithm", ""): list(item.get("health_flags") or [])
            for item in metrics.get("algorithms", [])
            if item.get("algorithm")
        }
        available = set(metadata.get("selected_algorithms", []))
        available.update(path.stem for path in self.maps_dir.glob("*_map.ply"))
        available.update(path.stem for path in (self.run / "standardized" / "trajectories").glob("*.csv"))
        ordered = [name for name in LABELS if name in available]
        ordered.extend(sorted(available - set(ordered)))
        selected = set(requested) if requested is not None else {
            name for name in ordered if not self._health_flags.get(name)
        }
        trajectories = {}
        for algorithm in ordered:
            path = self.run / "standardized" / "trajectories" / f"{algorithm}.csv"
            if path.is_file():
                try:
                    trajectories[algorithm] = load_trajectory(path)
                except (OSError, ValueError, KeyError):
                    continue
        baseline_name = str(metadata.get("baseline") or "fast_livo2")
        if baseline_name not in trajectories:
            raise ValueError(f"missing baseline trajectory: {baseline_name}")
        common_start = max(float(data["timestamp_s"][0]) for data in trajectories.values())
        origin, _ = pose_at(trajectories[baseline_name], common_start)
        for algorithm in ordered:
            path = self.run / "standardized" / "trajectories" / f"{algorithm}.csv"
            map_path = self.maps_dir / f"{algorithm}_map.ply"
            if algorithm not in trajectories and not map_path.is_file():
                continue
            entry: dict[str, vtk.vtkActor] = {}
            if map_path.is_file():
                entry["map"] = make_map_actor(map_path)
            if algorithm in trajectories:
                entry["path"] = make_path_actor(align_trajectory(trajectories[baseline_name], trajectories[algorithm], origin))
            if entry:
                self._actors[algorithm] = entry
                self._color_vars[algorithm] = COLORS.get(algorithm, "#f1c40f")
                self._visible_vars[algorithm] = tk.BooleanVar(value=algorithm in selected)
        if not self._actors:
            raise ValueError(f"no maps or trajectories found under {self.run}")
        hidden = [LABELS.get(name, name) for name in self._actors if self._health_flags.get(name)]
        suffix = f"；默认隐藏异常算法：{', '.join(hidden)}" if hidden and requested is None else ""
        self._status.set(f"已加载 {len(self._actors)} 个算法；点云和路径使用 FAST-LIVO2 基准坐标系{suffix}")

    def _load_resources(self) -> None:
        status = read_json(self.run / "metadata" / "run_status.json")
        algorithm_status = status.get("algorithms", {})
        for algorithm in self._actors:
            entry = algorithm_status.get(algorithm, {})
            result = entry.get("result") or {}
            configured_dir = result.get("output_dir") or entry.get("output_dir")
            output_dir = Path(configured_dir) if configured_dir else self.run / "raw" / algorithm
            resource_path = output_dir / "resource_monitor.json"
            if not resource_path.is_file():
                candidates = sorted(
                    (self.run / "raw" / algorithm).glob("**/resource_monitor.json"),
                    key=lambda path: path.stat().st_mtime,
                )
                resource_path = candidates[-1] if candidates else resource_path
            resource = read_json(resource_path)
            history = resource.get("sample_history") or []
            if not history and resource.get("latest"):
                history = [resource["latest"]]
            normalized: list[dict[str, float]] = []
            for sample in history:
                try:
                    normalized.append({
                        "elapsed_s": float(sample.get("elapsed_s", 0.0)),
                        "cpu_percent": float(sample.get("cpu_percent", 0.0)),
                        "rss_mib": float(sample.get("rss_bytes", 0.0)) / (1024.0 * 1024.0),
                        "threads": float(sample.get("threads", 0.0)),
                    })
                except (TypeError, ValueError):
                    continue
            if not normalized:
                continue
            self._resources[algorithm] = {
                "history": normalized,
                "mean_cpu_percent": float(resource.get("mean_cpu_percent", np.mean([item["cpu_percent"] for item in normalized]))),
                "peak_cpu_percent": float(resource.get("peak_cpu_percent", max(item["cpu_percent"] for item in normalized))),
                "mean_rss_mib": float(resource.get("mean_rss_mib", np.mean([item["rss_mib"] for item in normalized]))),
                "peak_rss_mib": float(resource.get("peak_rss_mib", max(item["rss_mib"] for item in normalized))),
                "mean_threads": float(np.mean([item["threads"] for item in normalized])),
                "peak_threads": float(resource.get("peak_threads", max(item["threads"] for item in normalized))),
            }

    @staticmethod
    def _rgb(value: str) -> tuple[float, float, float]:
        value = value.lstrip("#")
        return tuple(int(value[index:index + 2], 16) / 255.0 for index in (0, 2, 4))

    def _build_ui(self) -> None:
        self.root.title("LIO 三维点云、路径与性能对比")
        self.root.geometry("1850x950")
        self.root.minsize(1350, 700)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        notebook = ttk.Notebook(self.root)
        notebook.grid(row=0, column=0, sticky="nsew")
        view_tab = ttk.Frame(notebook)
        performance_tab = ttk.Frame(notebook)
        notebook.add(view_tab, text="三维点云与路径")
        notebook.add(performance_tab, text="性能曲线")
        view_tab.columnconfigure(1, weight=1)
        view_tab.columnconfigure(2, weight=0, minsize=430)
        view_tab.rowconfigure(0, weight=1)
        controls = ttk.Frame(view_tab, padding=10)
        controls.grid(row=0, column=0, sticky="ns")
        render_frame = ttk.Frame(view_tab, padding=(0, 10, 10, 10))
        render_frame.grid(row=0, column=1, sticky="nsew")
        render_frame.rowconfigure(0, weight=1)
        render_frame.columnconfigure(0, weight=1)
        performance_panel = ttk.LabelFrame(view_tab, text="当前显示算法的性能消耗", padding=8)
        performance_panel.grid(row=0, column=2, sticky="nsew", padx=(0, 10), pady=10)
        performance_panel.rowconfigure(1, weight=1)
        performance_panel.columnconfigure(0, weight=1)

        ttk.Label(controls, text="算法选择", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        actions = ttk.Frame(controls)
        actions.pack(fill="x", pady=(6, 8))
        ttk.Button(actions, text="全选", command=lambda: self._set_all(True)).pack(side="left", padx=(0, 4))
        ttk.Button(actions, text="全不选", command=lambda: self._set_all(False)).pack(side="left", padx=(0, 4))
        ttk.Button(actions, text="适应当前显示", command=self._fit_camera).pack(side="left", padx=(0, 4))
        ttk.Button(actions, text="适应正常算法", command=lambda: self._fit_camera(stable_only=True)).pack(side="left")
        for algorithm in self._actors:
            row = ttk.Frame(controls)
            row.pack(fill="x", pady=2)
            label = LABELS.get(algorithm, algorithm)
            if self._health_flags.get(algorithm):
                label += "（轨迹异常）"
            ttk.Checkbutton(row, text=label, variable=self._visible_vars[algorithm], command=self._apply_visibility).pack(side="left", anchor="w")
            button = tk.Button(row, width=2, height=1, bg=self._color_vars[algorithm], relief="solid", command=lambda name=algorithm: self._choose_color(name))
            button.pack(side="right", padx=(6, 0))
            row._color_button = button  # type: ignore[attr-defined]

        ttk.Separator(controls).pack(fill="x", pady=10)
        ttk.Checkbutton(controls, text="显示点云", variable=self._show_maps, command=self._apply_visibility).pack(anchor="w")
        ttk.Checkbutton(controls, text="显示路径", variable=self._show_paths, command=self._apply_visibility).pack(anchor="w")
        ttk.Label(controls, text="点云大小").pack(anchor="w", pady=(10, 0))
        tk.Scale(controls, from_=1, to=8, resolution=0.5, orient="horizontal", variable=self._point_size, command=lambda _value: self._apply_style()).pack(fill="x")
        ttk.Label(controls, text="路径线宽").pack(anchor="w")
        tk.Scale(controls, from_=1, to=10, resolution=0.5, orient="horizontal", variable=self._line_width, command=lambda _value: self._apply_style()).pack(fill="x")
        ttk.Label(controls, text="预设视角").pack(anchor="w", pady=(10, 3))
        views = ttk.Frame(controls)
        views.pack(fill="x")
        for name, label in (("top", "顶视"), ("front", "前视"), ("side", "侧视"), ("isometric", "等轴")):
            ttk.Button(views, text=label, command=lambda view=name: self._set_view(view)).pack(side="left", padx=(0, 3))
        ttk.Label(controls, textvariable=self._status, wraplength=250, justify="left").pack(anchor="w", pady=(12, 0))

        self._widget = vtkTkRenderWindowInteractor(render_frame, rw=vtk.vtkRenderWindow(), width=1000, height=700)
        self._widget.grid(row=0, column=0, sticky="nsew")
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.055, 0.07, 0.09)
        self._widget.GetRenderWindow().AddRenderer(self.renderer)
        self._widget.GetRenderWindow().GetInteractor().SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())
        axes = vtk.vtkAxesActor()
        marker = vtk.vtkOrientationMarkerWidget()
        marker.SetOrientationMarker(axes)
        marker.SetInteractor(self._widget.GetRenderWindow().GetInteractor())
        marker.SetViewport(0.0, 0.0, 0.18, 0.18)
        marker.SetEnabled(1)
        marker.InteractiveOff()
        self._marker = marker
        for actors in self._actors.values():
            for actor in actors.values():
                self.renderer.AddActor(actor)
        self._widget.Initialize()
        self._build_live_performance_panel(performance_panel)
        self._build_performance_tab(performance_tab)

    def _build_live_performance_panel(self, parent: ttk.LabelFrame) -> None:
        controls = ttk.Frame(parent)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="指标").grid(row=0, column=0, sticky="w")
        selector = ttk.Combobox(
            controls,
            textvariable=self._performance_metric,
            values=list(self._performance_metric_options),
            state="readonly",
            width=12,
        )
        selector.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        selector.bind("<<ComboboxSelected>>", self._metric_changed)
        ttk.Label(
            parent,
            textvariable=self._performance_info,
            wraplength=390,
            justify="left",
        ).grid(row=3, column=0, sticky="ew", pady=(6, 0))

        self._performance_figure = Figure(figsize=(4.5, 3.4), dpi=100)
        self._performance_axes = self._performance_figure.add_subplot(111)
        self._performance_canvas = FigureCanvasTkAgg(self._performance_figure, master=parent)
        self._performance_canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")

        self._performance_table = ttk.Treeview(
            parent,
            columns=("algorithm", "mean", "peak", "samples"),
            show="headings",
            height=9,
        )
        headings = {
            "algorithm": "算法",
            "mean": "均值",
            "peak": "峰值",
            "samples": "采样点",
        }
        widths = {"algorithm": 132, "mean": 82, "peak": 82, "samples": 62}
        for column, heading in headings.items():
            self._performance_table.heading(column, text=heading)
            self._performance_table.column(column, width=widths[column], anchor="center", stretch=column == "algorithm")
        self._performance_table.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self._refresh_performance_plot()

    def _metric_changed(self, _event: Any = None) -> None:
        self._refresh_performance_plot()

    def _refresh_performance_plot(self) -> None:
        if self._performance_axes is None or self._performance_canvas is None:
            return
        metric = self._performance_metric_options.get(self._performance_metric.get(), "cpu_percent")
        titles = {
            "cpu_percent": ("CPU 消耗曲线", "CPU（%）", "进程树逻辑 CPU 总和，100%约等于占用 1 个逻辑核"),
            "rss_mib": ("RSS 内存消耗曲线", "RSS 内存（MiB）", "进程树驻留内存，单位 MiB；数值越高表示内存占用越大"),
            "threads": ("线程数变化曲线", "线程数", "进程树线程数量；用于观察算法并发和线程膨胀情况"),
        }
        title, ylabel, explanation = titles[metric]
        axes = self._performance_axes
        axes.clear()
        axes.set_title(title, fontsize=10)
        axes.set_xlabel("算法运行时间（s）", fontsize=8)
        axes.set_ylabel(ylabel, fontsize=8)
        axes.grid(True, alpha=0.25)
        rows: list[tuple[str, str, str, str]] = []
        plotted = 0
        for algorithm in self._actors:
            if not self._visible_vars[algorithm].get():
                continue
            resource = self._resources.get(algorithm)
            if not resource:
                continue
            history = resource["history"]
            x = [item["elapsed_s"] for item in history]
            y = [item[metric] for item in history]
            axes.plot(x, y, label=LABELS.get(algorithm, algorithm), color=self._color_vars[algorithm], linewidth=1.1)
            if metric == "cpu_percent":
                mean = resource["mean_cpu_percent"]
                peak = resource["peak_cpu_percent"]
                unit = "%"
            elif metric == "rss_mib":
                mean = resource["mean_rss_mib"]
                peak = resource["peak_rss_mib"]
                unit = " MiB"
            else:
                mean = resource["mean_threads"]
                peak = resource["peak_threads"]
                unit = ""
            label = LABELS.get(algorithm, algorithm)
            if self._health_flags.get(algorithm):
                label += "（异常）"
            rows.append((label, f"{mean:.1f}{unit}", f"{peak:.1f}{unit}", str(len(history))))
            plotted += 1
        if plotted:
            axes.legend(fontsize=6, loc="upper right")
        else:
            axes.text(0.5, 0.5, "当前没有选中的性能数据", ha="center", va="center", transform=axes.transAxes)
        self._performance_figure.tight_layout()
        self._performance_canvas.draw_idle()
        if self._performance_table is not None:
            for item in self._performance_table.get_children():
                self._performance_table.delete(item)
            for row in rows:
                self._performance_table.insert("", "end", values=row)
        missing = sum(1 for algorithm in self._actors if algorithm not in self._resources and self._visible_vars[algorithm].get())
        suffix = f"；{missing} 个选中算法没有性能采样文件" if missing else ""
        self._performance_info.set(f"{explanation}。曲线只显示左侧已勾选算法，颜色与点云/路径一致{suffix}")

    def _build_performance_tab(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        canvas = tk.Canvas(parent, background="#f4f6f8", highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        content = ttk.Frame(canvas, padding=18)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=max(event.width, 900)))
        self._performance_photos: list[ImageTk.PhotoImage] = []
        curve_files = (
            ("CPU、内存和线程性能曲线", self.run / "figures" / "resource_curves" / "resource_curves.png"),
            ("算法资源均值与峰值汇总", self.run / "figures" / "resource_curves" / "resource_summary.png"),
        )
        for title, path in curve_files:
            frame = ttk.LabelFrame(content, text=title, padding=8)
            frame.pack(fill="x", pady=(0, 14))
            if not path.is_file():
                ttk.Label(frame, text=f"未找到性能图：{path}").pack(anchor="w")
                continue
            image = Image.open(path).convert("RGB")
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            image.thumbnail((1250, 1100), resampling)
            photo = ImageTk.PhotoImage(image)
            self._performance_photos.append(photo)
            ttk.Label(frame, image=photo).pack(anchor="center")

    def _set_all(self, value: bool) -> None:
        for variable in self._visible_vars.values():
            variable.set(value)
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        for algorithm, actors in self._actors.items():
            visible = self._visible_vars[algorithm].get()
            if "map" in actors:
                actors["map"].SetVisibility(int(visible and self._show_maps.get()))
            if "path" in actors:
                actors["path"].SetVisibility(int(visible and self._show_paths.get()))
            color = self._rgb(self._color_vars[algorithm])
            for actor in actors.values():
                actor.GetProperty().SetColor(*color)
        self._apply_style()
        self._refresh_performance_plot()

    def _apply_style(self) -> None:
        for actors in self._actors.values():
            if "map" in actors:
                actors["map"].GetProperty().SetPointSize(float(self._point_size.get()))
                actors["map"].GetProperty().SetOpacity(0.58)
            if "path" in actors:
                actors["path"].GetProperty().SetLineWidth(float(self._line_width.get()))
        self._widget.GetRenderWindow().Render()

    def _choose_color(self, algorithm: str) -> None:
        chosen = colorchooser.askcolor(color=self._color_vars[algorithm], title=f"选择颜色：{LABELS.get(algorithm, algorithm)}")
        if chosen[1]:
            self._color_vars[algorithm] = chosen[1]
            self._apply_visibility()
            for child in self.root.winfo_children():
                self._refresh_color_buttons(child, algorithm, chosen[1])

    def _refresh_color_buttons(self, parent: tk.Misc, algorithm: str, color: str) -> None:
        for child in parent.winfo_children():
            if isinstance(child, tk.Button) and child.cget("command"):
                # Rebuild color buttons through their row rather than relying on ttk styling.
                try:
                    if child.master.winfo_children()[0].cget("text") == LABELS.get(algorithm, algorithm):
                        child.configure(bg=color)
                except tk.TclError:
                    pass
            self._refresh_color_buttons(child, algorithm, color)

    def _fit_camera(self, stable_only: bool = False) -> None:
        changed: list[tuple[vtk.vtkActor, int]] = []
        if stable_only:
            for algorithm, actors in self._actors.items():
                if not self._health_flags.get(algorithm):
                    continue
                for actor in actors.values():
                    changed.append((actor, actor.GetVisibility()))
                    actor.SetVisibility(0)
        self.renderer.ResetCamera()
        for actor, visibility in changed:
            actor.SetVisibility(visibility)
        self._widget.GetRenderWindow().Render()

    def _set_view(self, view: str) -> None:
        bounds = self.renderer.ComputeVisiblePropBounds()
        if not np.isfinite(bounds).all():
            return
        center = np.asarray([(bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2])
        distance = max(float(bounds[1] - bounds[0]), float(bounds[3] - bounds[2]), float(bounds[5] - bounds[4]), 1.0) * 1.8
        camera = self.renderer.GetActiveCamera()
        camera.SetFocalPoint(*center)
        if view == "top":
            camera.SetPosition(center[0], center[1], center[2] + distance)
            camera.SetViewUp(0, 1, 0)
        elif view == "front":
            camera.SetPosition(center[0], center[1] - distance, center[2])
            camera.SetViewUp(0, 0, 1)
        elif view == "side":
            camera.SetPosition(center[0] + distance, center[1], center[2])
            camera.SetViewUp(0, 0, 1)
        else:
            camera.SetPosition(center[0] + distance, center[1] - distance, center[2] + distance * 0.8)
            camera.SetViewUp(0, 0, 1)
        self.renderer.ResetCameraClippingRange()
        self._widget.GetRenderWindow().Render()


def main() -> int:
    parser = argparse.ArgumentParser(description="LIO 三维点云、路径和性能曲线对比查看器")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithms", help="Comma-separated algorithms to show initially")
    args = parser.parse_args()
    try:
        root = tk.Tk()
        requested = [item.strip() for item in args.algorithms.split(",") if item.strip()] if args.algorithms else None
        InteractiveViewer(root, args.run, requested)
        root.mainloop()
    except (OSError, ValueError, RuntimeError, tk.TclError) as exc:
        messagebox.showerror("查看器启动失败", str(exc)) if "root" in locals() else None
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
