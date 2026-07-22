#!/usr/bin/env python3
"""Manual, process-group-safe lifecycle controller for one LIO algorithm.

The controller deliberately keeps the benchmark manifest as the source of
truth.  It only changes the lifecycle boundary: prepare starts the algorithm,
adapters, monitor and recorder; play starts rosbag playback; finalization
stops everything, validates the bag and writes the result.
"""
from __future__ import annotations

import argparse
import atexit
import datetime as dt
import json
import os
import signal
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(_ROOT / "benchmark_base"))

from lio_benchmark.manifest import load_manifest, resolve_path
from lio_benchmark.run_directory import create_run, resolve_run
from lio_benchmark.run_status import (
    atomic_write_json,
    heartbeat_run_status,
    load_run_status,
    now,
    update_run_status,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_TOPICS = {
    "kiss_icp": "/kiss/odometry",
    "mola_lo": "/tf",
    "mola_lio": "/tf",
    "fast_livo2": "/aft_mapped_to_init",
    "point_lio": "/aft_mapped_to_init",
    "dlio": "/odom",
    "glim_odometry": "/glim_ros/odom",
    "glim_full_slam": "/glim_ros/odom_corrected",
    "lio_sam_no_loop": "/lio_sam/mapping/odometry",
    "lio_sam_loop": "/lio_sam/mapping/odometry",
}


class ControllerError(RuntimeError):
    """A lifecycle operation failed after the controller had a chance to clean up."""


class ManualRunController:
    """Own all processes for one manually controlled algorithm run."""

    def __init__(
        self,
        run_dir: Path,
        algorithm: str,
        *,
        manifest_path: Path | None = None,
        bag_dir: Path | None = None,
        duration_s: float | None = None,
        startup_timeout_s: float = 5.0,
        settle_timeout_s: float = 15.0,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        run_factory: Callable[..., Any] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.run_dir = Path(run_dir).expanduser().resolve()
        self.algorithm = algorithm
        self.manifest_path = (manifest_path or self.run_dir / "manifest.json").expanduser().resolve()
        self.bag_dir_override = Path(bag_dir).expanduser().resolve() if bag_dir else None
        self.duration_s = duration_s
        self.startup_timeout_s = startup_timeout_s
        self.settle_timeout_s = settle_timeout_s
        self._popen = popen_factory
        self._run = run_factory
        self._sleep = sleep
        self._operation_lock = threading.RLock()
        self._finalize_lock = threading.Lock()
        self._stop_requested = threading.Event()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._processes: dict[str, Any] = {}
        self._log_handles: list[Any] = []
        self._log_paths: dict[str, Path] = {}
        self._phase_started_at = now()
        self._phase = "idle"
        self._state = "idle"
        self._output_dir: Path | None = None
        self._bag_process: Any | None = None
        self._failure_code: str | None = None
        self._failure_reason: str | None = None
        self._playback_exit_code: int | None = None
        self._playback_expected_timeout = False
        self._final_result: dict[str, Any] | None = None
        self._manifest: dict[str, Any] | None = None
        atexit.register(self.cleanup)

    @property
    def state(self) -> str:
        return self._state

    @property
    def output_dir(self) -> Path | None:
        return self._output_dir

    @property
    def manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            if not self.manifest_path.is_file():
                raise ControllerError(f"缺少 manifest: {self.manifest_path}")
            self._manifest = load_manifest(self.manifest_path)
        return self._manifest

    @property
    def bag_dir(self) -> Path:
        value = self.bag_dir_override or resolve_path(str(self.manifest["dataset"]["bag_dir"]))
        return Path(value).resolve()

    def _algorithm_config(self) -> Path:
        config = self.manifest.get("algorithms", {}).get(self.algorithm)
        if not config:
            raise ControllerError(f"算法不在 manifest 中: {self.algorithm}")
        return resolve_path(str(config["config"])).resolve()

    def _algorithm_entry(self) -> dict[str, Any]:
        config = self.manifest.get("algorithms", {}).get(self.algorithm)
        if not config or not config.get("enabled", True):
            raise ControllerError(f"算法未启用或不存在: {self.algorithm}")
        return config

    def _setup_scripts(self) -> list[Path]:
        entry = self._algorithm_entry()
        values = list(self.manifest.get("dataset", {}).get("setup_scripts", [])) + list(entry.get("setup_scripts", []))
        scripts: list[Path] = []
        seen: set[str] = set()
        for value in values:
            path = resolve_path(str(value)).resolve()
            if str(path) not in seen:
                scripts.append(path)
                seen.add(str(path))
        missing = [str(path) for path in scripts if not path.is_file()]
        if missing:
            raise ControllerError("setup script 不存在: " + ", ".join(missing))
        return scripts

    def _environment(self, output: Path) -> dict[str, str]:
        environment = os.environ.copy()
        environment.setdefault("ROS_DOMAIN_ID", os.environ.get("LIO_BENCHMARK_ROS_DOMAIN_ID", "77"))
        environment["ROS_LOG_DIR"] = str(output / "ros_logs")
        entry = self._algorithm_entry()
        environment["LIO_BENCHMARK_ALGORITHM_WORKSPACE"] = str(entry.get("workspace", ""))
        for key, value in entry.get("environment", {}).items():
            if not key.startswith("LIO_BENCHMARK_") or not key.replace("_", "").isalnum():
                raise ControllerError(f"非法 benchmark 环境变量: {key}")
            environment[key] = str(value)
        return environment

    def _shell_script(self, command: list[str], *, prelude: list[str] | None = None) -> str:
        lines = ["set -e"]
        lines.extend(f"source {shlex.quote(str(path))}" for path in self._setup_scripts())
        if prelude:
            lines.extend(prelude)
        lines.append("exec " + shlex.join(command))
        return "\n".join(lines)

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _spawn(self, name: str, script: str, output: Path, stderr: Path | None = None) -> Any:
        stdout_path = output
        stderr_path = stderr or output
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout = stdout_path.open("a", encoding="utf-8", buffering=1)
        error = stderr_path.open("a", encoding="utf-8", buffering=1) if stderr_path != stdout_path else stdout
        self._log_handles.extend([stdout] if error is stdout else [stdout, error])
        self._log_paths[name] = stdout_path
        environment = self._environment(self._output_dir or self.run_dir)
        process = self._popen(
            ["bash", "-lc", script],
            cwd=str(REPO_ROOT),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=error,
            start_new_session=True,
        )
        self._processes[name] = process
        return process

    def _allocate_output_dir(self) -> Path:
        base = self.run_dir / "raw" / self.algorithm
        base.mkdir(parents=True, exist_ok=True)
        if any(base.iterdir()):
            suffix = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            candidate = base / f"attempt_{suffix}_{os.getpid()}"
            index = 1
            while candidate.exists():
                candidate = base / f"attempt_{suffix}_{os.getpid()}_{index}"
                index += 1
            candidate.mkdir(parents=True)
            return candidate
        return base

    def _output_topics(self) -> list[str]:
        return {
            "kiss_icp": ["/kiss/odometry", "/kiss/trajectory"],
            "mola_lo": ["/tf", "/lidar_odometry/metadata", "/diagnostics"],
            "mola_lio": ["/tf", "/lidar_odometry/metadata", "/diagnostics"],
            "fast_livo2": ["/aft_mapped_to_init", "/path"],
            "point_lio": ["/aft_mapped_to_init"],
            "dlio": ["/odom"],
            "glim_odometry": ["/glim_ros/odom", "/glim_ros/odom_scanend", "/glim_ros/odom_corrected", "/glim_ros/odom_scanend_corrected"],
            "glim_full_slam": ["/glim_ros/odom", "/glim_ros/odom_scanend", "/glim_ros/odom_corrected", "/glim_ros/odom_scanend_corrected"],
            "lio_sam_no_loop": ["/lio_sam/mapping/odometry", "/lio_sam/imu/odometry", "/lio_sam/mapping/path"],
            "lio_sam_loop": ["/lio_sam/mapping/odometry", "/lio_sam/imu/odometry", "/lio_sam/mapping/path"],
        }[self.algorithm]

    def _topic(self, key: str, default: str = "") -> str:
        return str(self.manifest.get("dataset", {}).get("adapter_topics", {}).get(key, default))

    def _make_commands(self) -> tuple[list[tuple[str, str, Path, Path | None]], str, list[str]]:
        """Build adapter, node, recorder and playback shell commands."""
        entry = self._algorithm_entry()
        config = self._algorithm_config()
        dataset = self.manifest["dataset"]
        lidar_topic = str(dataset["lidar_topic"])
        imu_topic = str(dataset["imu_topic"])
        cloud_topic = self._topic("pointcloud2", "/lio_benchmark/points")
        imu_si_topic = self._topic("imu_si", "/lio_benchmark/imu_si")
        lio_sam_topic = self._topic("lio_sam_points", "/lio_benchmark/lio_sam_points")
        adapters: list[tuple[str, str, Path, Path | None]] = []
        command: list[str]
        prelude: list[str] = []
        algorithm = self.algorithm
        adapter_path = dataset.get("cloud_adapter", {}).get("required_executable")

        def add_cloud(destination: str) -> None:
            if not adapter_path:
                raise ControllerError("manifest 缺少 dataset.cloud_adapter.required_executable")
            adapters.append(
                (
                    "cloud_adapter",
                    self._shell_script(
                        [str(resolve_path(str(adapter_path))), "--ros-args", "-p", f"input_topic:={lidar_topic}", "-p", f"output_topic:={destination}", "-p", "sort_by_time:=true", "-p", f"metrics_path:={self._output_dir / 'input_validation.json'}"]
                    ),
                    self._output_dir / "cloud_adapter.log",
                    None,
                )
            )

        def add_imu() -> None:
            adapters.append(
                (
                    "imu_scaler",
                    self._shell_script(
                        [sys.executable, str(REPO_ROOT / "evaluators/scale_imu_acceleration.py"), "--ros-args", "-p", f"input_topic:={imu_topic}", "-p", f"output_topic:={imu_si_topic}", "-p", "acceleration_scale:=9.80665", "-p", "output_frame_id:=livox_imu"]
                    ),
                    self._output_dir / "imu_scaler.log",
                    None,
                )
            )

        if algorithm == "kiss_icp":
            add_cloud(cloud_topic)
            command = [str(entry["required_executables"][0]), "--ros-args", "--params-file", str(config), "-p", "use_sim_time:=true", "-p", "publish_odom_tf:=false", "-r", f"pointcloud_topic:={cloud_topic}"]
        elif algorithm in {"mola_lo", "mola_lio"}:
            add_cloud(cloud_topic)
            if algorithm == "mola_lio":
                add_imu()
            prelude.append("mola_pipeline=\"$(ros2 pkg prefix mola_lidar_odometry)/share/mola_lidar_odometry/pipelines/lidar3d-gicp.yaml\"")
            args = ["lidar_topic_name:=" + cloud_topic, "use_sim_time:=true", "use_mola_gui:=False", "use_rviz:=False", "ignore_lidar_pose_from_tf:=true", "publish_localization_following_rep105:=False", "mola_tf_base_link:=livox_frame", "min_nearby_poses_occupied:=2", "simplemap_min_nearby_poses:=2", "mola_lo_pipeline:=$mola_pipeline"]
            if algorithm == "mola_lio":
                prelude.extend(["export IMU_POSE_X=-0.011 IMU_POSE_Y=-0.02329 IMU_POSE_Z=0.04412", "export IMU_POSE_YAW=0 IMU_POSE_PITCH=0 IMU_POSE_ROLL=0"])
                args.extend(["imu_topic_name:=" + imu_si_topic, "use_imu_for_lio:=True", "imu_gravity_correction:=true", "mola_deskew_method:=MotionCompensationMethod::IMU", "ignore_imu_pose_from_tf:=true"])
            else:
                args.extend(["use_imu_for_lio:=False", "imu_gravity_correction:=false", "mola_deskew_method:=MotionCompensationMethod::Linear"])
            command = ["ros2", "launch", "mola_lidar_odometry", "ros2-lidar-odometry.launch.py", *args]
        elif algorithm in {"fast_livo2", "point_lio"}:
            if algorithm == "point_lio":
                add_cloud(cloud_topic)
            command = [str(entry["required_executables"][0]), "--ros-args", "--params-file", str(config), "-p", "use_sim_time:=true"]
        elif algorithm == "dlio":
            add_cloud(cloud_topic)
            add_imu()
            command = [str(entry["required_executables"][0]), "--ros-args", "--params-file", str(config / "dlio.yaml"), "--params-file", str(config / "params.yaml"), "-p", "use_sim_time:=true", "-r", f"pointcloud:={cloud_topic}", "-r", f"imu:={imu_si_topic}"]
        elif algorithm in {"glim_odometry", "glim_full_slam"}:
            add_cloud(cloud_topic)
            add_imu()
            prelude.append(f"python3 {shlex.quote(str(REPO_ROOT / 'evaluators/prepare_glim_config.py'))} {shlex.quote(str(config / 'config.yaml'))} {shlex.quote(str(self._output_dir / 'config'))}")
            dump = self._output_dir / "dump"
            command = [str(entry["required_executables"][0]), "--ros-args", "-p", "use_sim_time:=true", "-p", f"config_path:={self._output_dir / 'config'}", "-p", f"dump_path:={dump}"]
        elif algorithm in {"lio_sam_no_loop", "lio_sam_loop"}:
            add_cloud(lio_sam_topic)
            add_imu()
            command = ["ros2", "launch", str(REPO_ROOT / "evaluators/launch/lio_sam_headless.launch.py"), f"params_file:={config}"]
        else:
            raise ControllerError(f"unsupported algorithm: {algorithm}")

        node_script = self._shell_script(command, prelude=prelude)
        # shlex.join quotes the '$' in this one ROS parameter.  It is a shell
        # variable by design because the MOLA prefix is discovered after setup.
        node_script = node_script.replace("'mola_lo_pipeline:=$mola_pipeline'", "mola_lo_pipeline:=$mola_pipeline")
        node = ("algorithm", node_script, self._output_dir / "stdout.log", self._output_dir / "stderr.log")
        recorder_command = ["ros2", "bag", "record", "-o", str(self._output_dir / "trajectory"), *self._output_topics()]
        recorder = ("recorder", self._shell_script(recorder_command), self._output_dir / "record.log", None)
        playback_command = ["ros2", "bag", "play", str(self.bag_dir), "--rate", str(self.manifest.get("playback_rate", 1.0)), "--clock", "--disable-keyboard-controls", "--topics", lidar_topic, imu_topic]
        playback_script = self._shell_script(playback_command)
        self._atomic_text(self._output_dir / "actual_node_command.txt", node_script + "\n")
        self._atomic_text(self._output_dir / "actual_play_command.txt", playback_script + "\n")
        return adapters + [node, recorder], playback_script, self._output_topics()

    def _prepare_static_files(self) -> None:
        config = self._algorithm_config()
        destination = self._output_dir / "actual_config"
        if config.is_dir():
            shutil.copytree(config, destination)
        else:
            shutil.copy2(config, destination)
        atomic_write_json(self._output_dir / "controller.json", {"algorithm": self.algorithm, "bag_dir": str(self.bag_dir), "prepared_at": now(), "output_dir": str(self._output_dir)})
        if self.algorithm == "fast_livo2":
            source = self.manifest.get("dataset", {}).get("pre_run_input_validation")
            if source:
                source_path = resolve_path(str(source))
                if source_path.is_file():
                    try:
                        atomic_write_json(self._output_dir / "input_validation.json", json.loads(source_path.read_text(encoding="utf-8")))
                    except (OSError, json.JSONDecodeError):
                        pass

    def _set_phase(self, phase: str, event: str | None = None) -> None:
        self._phase = phase
        self._phase_started_at = now()
        heartbeat_run_status(self.run_dir, self.algorithm, "running" if self._state == "playing" else "not_started", phase=phase, phase_started_at=self._phase_started_at, current_process=self._process_snapshot(), event=event)

    def _process_snapshot(self) -> dict[str, Any]:
        pids: list[int] = []
        for process in self._processes.values():
            pid = getattr(process, "pid", None)
            if pid:
                pids.append(int(pid))
        if not pids:
            return {"pid": None, "cpu_percent": 0.0, "rss_bytes": 0, "threads": 0}
        live = self._read_resource().get("latest")
        algorithm_pid = getattr(self._processes.get("algorithm"), "pid", pids[0])
        if live:
            return {
                "pid": algorithm_pid,
                "cpu_percent": round(float(live.get("cpu_percent", 0.0)), 2),
                "rss_bytes": int(live.get("rss_bytes", 0)),
                "threads": int(live.get("threads", 0)),
            }
        try:
            import psutil

            processes = []
            for pid in pids:
                try:
                    root = psutil.Process(pid)
                    processes.extend([root, *root.children(recursive=True)])
                except psutil.Error:
                    continue
            if not processes:
                return {"pid": pids[0], "cpu_percent": 0.0, "rss_bytes": 0, "threads": 0}
            return {
                "pid": algorithm_pid,
                "cpu_percent": round(sum(process.cpu_percent(None) for process in processes), 2),
                "rss_bytes": sum(process.memory_info().rss for process in processes),
                "threads": sum(process.num_threads() for process in processes),
            }
        except (ImportError, OSError):
            return {"pid": pids[0], "cpu_percent": 0.0, "rss_bytes": 0, "threads": 0}

    def _latest_log_event(self) -> str | None:
        lines: list[str] = []
        for path in self._log_paths.values():
            try:
                lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines()[-3:])
            except OSError:
                continue
        return lines[-1][-300:] if lines else None

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(1.0):
            try:
                heartbeat_run_status(self.run_dir, self.algorithm, "running" if self._state == "playing" else "not_started", phase=self._phase, phase_started_at=self._phase_started_at, current_process=self._process_snapshot(), event=self._latest_log_event())
            except (OSError, ValueError, json.JSONDecodeError):
                pass

    def _start_heartbeat(self) -> None:
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="lio-status-heartbeat", daemon=True)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread and self._heartbeat_thread is not threading.current_thread():
            self._heartbeat_thread.join(timeout=2.0)
        self._heartbeat_thread = None

    def _poll(self, process: Any) -> int | None:
        try:
            return process.poll()
        except AttributeError:
            return None

    def _terminate(self, name: str, sig: int = signal.SIGINT, timeout_s: float = 10.0) -> int | None:
        process = self._processes.get(name)
        if process is None:
            return None
        if self._poll(process) is None:
            pid = getattr(process, "pid", None)
            if pid:
                try:
                    os.killpg(os.getpgid(pid), sig)
                except (ProcessLookupError, PermissionError, OSError):
                    try:
                        process.send_signal(sig)
                    except (AttributeError, OSError):
                        pass
            deadline = time.monotonic() + timeout_s
            while self._poll(process) is None and time.monotonic() < deadline:
                try:
                    process.wait(timeout=0.2)
                except (subprocess.TimeoutExpired, TimeoutError):
                    pass
                except (ChildProcessError, OSError):
                    break
            if self._poll(process) is None:
                pid = getattr(process, "pid", None)
                if pid:
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                try:
                    process.kill()
                except (AttributeError, OSError):
                    pass
                try:
                    process.wait(timeout=2)
                except (Exception,):
                    pass
        return self._poll(process)

    def _check_processes_started(self) -> None:
        for name, process in self._processes.items():
            if name in {"resource_monitor", "recorder"}:
                continue
            if self._poll(process) is not None:
                raise ControllerError(f"{name} 在准备阶段退出，returncode={self._poll(process)}")

    def prepare(self) -> dict[str, Any]:
        with self._operation_lock:
            if self._state not in {"idle", "finished", "failed"}:
                raise ControllerError(f"当前状态不能准备: {self._state}")
            if not self.run_dir.is_dir():
                raise ControllerError(f"run 目录不存在: {self.run_dir}")
            if self.algorithm not in self.manifest.get("algorithms", {}):
                raise ControllerError(f"算法不在 manifest 中: {self.algorithm}")
            status = load_run_status(self.run_dir)
            existing_result = status.get("algorithms", {}).get(self.algorithm, {}).get("result", {})
            if existing_result.get("status") == "SUCCESS":
                smoke_duration = existing_result.get("duration_s", existing_result.get("smoke_duration_s"))
                if smoke_duration is None:
                    raise ControllerError(f"算法已有完整成功结果，不覆盖: {self.algorithm}")
            self._processes = {}
            self._log_paths = {}
            self._failure_code = None
            self._failure_reason = None
            self._playback_exit_code = None
            self._playback_expected_timeout = False
            self._final_result = None
            self._bag_process = None
            self.bag_dir
            if not self.bag_dir.exists():
                raise ControllerError(f"bag 目录不存在: {self.bag_dir}")
            self._output_dir = self._allocate_output_dir()
            (self._output_dir / "ros_logs").mkdir(parents=True, exist_ok=True)
            self._prepare_static_files()
            self._state = "preparing"
            self._set_phase("preparing", "开始准备算法、适配器和录包器")
            update_run_status(self.run_dir, self.algorithm, "running", "not_started", phase="preparing", event="manual prepare started")
            self._start_heartbeat()
            try:
                commands, playback_script, _ = self._make_commands()
                self._playback_script = playback_script
                for name, script, stdout, stderr in commands:
                    if name == "algorithm":
                        continue
                    if name == "recorder":
                        continue
                    self._spawn(name, script, stdout, stderr)
                self._sleep(min(1.0, self.startup_timeout_s))
                self._check_processes_started()
                node = next(item for item in commands if item[0] == "algorithm")
                self._spawn(node[0], node[1], node[2], node[3])
                interval = os.environ.get("LIO_BENCHMARK_RESOURCE_INTERVAL_S", str(self.manifest.get("resource_monitor_interval_s", 1.0)))
                monitor_script = self._shell_script([sys.executable, str(REPO_ROOT / "evaluators/resource_monitor.py"), str(self._processes["algorithm"].pid), "--output", str(self._output_dir / "resource_monitor.json"), "--interval", interval])
                self._spawn("resource_monitor", monitor_script, self._output_dir / "resource_monitor.log")
                deadline = time.monotonic() + self.startup_timeout_s
                while time.monotonic() < deadline:
                    self._check_processes_started()
                    self._sleep(0.25)
                recorder = next(item for item in commands if item[0] == "recorder")
                self._spawn(recorder[0], recorder[1], recorder[2], recorder[3])
                self._sleep(1.0)
                if self._poll(self._processes["recorder"]) is not None:
                    raise ControllerError(f"recorder 在准备阶段退出，returncode={self._poll(self._processes['recorder'])}")
                self._state = "prepared"
                self._set_phase("prepared", "算法、输入适配器、资源监控和 recorder 已就绪，等待播放")
                return self.snapshot()
            except Exception as exc:
                self._failure_code = "RUNTIME_CRASH"
                self._failure_reason = str(exc)
                self._finalize(bag_state="failed", forced_status="RUNTIME_CRASH", reason=str(exc))
                raise

    def play(self) -> dict[str, Any]:
        if self._state != "prepared":
            raise ControllerError(f"当前状态不能播放: {self._state}")
        self._state = "playing"
        self._stop_requested.clear()
        self._set_phase("playback", "开始播放 bag")
        update_run_status(self.run_dir, self.algorithm, "running", "running", phase="playback", event="manual bag playback started")
        playback_log = self._output_dir / "play.log"
        self._bag_process = self._spawn("bag_play", self._playback_script, playback_log)
        started = time.monotonic()
        while self._poll(self._bag_process) is None:
            if self._stop_requested.is_set():
                break
            if self.duration_s is not None and time.monotonic() - started >= self.duration_s:
                self._playback_expected_timeout = True
                self._terminate("bag_play", signal.SIGINT, 5.0)
                break
            if self._poll(self._processes.get("algorithm")) is not None:
                self._failure_code = "RUNTIME_CRASH"
                self._failure_reason = "算法进程在 bag 播放期间退出"
                self._terminate("bag_play", signal.SIGINT, 5.0)
                break
            self._sleep(0.25)
        self._playback_exit_code = self._poll(self._bag_process)
        stopped = self._stop_requested.is_set()
        bag_state = "stopped" if stopped else ("completed" if self._playback_exit_code in (0, None) or self._playback_expected_timeout else "failed")
        return self._finalize(bag_state=bag_state, reason="用户停止并保存" if stopped else self._failure_reason)

    def stop_and_save(self) -> dict[str, Any]:
        self._stop_requested.set()
        if self._state in {"prepared", "playing", "preparing"}:
            if self._bag_process is not None and self._poll(self._bag_process) is None:
                self._terminate("bag_play", signal.SIGINT, 5.0)
            return self._finalize(bag_state="stopped", reason="用户停止并保存")
        return self._final_result or self.snapshot()

    def _read_trajectory_messages(self, metadata: Path) -> int:
        try:
            import yaml

            data = yaml.safe_load(metadata.read_text(encoding="utf-8")) or {}
            return int(data["rosbag2_bagfile_information"]["message_count"])
        except (OSError, KeyError, TypeError, ValueError):
            return -1

    def _read_resource(self) -> dict[str, Any]:
        if self._output_dir is None:
            return {}
        path = self._output_dir / "resource_monitor.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _validate_output(self) -> tuple[dict[str, Any], list[str], int]:
        metadata = self._output_dir / "trajectory" / "metadata.yaml"
        errors: list[str] = []
        if not metadata.is_file():
            errors.append("trajectory/metadata.yaml 不存在")
            messages = -1
        else:
            messages = self._read_trajectory_messages(metadata)
            if messages < 0:
                errors.append("trajectory metadata.yaml 格式无效")
            elif messages == 0:
                errors.append("轨迹消息数为 0")
            try:
                check = self._run(["ros2", "bag", "info", str(self._output_dir / "trajectory")], cwd=str(REPO_ROOT), env=self._environment(self._output_dir), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60, start_new_session=True)
                if getattr(check, "returncode", 1) != 0:
                    errors.append("ros2 bag info 无法读取轨迹 bag: " + getattr(check, "stderr", "").strip()[-500:])
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(f"ros2 bag info 检查失败: {exc}")
        validation_path = self._output_dir / "input_validation.json"
        try:
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            if not isinstance(validation, dict):
                raise ValueError("顶层不是对象")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"input_validation.json 无效: {exc}")
        resource_path = self._output_dir / "resource_monitor.json"
        resource = self._read_resource()
        if not resource_path.is_file() or resource.get("status") != "finished":
            errors.append("resource_monitor.json 未成功写入最终汇总")
        return {"metadata": metadata.is_file(), "bag_readable": metadata.is_file() and not any("ros2 bag info" in error for error in errors), "input_validation": validation_path.is_file(), "resource_monitor": resource_path.is_file(), "errors": errors}, errors, messages

    def _finalize(self, *, bag_state: str, forced_status: str | None = None, reason: str | None = None) -> dict[str, Any]:
        if not self._finalize_lock.acquire(blocking=False):
            return self._final_result or self.snapshot()
        try:
            self._state = "finalizing"
            self._stop_heartbeat()
            if self._bag_process is not None and self._poll(self._bag_process) is None:
                self._terminate("bag_play", signal.SIGINT, 5.0)
            if "recorder" in self._processes:
                self._terminate("recorder", signal.SIGINT, self.settle_timeout_s)
            for name in ("algorithm", "cloud_adapter", "imu_scaler"):
                self._terminate(name, signal.SIGTERM, 10.0)
            if "resource_monitor" in self._processes:
                deadline = time.monotonic() + 3.0
                while self._poll(self._processes["resource_monitor"]) is None and time.monotonic() < deadline:
                    self._sleep(0.2)
                self._terminate("resource_monitor", signal.SIGTERM, 2.0)
            for name in list(self._processes):
                if self._poll(self._processes[name]) is None:
                    self._terminate(name, signal.SIGTERM, 2.0)
            if self._output_dir and not any(name in self._processes for name in ("cloud_adapter", "imu_scaler")):
                source = self.manifest.get("dataset", {}).get("pre_run_input_validation")
                if source and not (self._output_dir / "input_validation.json").is_file():
                    path = resolve_path(str(source))
                    if path.is_file():
                        try:
                            atomic_write_json(self._output_dir / "input_validation.json", json.loads(path.read_text(encoding="utf-8")))
                        except (OSError, json.JSONDecodeError):
                            pass
            self._log_handles_close()
            validation, validation_errors, messages = self._validate_output()
            process_rc = self._poll(self._processes.get("algorithm"))
            if forced_status:
                result_status = forced_status
            elif messages == 0:
                result_status = "NO_ODOMETRY"
            elif validation_errors:
                result_status = "SAVE_FAILED"
            elif self._failure_code:
                result_status = self._failure_code
            elif process_rc not in (None, 0, -signal.SIGINT, -signal.SIGTERM):
                result_status = "RUNTIME_CRASH"
            else:
                result_status = "SUCCESS"
            final_reason = reason or self._failure_reason or ("; ".join(validation_errors) if validation_errors else None)
            resource = self._read_resource()
            result = {
                "algorithm": self.algorithm,
                "status": result_status,
                "reason": final_reason,
                "bag_playback": bag_state,
                "bag_play_exit_code": self._playback_exit_code,
                "algorithm_exit_code": process_rc,
                "playback_rate": self.manifest.get("playback_rate", 1.0),
                "duration_s": self.duration_s,
                "trajectory_messages": max(0, messages),
                "output_dir": str(self._output_dir),
                "validation": validation,
                "resource": resource,
                "finished_at": now(),
            }
            atomic_write_json(self._output_dir / "run_result.json", result)
            self._final_result = result
            self._state = "finished" if result_status == "SUCCESS" else "failed"
            update_run_status(self.run_dir, self.algorithm, "completed" if result_status == "SUCCESS" else "failed", bag_state, str(self._output_dir / "run_result.json"), final_reason, phase="completed" if result_status == "SUCCESS" else "failed", current_process={"pid": None, "cpu_percent": 0.0, "rss_bytes": 0, "threads": 0}, event=f"manual finalize: {result_status}")
            return result
        finally:
            self._finalize_lock.release()

    def _log_handles_close(self) -> None:
        for stream in self._log_handles:
            try:
                stream.close()
            except OSError:
                pass
        self._log_handles.clear()

    def cleanup(self) -> None:
        """Best-effort process-group cleanup for callers handling their own result."""
        self._stop_requested.set()
        for name in list(self._processes):
            self._terminate(name, signal.SIGTERM, 2.0)
        self._stop_heartbeat()
        self._log_handles_close()

    def trajectory_snapshot(self) -> dict[str, Any]:
        output = self._output_dir or self.run_dir / "raw" / self.algorithm
        metadata = output / "trajectory" / "metadata.yaml"
        files = [path for path in (output / "trajectory").glob("*") if path.is_file()] if (output / "trajectory").is_dir() else []
        return {"output_dir": str(output), "metadata_exists": metadata.is_file(), "bytes": sum(path.stat().st_size for path in files if path.exists()), "messages": self._read_trajectory_messages(metadata) if metadata.is_file() else 0, "saved": (output / "run_result.json").is_file()}

    def snapshot(self) -> dict[str, Any]:
        status = load_run_status(self.run_dir)
        status["controller_state"] = self._state
        status["trajectory_snapshot"] = self.trajectory_snapshot()
        resource = self._read_resource()
        status["resource_snapshot"] = resource.get("latest")
        status["resource_summary"] = resource
        status["latest_logs"] = self.latest_log_lines(12)
        return status

    @staticmethod
    def _tail_lines(path: Path, limit: int = 20, chunk_size: int = 64 * 1024) -> list[str]:
        """Read only the end of a log file; never load a multi-GB log in full."""
        if limit <= 0 or not path.is_file():
            return []
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            position = stream.tell()
            data = b""
            while position > 0 and data.count(b"\n") <= limit:
                size = min(chunk_size, position)
                position -= size
                stream.seek(position)
                data = stream.read(size) + data
        return data.decode("utf-8", errors="replace").splitlines()[-limit:]

    def latest_log_lines(self, limit: int = 20) -> list[str]:
        paths = list(self._log_paths.values())
        if self._output_dir:
            paths.extend(self._output_dir.glob("*.log"))
        lines: list[str] = []
        for path in dict.fromkeys(paths):
            try:
                lines.extend(f"[{path.name}] {line}" for line in self._tail_lines(path, limit))
            except OSError:
                continue
        return lines[-limit:]

    def can_generate_map(self) -> bool:
        status = load_run_status(self.run_dir)
        entry = status.get("algorithms", {}).get("fast_livo2", {})
        return entry.get("result", {}).get("status") == "SUCCESS" and (self.run_dir / "standardized" / "trajectories" / "fast_livo2.csv").is_file()

    def generate_report(self, *, include_map: bool = True) -> dict[str, Any]:
        preliminary_script = REPO_ROOT / "evaluators/generate_experiment_report.py"
        preliminary = self._run([sys.executable, str(preliminary_script), "--run", str(self.run_dir)], cwd=str(REPO_ROOT), env=self._environment(self.run_dir), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3600, start_new_session=True)
        if getattr(preliminary, "returncode", 1) != 0:
            raise ControllerError("初步实验报告生成失败: " + getattr(preliminary, "stderr", "").strip()[-1000:])
        summary_script = REPO_ROOT / "evaluators/summarize_smoke_run.py"
        report_command = [sys.executable, str(summary_script), str(self.run_dir), "--name", "manual_comparison"]
        summary = self._run(report_command, cwd=str(REPO_ROOT), env=self._environment(self.run_dir), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3600, start_new_session=True)
        if getattr(summary, "returncode", 1) != 0:
            raise ControllerError("标准化/对比报告失败: " + getattr(summary, "stderr", "").strip()[-1000:])
        result: dict[str, Any] = {
            "preliminary": str(self.run_dir / "reports" / "preliminary_experiment_report.md"),
            "summary": str(self.run_dir / "reports" / "manual_comparison.md"),
        }
        if include_map and self.can_generate_map():
            map_script = REPO_ROOT / "evaluators/visualize_baseline_maps.py"
            map_result = self._run([sys.executable, str(map_script), "--run", str(self.run_dir)], cwd=str(REPO_ROOT), env=self._environment(self.run_dir), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3600, start_new_session=True)
            if getattr(map_result, "returncode", 1) != 0:
                raise ControllerError("FAST-LIVO2 基准地图生成失败: " + getattr(map_result, "stderr", "").strip()[-1000:])
            result["baseline_map"] = str(self.run_dir / "figures" / "fast_livo2_baseline_maps")
        else:
            result["baseline_map"] = None
        return result


class RunQueueWorker:
    """Run selected algorithms serially and persist queue progress."""

    def __init__(
        self,
        run_dir: Path,
        algorithms: list[str],
        *,
        bag_dir: Path | None = None,
        duration_s: float | None = None,
        controller_factory: Callable[..., ManualRunController] = ManualRunController,
    ) -> None:
        self.run_dir = Path(run_dir).expanduser().resolve()
        self.algorithms = list(dict.fromkeys(algorithms))
        self.bag_dir = bag_dir
        self.duration_s = duration_s
        self.controller_factory = controller_factory
        self._lock = threading.RLock()
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_controller: ManualRunController | None = None
        self._state = "idle"
        self._current: str | None = None
        self._index = -1
        self._results: dict[str, dict[str, Any]] = {}
        self._event = ""
        self._updated_at = now()
        self._persist()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def current_controller(self) -> ManualRunController | None:
        with self._lock:
            return self._current_controller

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _persist(self) -> None:
        with self._lock:
            self._updated_at = now()
            atomic_write_json(
                self.run_dir / "metadata" / "run_queue.json",
                {
                    "state": self._state,
                    "algorithms": self.algorithms,
                    "index": self._index,
                    "current_algorithm": self._current,
                    "results": self._results,
                    "event": self._event,
                    "updated_at": self._updated_at,
                },
            )

    def _set(self, *, state: str | None = None, current: str | None = None, event: str | None = None) -> None:
        with self._lock:
            if state is not None:
                self._state = state
            self._current = current
            if event is not None:
                self._event = event
        self._persist()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "algorithms": list(self.algorithms),
                "index": self._index,
                "current_algorithm": self._current,
                "results": dict(self._results),
                "event": self._event,
                "updated_at": self._updated_at,
            }

    def start(self) -> None:
        with self._lock:
            if self.is_running():
                raise ControllerError("运行队列已经在执行")
            if not self.algorithms:
                raise ControllerError("运行队列为空")
            self._stop_requested.clear()
            self._index = -1
            self._results = {}
            self._state = "queued"
            self._event = "队列已启动，等待第一个算法"
        self._persist()
        self._thread = threading.Thread(target=self._run, name="lio-benchmark-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_requested.set()
        controller = self.current_controller
        if controller is not None:
            controller.stop_and_save()
        self._set(state="stopping", current=self._current, event="收到停止队列请求")

    def _result_after_exception(self, algorithm: str, exc: Exception) -> dict[str, Any]:
        try:
            entry = load_run_status(self.run_dir).get("algorithms", {}).get(algorithm, {})
            result = entry.get("result")
            if isinstance(result, dict) and result.get("status"):
                return result
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return {"algorithm": algorithm, "status": "RUNTIME_CRASH", "reason": str(exc)}

    def _run(self) -> None:
        stopped = False
        for index, algorithm in enumerate(self.algorithms):
            if self._stop_requested.is_set():
                stopped = True
                break
            with self._lock:
                self._index = index
                self._current = algorithm
                self._state = "preparing"
                self._event = f"正在准备 {algorithm}"
            self._persist()
            try:
                controller = self.controller_factory(self.run_dir, algorithm, bag_dir=self.bag_dir, duration_s=self.duration_s)
            except Exception as exc:
                result = self._result_after_exception(algorithm, exc)
                with self._lock:
                    self._results[algorithm] = result
                    self._event = f"{algorithm} 准备失败: {result.get('status', 'RUNTIME_CRASH')}"
                self._persist()
                continue
            with self._lock:
                self._current_controller = controller
            try:
                controller.prepare()
                if self._stop_requested.is_set():
                    stopped = True
                    result = controller.stop_and_save()
                else:
                    with self._lock:
                        self._state = "playing"
                        self._event = f"正在播放 {algorithm}"
                    self._persist()
                    result = controller.play()
            except Exception as exc:
                result = self._result_after_exception(algorithm, exc)
                try:
                    if not result.get("status") or result.get("status") == "RUNTIME_CRASH":
                        result = controller.stop_and_save()
                except Exception:
                    pass
            with self._lock:
                self._results[algorithm] = result
                self._current_controller = None
                self._event = f"{algorithm} 完成: {result.get('status', 'UNKNOWN')}"
            self._persist()
            controller.cleanup()
            if stopped:
                break
        with self._lock:
            self._state = "stopped" if (stopped or self._stop_requested.is_set()) else "completed"
            self._current = None
            self._current_controller = None
            self._event = "队列已停止" if self._state == "stopped" else "队列全部完成"
        self._persist()


def _cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LIO benchmark manual lifecycle controller")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithm", required=True)
    parser.add_argument("--bag", type=Path)
    parser.add_argument("--duration", type=float)
    parser.add_argument("command", choices=("prepare", "run", "status", "report"))
    parser.add_argument("--auto-play", action="store_true", help="run command: start playback immediately")
    return parser


def main() -> int:
    args = _cli_parser().parse_args()
    if args.command == "status":
        print(json.dumps(load_run_status(args.run.resolve()), ensure_ascii=False, indent=2))
        return 0
    controller = ManualRunController(args.run, args.algorithm, bag_dir=args.bag, duration_s=args.duration)
    if args.command == "report":
        print(json.dumps(controller.generate_report(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "prepare":
        controller.prepare()
        print(json.dumps(controller.snapshot(), ensure_ascii=False, indent=2))
        try:
            while True:
                line = input("manual controller> ").strip().lower()
                if line in {"play", "p"}:
                    print(json.dumps(controller.play(), ensure_ascii=False, indent=2))
                    return 0
                if line in {"stop", "s", "quit", "q"}:
                    print(json.dumps(controller.stop_and_save(), ensure_ascii=False, indent=2))
                    return 0
                print("commands: play, stop")
        except (EOFError, KeyboardInterrupt):
            print(json.dumps(controller.stop_and_save(), ensure_ascii=False, indent=2))
            return 0
    try:
        controller.prepare()
        result = controller.play()
    except (KeyboardInterrupt, EOFError):
        result = controller.stop_and_save()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "SUCCESS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
