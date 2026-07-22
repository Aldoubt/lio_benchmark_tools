#!/usr/bin/env python3
"""Tkinter desktop front-end for the manual LIO benchmark controller."""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

if __package__ in (None, ""):
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT / "benchmark_base"))

from lio_benchmark.manifest import load_manifest
from lio_benchmark.run_directory import create_run
from lio_benchmark.run_status import load_run_status
from manual_run_controller import ControllerError, ManualRunController, RunQueueWorker


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _output_directory(run: Path, algorithm: str, entry: dict[str, Any]) -> Path:
    result = entry.get("result") or {}
    configured = result.get("output_dir") or entry.get("output_dir")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_dir():
            return candidate
    return run / "raw" / algorithm


def _resource_file(run: Path, algorithm: str, entry: dict[str, Any]) -> Path:
    output = _output_directory(run, algorithm, entry)
    candidates = list(output.glob("resource_monitor.json")) if output.is_dir() else []
    if output.is_dir():
        candidates.extend(output.glob("**/resource_monitor.json"))
    return max(candidates, key=lambda path: path.stat().st_mtime_ns) if candidates else output / "resource_monitor.json"


def load_live_resource(run: Path, status: dict[str, Any], selected_algorithm: str = "") -> tuple[str, dict[str, Any]]:
    """Load the newest live resource file, including runs started outside the GUI."""
    current = status.get("current_algorithm")
    last = status.get("last_algorithm")
    candidates = [name for name in (selected_algorithm, last) if name and name != current]
    candidates.extend(name for name in status.get("algorithms", {}) if name not in candidates and name != current)

    def read_for(algorithm: str) -> dict[str, Any]:
        entry = status.get("algorithms", {}).get(algorithm, {})
        path = _resource_file(run, algorithm, entry)
        return _read_json(path) if path.is_file() else {}

    # An externally started run must always follow its active algorithm. Once a
    # run is finished, honor the algorithm selected in the GUI.
    if current and status.get("state") == "running":
        active = read_for(current)
        if active:
            return current, active
    newest: tuple[str, dict[str, Any], int] | None = None
    run = run.expanduser()
    for algorithm in candidates:
        entry = status.get("algorithms", {}).get(algorithm, {})
        path = _resource_file(run, algorithm, entry)
        if not path.is_file():
            continue
        data = _read_json(path)
        if not data:
            continue
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        if newest is None or mtime > newest[2]:
            newest = (algorithm, data, mtime)
    return (newest[0], newest[1]) if newest else ("", {})


def resource_history(resource: dict[str, Any], limit: int = 120) -> list[tuple[float, float]]:
    history = resource.get("sample_history")
    if not isinstance(history, list):
        latest = resource.get("latest")
        history = [latest] if isinstance(latest, dict) else []
    values: list[tuple[float, float]] = []
    for item in history[-limit:]:
        if not isinstance(item, dict):
            continue
        try:
            values.append((float(item.get("elapsed_s", 0.0)), float(item.get("cpu_percent", 0.0) or 0.0)))
        except (TypeError, ValueError):
            continue
    return values


def control_states(controller_state: str, has_run: bool) -> dict[str, bool]:
    """Return button enabled states; kept pure so it is testable without Tk."""
    return {
        "prepare": has_run and controller_state in {"idle", "finished", "failed"},
        "play": controller_state == "prepared",
        "stop": controller_state in {"preparing", "prepared", "playing"},
        "open": has_run,
        "logs": has_run,
        "report": has_run and controller_state not in {"preparing", "playing", "finalizing"},
        "refresh": True,
    }


class BenchmarkGUI:
    def __init__(self, root: tk.Tk, *, run: Path | None = None, manifest: Path | None = None, bag: Path | None = None, algorithm: str | None = None, duration: str = "") -> None:
        self.root = root
        self.root.title("离线 LIO Benchmark")
        self.root.geometry("1180x760")
        self.root.minsize(900, 600)
        self.run_var = tk.StringVar(value=str(run or ""))
        self.manifest_var = tk.StringVar(value=str(manifest or ""))
        self.bag_var = tk.StringVar(value=str(bag or ""))
        self.algorithm_var = tk.StringVar(value=algorithm or "")
        self.duration_var = tk.StringVar(value=duration)
        self.status_var = tk.StringVar(value="IDLE")
        self.phase_var = tk.StringVar(value="-")
        self.elapsed_var = tk.StringVar(value="0.0 s")
        self.phase_elapsed_var = tk.StringVar(value="0.0 s")
        self.process_var = tk.StringVar(value="PID - CPU 0.0% RSS 0 B threads 0")
        self.bag_state_var = tk.StringVar(value="not_started")
        self.progress_var = tk.StringVar(value="最近更新时间 -")
        self.trajectory_var = tk.StringVar(value="0 B / 0 messages / not saved")
        self.result_var = tk.StringVar(value="")
        self.queue_state_var = tk.StringVar(value="队列未启动")
        self.queue_current_var = tk.StringVar(value="当前算法：-")
        self._controller: ManualRunController | None = None
        self._queue_worker: RunQueueWorker | None = None
        self._queue_algorithms: list[str] = []
        self._queue_run_path = ""
        self._busy = False
        self._last_logs: tuple[str, ...] = ()
        self._resource_history: list[tuple[float, float]] = []
        self._dataset_duration_s = 0.0
        self._tree: ttk.Treeview
        self._log: tk.Text
        self._queue_list: tk.Listbox
        self._resource_canvas: tk.Canvas
        self._buttons: dict[str, ttk.Button] = {}
        self._queue_buttons: dict[str, ttk.Button] = {}
        self._refresh_scheduled = False
        self._closing = False
        self.root.protocol("WM_DELETE_WINDOW", self._close_window)
        self._build()
        self._load_context()
        self._schedule_refresh()

    def _build(self) -> None:
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)
        top = ttk.Frame(root, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        for row, (label, variable, callback) in enumerate((("Run 目录", self.run_var, self._choose_run), ("Manifest", self.manifest_var, self._choose_manifest), ("Bag 目录", self.bag_var, self._choose_bag))):
            ttk.Label(top, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            ttk.Entry(top, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=3)
            ttk.Button(top, text="选择", command=callback).grid(row=row, column=2, padx=(8, 0), pady=3)
        ttk.Label(top, text="算法").grid(row=0, column=3, sticky="w", padx=(18, 8))
        self.algorithm_combo = ttk.Combobox(top, textvariable=self.algorithm_var, state="readonly", width=20)
        self.algorithm_combo.grid(row=0, column=4, sticky="w")
        ttk.Label(top, text="播放秒数").grid(row=1, column=3, sticky="w", padx=(18, 8))
        ttk.Entry(top, textvariable=self.duration_var, width=10).grid(row=1, column=4, sticky="w")
        ttk.Label(top, text="空白=完整 bag").grid(row=1, column=5, sticky="w", padx=8)
        ttk.Button(top, text="新建 Run", command=self._new_run).grid(row=2, column=3, padx=(18, 4), pady=3, sticky="w")
        ttk.Button(top, text="载入", command=self._load_context).grid(row=2, column=4, pady=3, sticky="w")

        controls = ttk.Frame(root, padding=(10, 0, 10, 8))
        controls.grid(row=1, column=0, sticky="ew")
        for name, text, callback in (("prepare", "初始化/准备算法", self._prepare), ("play", "开始播放", self._play), ("stop", "停止并保存", self._stop), ("open", "打开结果目录", self._open_output), ("logs", "查看日志", self._view_logs), ("report", "生成报告", self._report), ("refresh", "刷新状态", self._refresh)):
            button = ttk.Button(controls, text=text, command=callback)
            button.pack(side="left", padx=(0, 6))
            self._buttons[name] = button

        queue_frame = ttk.LabelFrame(root, text="运行队列（按列表顺序自动执行）", padding=6)
        queue_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        queue_frame.columnconfigure(0, weight=1)
        self._queue_list = tk.Listbox(queue_frame, height=4, exportselection=False)
        self._queue_list.grid(row=0, column=0, rowspan=2, sticky="ew", padx=(0, 8))
        queue_controls = ttk.Frame(queue_frame)
        queue_controls.grid(row=0, column=1, sticky="nw")
        for name, text, callback in (("add", "加入当前算法", self._queue_add), ("up", "上移", lambda: self._queue_move(-1)), ("down", "下移", lambda: self._queue_move(1)), ("remove", "移除", self._queue_remove), ("clear", "清空", self._queue_clear)):
            button = ttk.Button(queue_controls, text=text, command=callback)
            button.pack(side="left", padx=(0, 4))
            self._queue_buttons[name] = button
        queue_actions = ttk.Frame(queue_frame)
        queue_actions.grid(row=1, column=1, sticky="w", pady=(5, 0))
        self._queue_buttons["start"] = ttk.Button(queue_actions, text="开始运行队列", command=self._queue_start)
        self._queue_buttons["start"].pack(side="left", padx=(0, 6))
        self._queue_buttons["stop"] = ttk.Button(queue_actions, text="停止队列并保存当前算法", command=self._queue_stop)
        self._queue_buttons["stop"].pack(side="left", padx=(0, 10))
        ttk.Label(queue_actions, textvariable=self.queue_state_var).pack(side="left", padx=(0, 12))
        ttk.Label(queue_actions, textvariable=self.queue_current_var).pack(side="left")

        summary = ttk.LabelFrame(root, text="当前状态", padding=8)
        summary.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
        summary.columnconfigure(1, weight=1)
        fields = (("状态", self.status_var), ("阶段", self.phase_var), ("已运行", self.elapsed_var), ("阶段耗时", self.phase_elapsed_var), ("进程资源", self.process_var), ("Bag", self.bag_state_var), ("播放/更新时间", self.progress_var), ("轨迹", self.trajectory_var), ("结果", self.result_var))
        for row, (label, variable) in enumerate(fields):
            ttk.Label(summary, text=label).grid(row=row // 3, column=(row % 3) * 2, sticky="w", padx=(0, 6), pady=2)
            ttk.Label(summary, textvariable=variable).grid(row=row // 3, column=(row % 3) * 2 + 1, sticky="w", padx=(0, 20), pady=2)
        self._resource_canvas = tk.Canvas(summary, height=105, background="white", highlightthickness=1, highlightbackground="#c7c7c7")
        self._resource_canvas.grid(row=3, column=0, columnspan=6, sticky="ew", pady=(5, 0))
        ttk.Label(summary, text="CPU 曲线（逻辑 CPU 总和，100% = 1 个逻辑核）").grid(row=4, column=0, columnspan=6, sticky="w", pady=(3, 0))

        body = ttk.PanedWindow(root, orient="vertical")
        body.grid(row=4, column=0, sticky="nsew", padx=10, pady=(0, 10))
        status_frame = ttk.Frame(body)
        status_frame.rowconfigure(0, weight=1)
        status_frame.columnconfigure(0, weight=1)
        self._tree = ttk.Treeview(status_frame, columns=("algorithm", "state", "result", "messages", "output"), show="headings", height=8)
        for column, title, width in (("algorithm", "算法", 150), ("state", "状态", 120), ("result", "结果", 130), ("messages", "轨迹消息", 100), ("output", "输出目录", 600)):
            self._tree.heading(column, text=title)
            self._tree.column(column, width=width, anchor="w")
        self._tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(status_frame, orient="vertical", command=self._tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self._tree.configure(yscrollcommand=scroll.set)
        body.add(status_frame, weight=1)
        log_frame = ttk.Frame(body)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self._log = tk.Text(log_frame, height=10, wrap="none", state="disabled")
        self._log.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self._log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self._log.configure(yscrollcommand=log_scroll.set)
        body.add(log_frame, weight=1)

    def _choose_run(self) -> None:
        path = filedialog.askdirectory(title="选择 run 目录")
        if path:
            self.run_var.set(path)
            self._load_context()

    def _choose_manifest(self) -> None:
        path = filedialog.askopenfilename(title="选择 manifest", filetypes=(("JSON", "*.json"), ("All", "*")))
        if path:
            self.manifest_var.set(path)
            try:
                data = load_manifest(Path(path))
                self.bag_var.set(str(data.get("dataset", {}).get("bag_dir", "")))
                self._set_algorithms(data)
            except Exception as exc:
                messagebox.showerror("Manifest", str(exc))

    def _choose_bag(self) -> None:
        path = filedialog.askdirectory(title="选择 rosbag2 目录")
        if path:
            self.bag_var.set(path)

    def _set_algorithms(self, manifest: dict) -> None:
        try:
            self._dataset_duration_s = float(manifest.get("dataset", {}).get("duration_s") or 0.0)
        except (TypeError, ValueError):
            self._dataset_duration_s = 0.0
        names = [name for name, config in manifest.get("algorithms", {}).items() if config.get("enabled", True)]
        self.algorithm_combo["values"] = names
        if self.algorithm_var.get() not in names:
            self.algorithm_var.set(names[0] if names else "")
        if not self._queue_algorithms:
            try:
                status = load_run_status(Path(self.run_var.get()).expanduser()) if self.run_var.get() else {}
            except (OSError, ValueError, json.JSONDecodeError):
                status = {}
            self._queue_algorithms = [name for name in names if not self._is_full_success(status.get("algorithms", {}).get(name, {}).get("result", {}))]
            self._render_queue()

    @staticmethod
    def _is_full_success(result: dict) -> bool:
        return result.get("status") == "SUCCESS" and result.get("duration_s", result.get("smoke_duration_s")) is None

    def _render_queue(self) -> None:
        if not hasattr(self, "_queue_list"):
            return
        self._queue_list.delete(0, "end")
        for index, algorithm in enumerate(self._queue_algorithms, 1):
            self._queue_list.insert("end", f"{index}. {algorithm}")

    def _queue_add(self) -> None:
        algorithm = self.algorithm_var.get()
        if algorithm and algorithm not in self._queue_algorithms and not (self._queue_worker and self._queue_worker.is_running()):
            self._queue_algorithms.append(algorithm)
            self._render_queue()

    def _queue_move(self, offset: int) -> None:
        if self._queue_worker and self._queue_worker.is_running():
            return
        selection = self._queue_list.curselection()
        if not selection:
            return
        index = selection[0]
        target = index + offset
        if not 0 <= target < len(self._queue_algorithms):
            return
        self._queue_algorithms[index], self._queue_algorithms[target] = self._queue_algorithms[target], self._queue_algorithms[index]
        self._render_queue()
        self._queue_list.selection_set(target)

    def _queue_remove(self) -> None:
        if self._queue_worker and self._queue_worker.is_running():
            return
        selection = self._queue_list.curselection()
        if selection:
            self._queue_algorithms.pop(selection[0])
            self._render_queue()

    def _queue_clear(self) -> None:
        if not self._queue_worker or not self._queue_worker.is_running():
            self._queue_algorithms.clear()
            self._render_queue()

    def _queue_start(self) -> None:
        if self._busy or not self.run_var.get():
            return
        try:
            duration = self.duration_var.get().strip()
            value = float(duration) if duration else None
            self._queue_worker = RunQueueWorker(self.run_var.get(), self._queue_algorithms, bag_dir=Path(self.bag_var.get()).expanduser() if self.bag_var.get() else None, duration_s=value)
            self._queue_worker.start()
            self._busy = True
            self.result_var.set("运行队列已启动")
        except Exception as exc:
            self._operation_failed(exc)

    def _queue_stop(self) -> None:
        if self._queue_worker and self._queue_worker.is_running():
            threading.Thread(target=self._queue_worker.stop, name="lio-queue-stop", daemon=True).start()

    def _load_context(self) -> None:
        try:
            run_key = str(Path(self.run_var.get()).expanduser().resolve()) if self.run_var.get() else ""
            if run_key != self._queue_run_path and not (self._queue_worker and self._queue_worker.is_running()):
                self._queue_run_path = run_key
                self._queue_algorithms = []
            if self.run_var.get():
                run = Path(self.run_var.get()).expanduser()
                manifest_path = run / "manifest.json"
                if manifest_path.is_file():
                    self.manifest_var.set(str(manifest_path))
                    data = load_manifest(manifest_path)
                    self.bag_var.set(str(data.get("dataset", {}).get("bag_dir", "")))
                    self._set_algorithms(data)
            elif self.manifest_var.get():
                data = load_manifest(Path(self.manifest_var.get()).expanduser())
                self.bag_var.set(str(data.get("dataset", {}).get("bag_dir", "")))
                self._set_algorithms(data)
        except Exception as exc:
            self.result_var.set(str(exc))
        self._refresh()

    def _new_run(self) -> None:
        try:
            manifest_path = Path(self.manifest_var.get()).expanduser()
            manifest = load_manifest(manifest_path)
            run_id = simpledialog.askstring("新建 Run", "Run ID", initialvalue=f"{manifest['name']}_manual")
            if not run_id:
                return
            path = create_run(manifest, manifest_path, run_id)
            self.run_var.set(str(path))
            self.manifest_var.set(str(path / "manifest.json"))
            self._load_context()
        except Exception as exc:
            messagebox.showerror("新建 Run 失败", str(exc))

    def _controller_for_run(self) -> ManualRunController:
        run = Path(self.run_var.get()).expanduser()
        if not run.is_dir():
            raise ControllerError("请先选择有效 run 目录")
        duration = self.duration_var.get().strip()
        value = float(duration) if duration else None
        return ManualRunController(run, self.algorithm_var.get(), bag_dir=Path(self.bag_var.get()).expanduser() if self.bag_var.get() else None, duration_s=value)

    def _background(self, operation, success_message: str = "") -> None:
        if self._busy:
            return
        self._busy = True
        self._refresh()

        def worker() -> None:
            try:
                result = operation()
                self.root.after(0, lambda: self._operation_done(result, success_message))
            except Exception as exc:
                self.root.after(0, lambda error=exc: self._operation_failed(error))

        threading.Thread(target=worker, daemon=True).start()

    def _operation_done(self, result, message: str) -> None:
        self._busy = False
        if message:
            self.result_var.set(message)
        if isinstance(result, dict) and result.get("status"):
            self.result_var.set(f"{result['status']} / {result.get('trajectory_messages', 0)} messages / {result.get('output_dir', '')}")
        if self._closing:
            self.root.destroy()
            return
        self._refresh()

    def _operation_failed(self, exc: Exception) -> None:
        self._busy = False
        self.result_var.set(str(exc))
        self._refresh()
        messagebox.showerror("操作失败", str(exc))

    def _close_window(self) -> None:
        if self._closing:
            return
        if self._queue_worker and self._queue_worker.is_running():
            self._closing = True
            threading.Thread(target=self._queue_worker.stop, name="lio-queue-close", daemon=True).start()
            self.root.after(200, self._close_when_queue_stops)
            return
        active = self._controller and self._controller.state in {"preparing", "prepared", "playing", "finalizing"}
        if active:
            self._closing = True
            self._background(self._controller.stop_and_save)
        else:
            self.root.destroy()

    def _close_when_queue_stops(self) -> None:
        if self._queue_worker and self._queue_worker.is_running():
            self.root.after(200, self._close_when_queue_stops)
        else:
            self.root.destroy()

    def _prepare(self) -> None:
        def operation():
            self._controller = self._controller_for_run()
            return self._controller.prepare()

        self._background(operation, "算法已准备，等待开始播放")

    def _play(self) -> None:
        if not self._controller:
            self.result_var.set("请先初始化/准备算法")
            return
        self._background(self._controller.play)

    def _stop(self) -> None:
        if self._controller:
            self._background(self._controller.stop_and_save)

    def _open_output(self) -> None:
        path = self._controller.output_dir if self._controller and self._controller.output_dir else Path(self.run_var.get()).expanduser() / "raw" / self.algorithm_var.get()
        if not path.exists():
            path = Path(self.run_var.get()).expanduser()
        try:
            subprocess.Popen(["xdg-open", str(path)], start_new_session=True)
        except OSError as exc:
            messagebox.showerror("打开目录失败", str(exc))

    def _view_logs(self) -> None:
        lines = self._controller.latest_log_lines(200) if self._controller else []
        if not lines and self.run_var.get():
            directory = Path(self.run_var.get()) / "raw" / self.algorithm_var.get()
            for path in directory.glob("**/*.log"):
                try:
                    lines.extend(f"[{path.name}] {line}" for line in ManualRunController._tail_lines(path, 50))
                except OSError:
                    pass
        window = tk.Toplevel(self.root)
        window.title("最近日志")
        window.geometry("1000x600")
        text = tk.Text(window, wrap="none")
        text.pack(fill="both", expand=True)
        text.insert("1.0", "\n".join(lines) if lines else "暂无日志")
        text.configure(state="disabled")

    def _report(self) -> None:
        if not self._controller:
            try:
                self._controller = self._controller_for_run()
            except Exception as exc:
                self._operation_failed(exc)
                return
        self._background(self._controller.generate_report, "报告已生成")

    def _refresh(self) -> None:
        self._refresh_scheduled = False
        queue_snapshot = self._queue_worker.snapshot() if self._queue_worker else None
        if self._queue_worker:
            current_controller = self._queue_worker.current_controller
            if current_controller is not None:
                self._controller = current_controller
            self.queue_state_var.set(f"队列状态：{queue_snapshot['state']}")
            current = queue_snapshot.get("current_algorithm") or "-"
            self.queue_current_var.set(f"当前算法：{current} ({queue_snapshot.get('index', -1) + 1}/{len(queue_snapshot.get('algorithms', []))})")
            if self._queue_worker.is_running():
                self._busy = True
            elif queue_snapshot.get("state") in {"completed", "stopped"}:
                self._busy = False
        if self._controller:
            status = self._controller.snapshot()
            logs = tuple(status.get("latest_logs", []))
        elif self.run_var.get() and (Path(self.run_var.get()) / "metadata/run_status.json").is_file():
            status = load_run_status(Path(self.run_var.get()).expanduser())
            logs = ()
        else:
            status = {"controller_state": "idle", "state": "initialized", "bag_playback": "not_started", "algorithms": {}}
            logs = ()
        run_path = Path(self.run_var.get()).expanduser() if self.run_var.get() else None
        live_algorithm, resource = load_live_resource(run_path, status, self.algorithm_var.get()) if run_path else ("", {})
        display_algorithm = live_algorithm or status.get("current_algorithm") or self.algorithm_var.get()
        state = status.get("controller_state", "idle")
        selected_entry = status.get("algorithms", {}).get(display_algorithm, {})
        self.status_var.set(f"{display_algorithm}: " if display_algorithm else "")
        self.status_var.set(self.status_var.get() + str(selected_entry.get("result", {}).get("status") or selected_entry.get("state") or status.get("state", state)).upper())
        self.phase_var.set(str(status.get("phase", "-")))
        self.elapsed_var.set(f"{float(status.get('elapsed_s', 0.0)):.1f} s")
        self.phase_elapsed_var.set(f"{float(status.get('phase_elapsed_s', 0.0)):.1f} s")
        latest = resource.get("latest") or status.get("resource_snapshot") or {}
        if resource:
            self._resource_history = resource_history(resource)
            self.process_var.set(f"{display_algorithm} / CPU {float(latest.get('cpu_percent', 0.0) or 0.0):.1f}% / RSS {self._bytes(latest.get('rss_bytes', 0))} / threads {latest.get('threads', 0)} / 采样 {resource.get('samples', len(self._resource_history))}")
        else:
            process = status.get("current_process") or {}
            self.process_var.set(f"PID {process.get('pid', '-')} / CPU {float(process.get('cpu_percent', 0.0) or 0.0):.1f}% / RSS {self._bytes(process.get('rss_bytes', 0))} / threads {process.get('threads', 0)}")
        self._draw_resource_chart()
        self.bag_state_var.set(str(status.get("bag_playback", "not_started")))
        heartbeat = status.get("heartbeat", {})
        sample_elapsed = latest.get("elapsed_s")
        if status.get("bag_playback") == "running" and self._dataset_duration_s > 0 and sample_elapsed is not None:
            percentage = min(100.0, max(0.0, float(sample_elapsed) / self._dataset_duration_s * 100.0))
            progress = f"Bag 回放估计 {float(sample_elapsed):.1f}/{self._dataset_duration_s:.1f} s ({percentage:.1f}%)"
        else:
            progress = f"阶段耗时 {float(status.get('phase_elapsed_s', 0.0)):.1f} s"
        updated_at = resource.get("updated_at") or heartbeat.get("at", status.get("updated_at", "-"))
        self.progress_var.set(f"{display_algorithm or '-'} / {progress} / 最近更新 {updated_at}")
        trajectory = status.get("trajectory_snapshot") or {}
        if run_path and display_algorithm:
            output = _output_directory(run_path, display_algorithm, status.get("algorithms", {}).get(display_algorithm, {}))
            trajectory_dir = output / "trajectory"
            files = list(trajectory_dir.glob("*") if trajectory_dir.is_dir() else [])
            trajectory = {"bytes": sum(path.stat().st_size for path in files if path.is_file()), "messages": trajectory.get("messages", 0), "saved": (output / "run_result.json").is_file()}
        self.trajectory_var.set(f"{self._bytes(trajectory.get('bytes', 0))} / {trajectory.get('messages', 0)} messages / {'saved' if trajectory.get('saved') else 'not saved'}")
        if logs and logs != self._last_logs:
            self._log.configure(state="normal")
            self._log.delete("1.0", "end")
            self._log.insert("end", "\n".join(logs))
            self._log.see("end")
            self._log.configure(state="disabled")
            self._last_logs = logs
        for item in self._tree.get_children():
            self._tree.delete(item)
        for name, entry in status.get("algorithms", {}).items():
            result = entry.get("result") or {}
            output = result.get("output_dir") or entry.get("output_dir") or str((run_path / "raw" / name) if run_path else "")
            self._tree.insert("", "end", values=(name, entry.get("state", "pending"), result.get("status", ""), result.get("trajectory_messages", ""), output))
        controls = control_states(state, bool(self.run_var.get()))
        for name, button in self._buttons.items():
            button.configure(state="normal" if controls[name] and (not self._busy or name in {"refresh", "stop"}) else "disabled")
        queue_running = bool(self._queue_worker and self._queue_worker.is_running())
        external_run_active = status.get("state") == "running" or status.get("bag_playback") == "running"
        for name, button in self._queue_buttons.items():
            if name == "start":
                enabled = bool(self._queue_algorithms) and not queue_running and not self._busy and not external_run_active
            elif name == "stop":
                enabled = queue_running
            else:
                enabled = not queue_running and not self._busy and not external_run_active
            button.configure(state="normal" if enabled else "disabled")
        if not self.root.winfo_exists():
            return
        self._schedule_refresh()

    def _draw_resource_chart(self) -> None:
        if not hasattr(self, "_resource_canvas"):
            return
        canvas = self._resource_canvas
        canvas.delete("all")
        width = max(420, canvas.winfo_width())
        height = max(80, canvas.winfo_height())
        left, right, top, bottom = 42, 8, 8, 20
        chart_width = width - left - right
        chart_height = height - top - bottom
        peak = max(100.0, *(value for _, value in self._resource_history)) if self._resource_history else 100.0
        for value in (0.0, 100.0, peak):
            y = top + chart_height - (value / peak) * chart_height
            canvas.create_line(left, y, width - right, y, fill="#e5e5e5")
            canvas.create_text(left - 5, y, text=f"{value:.0f}%", anchor="e", fill="#555")
        if len(self._resource_history) < 2:
            canvas.create_text(left + 8, top + 8, text="等待资源采样", anchor="nw", fill="#777")
            return
        points = []
        for index, (_, value) in enumerate(self._resource_history):
            x = left + chart_width * index / max(1, len(self._resource_history) - 1)
            y = top + chart_height - min(peak, max(0.0, value)) / peak * chart_height
            points.extend((x, y))
        canvas.create_line(*points, fill="#1f6aa5", width=2, smooth=True)

    def _schedule_refresh(self) -> None:
        if not self._refresh_scheduled and self.root.winfo_exists():
            self._refresh_scheduled = True
            self.root.after(1000, self._refresh)

    @staticmethod
    def _bytes(value: Any) -> str:
        value = float(value or 0)
        for unit in ("B", "KiB", "MiB", "GiB"):
            if value < 1024 or unit == "GiB":
                return f"{value:.1f} {unit}"
            value /= 1024


def main() -> int:
    parser = argparse.ArgumentParser(description="Tkinter GUI for manual offline LIO benchmark runs")
    parser.add_argument("--run", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--bag", type=Path)
    parser.add_argument("--algorithm")
    parser.add_argument("--duration", default="")
    args = parser.parse_args()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"无法启动 Tkinter GUI（可能没有 DISPLAY）: {exc}", file=sys.stderr)
        print("可使用命令行 controller，例如：python3 evaluators/manual_run_controller.py --run <run> --algorithm <algorithm> --duration 20 run --auto-play", file=sys.stderr)
        return 2
    BenchmarkGUI(root, run=args.run, manifest=args.manifest, bag=args.bag, algorithm=args.algorithm, duration=args.duration)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
