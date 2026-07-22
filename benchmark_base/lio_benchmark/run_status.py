"""Atomic structured run status and human-readable Markdown projection.

The status files are intentionally useful while a long bag is running.  Writers
take a small advisory lock and replace complete files atomically, so the GUI
never has to parse a half-written JSON document.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - the benchmark currently targets Linux
    fcntl = None


TERMINAL_RESULT_STATES = {"SUCCESS"}
STATUS_ALGORITHM_STATES = {"running", "completed", "failed"}
STATUS_BAG_STATES = {"not_started", "running", "completed", "failed", "stopped"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def _atomic_write(path: Path, content: str) -> None:
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


def atomic_write_json(path: Path, value: Any) -> None:
    """Write JSON as a complete, durable file without exposing a partial file."""
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def _status_lock(run: Path) -> Iterator[None]:
    lock_path = run / "metadata" / "run_status.json.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stream = lock_path.open("a+", encoding="utf-8")
    try:
        if fcntl is not None:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _enabled_algorithms(manifest: dict[str, Any]) -> list[str]:
    return [name for name, config in manifest.get("algorithms", {}).items() if config.get("enabled", True)]


def _base_status(run: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    created_at = manifest.get("created_at") or now()
    algorithms = {name: {"state": "pending"} for name in _enabled_algorithms(manifest)}
    return {
        "run_id": manifest.get("run_id", run.name),
        "state": "initialized",
        "bag_playback": "not_started",
        "phase": "initialized",
        "phase_started_at": created_at,
        "current_algorithm": None,
        "last_algorithm": None,
        "created_at": created_at,
        "updated_at": created_at,
        "elapsed_s": 0.0,
        "phase_elapsed_s": 0.0,
        "current_process": {"pid": None, "cpu_percent": 0.0, "rss_bytes": 0, "threads": 0},
        "heartbeat": {"at": created_at, "interval_s": 1.0},
        "recent_event": "run initialized",
        "algorithms": algorithms,
        "events": [{"at": created_at, "state": "initialized", "bag_playback": "not_started", "event": "run initialized"}],
    }


def _parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _seconds_since(value: str | None, current: dt.datetime) -> float:
    parsed = _parse_time(value)
    if parsed is None:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return max(0.0, (current - parsed).total_seconds())


def _load_unlocked(run: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    path = run / "metadata" / "run_status.json"
    status = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else _base_status(run, manifest)
    for name in _enabled_algorithms(manifest):
        status.setdefault("algorithms", {}).setdefault(name, {"state": "pending"})
    status.setdefault("events", [])
    status.setdefault("phase", status.get("state", "initialized"))
    status.setdefault("phase_started_at", status.get("updated_at") or status.get("created_at") or now())
    status.setdefault("heartbeat", {})
    return status, manifest


def load_run_status(run: Path) -> dict[str, Any]:
    """Read a status snapshot, tolerating a status file from an older release."""
    status_path = run / "metadata" / "run_status.json"
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        return _base_status(run, manifest)


def _result(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _derive_state(status: dict[str, Any], manifest: dict[str, Any]) -> str:
    entries = [status["algorithms"][name] for name in _enabled_algorithms(manifest)]
    results = [entry.get("result") for entry in entries if entry.get("result")]
    if any(item.get("status") not in TERMINAL_RESULT_STATES for item in results):
        return "failed"
    if entries and all(entry.get("result") for entry in entries):
        return "completed"
    if any(entry.get("state") == "running" for entry in entries):
        return "running"
    if any(entry.get("result") for entry in entries):
        return "completed_partial"
    return "initialized"


def _refresh_elapsed(status: dict[str, Any], timestamp: str) -> None:
    current = _parse_time(timestamp) or dt.datetime.now(dt.timezone.utc)
    status["elapsed_s"] = round(_seconds_since(status.get("created_at"), current), 3)
    status["phase_elapsed_s"] = round(_seconds_since(status.get("phase_started_at"), current), 3)
    algorithm = status.get("current_algorithm")
    if algorithm and algorithm in status.get("algorithms", {}):
        entry = status["algorithms"][algorithm]
        entry["elapsed_s"] = round(_seconds_since(entry.get("started_at"), current), 3)


def render_markdown(status: dict[str, Any]) -> str:
    process = status.get("current_process") or {}
    lines = [
        f"# Run {status['run_id']}",
        "",
        f"- 状态：{status['state']}",
        f"- bag 回放：{status['bag_playback']}",
        f"- 当前阶段：{status.get('phase', '')}",
        f"- 当前算法：{status.get('current_algorithm') or '无'}",
        f"- 最近算法：{status.get('last_algorithm') or '无'}",
        f"- 创建时间：{status['created_at']}",
        f"- 更新时间：{status['updated_at']}",
        f"- 已运行：{status.get('elapsed_s', 0.0):.1f}s，阶段：{status.get('phase_elapsed_s', 0.0):.1f}s",
        f"- 当前进程：PID={process.get('pid')} CPU={process.get('cpu_percent', 0.0):.1f}% RSS={process.get('rss_bytes', 0)} bytes threads={process.get('threads', 0)}",
        f"- 最近事件：{status.get('recent_event', '')}",
        "",
        "## 算法状态",
        "",
        "| 算法 | 状态 | 结果 | 轨迹消息 | 开始 | 结束 |",
        "|---|---|---|---:|---|---|",
    ]
    for name, entry in status.get("algorithms", {}).items():
        result = entry.get("result") or {}
        lines.append(
            f"| {name} | {entry.get('state', 'pending')} | {result.get('status', '')} | "
            f"{result.get('trajectory_messages', '')} | {entry.get('started_at', '')} | {entry.get('finished_at', '')} |"
        )
    if status.get("events"):
        lines.extend(["", "## 最近事件", ""])
        for event in status["events"][-12:]:
            detail = " ".join(f"{key}={value}" for key, value in event.items() if key != "at")
            lines.append(f"- {event['at']} {detail}")
    return "\n".join(lines) + "\n"


def _write_status_unlocked(run: Path, status: dict[str, Any]) -> None:
    atomic_write_json(run / "metadata" / "run_status.json", status)
    _atomic_write(run / "RUN_STATUS.md", render_markdown(status))


def initialize_run_status(run: Path, manifest: dict[str, Any]) -> None:
    status = _base_status(run, manifest)
    with _status_lock(run):
        _write_status_unlocked(run, status)


def update_run_status(
    run: Path,
    algorithm: str,
    algorithm_state: str,
    bag_playback: str,
    result_path: str | Path | None = None,
    reason: str | None = None,
    *,
    phase: str | None = None,
    current_process: dict[str, Any] | None = None,
    event: str | None = None,
) -> dict[str, Any]:
    """Record a lifecycle transition while preserving the old public API."""
    if algorithm_state not in STATUS_ALGORITHM_STATES:
        raise ValueError(f"invalid algorithm state: {algorithm_state}")
    if bag_playback not in STATUS_BAG_STATES:
        raise ValueError(f"invalid bag playback state: {bag_playback}")
    with _status_lock(run):
        status, manifest = _load_unlocked(run)
        timestamp = now()
        result = _result(result_path)
        entry = status.setdefault("algorithms", {}).setdefault(algorithm, {"state": "pending"})
        previous_phase = status.get("phase")
        entry["state"] = algorithm_state
        if algorithm_state == "running":
            entry.setdefault("started_at", timestamp)
        else:
            entry["finished_at"] = timestamp
        if result is not None:
            entry["result"] = result
        if reason:
            entry["reason"] = reason
        elif algorithm_state == "completed" and result and result.get("status") == "SUCCESS":
            # A successful retry must not inherit a failure reason from an
            # earlier attempt stored in the same run directory.
            entry.pop("reason", None)
        if result and result.get("output_dir"):
            entry["output_dir"] = result["output_dir"]

        status["updated_at"] = timestamp
        status["heartbeat"] = {"at": timestamp, "interval_s": 1.0, "phase": phase or status.get("phase")}
        status["last_algorithm"] = algorithm
        status["current_algorithm"] = algorithm if algorithm_state == "running" else None
        status["bag_playback"] = bag_playback
        status["state"] = _derive_state(status, manifest)
        if phase:
            status["phase"] = phase
        if phase and phase != previous_phase:
            status["phase_started_at"] = timestamp
        if current_process is not None:
            status["current_process"] = current_process
        status["recent_event"] = event or reason or f"{algorithm}: {algorithm_state}/{bag_playback}"
        status.setdefault("events", []).append(
            {
                "at": timestamp,
                "algorithm": algorithm,
                "state": algorithm_state,
                "bag_playback": bag_playback,
                "event": status["recent_event"],
                **({"reason": reason} if reason else {}),
            }
        )
        status["events"] = status["events"][-200:]
        _refresh_elapsed(status, timestamp)
        _write_status_unlocked(run, status)
        return status


def heartbeat_run_status(
    run: Path,
    algorithm: str | None = None,
    bag_playback: str | None = None,
    *,
    phase: str | None = None,
    phase_started_at: str | None = None,
    current_process: dict[str, Any] | None = None,
    event: str | None = None,
) -> dict[str, Any]:
    """Write a lightweight live snapshot; safe to call once per second."""
    with _status_lock(run):
        status, manifest = _load_unlocked(run)
        timestamp = now()
        if algorithm:
            status["current_algorithm"] = algorithm
            status["last_algorithm"] = algorithm
            status.setdefault("algorithms", {}).setdefault(algorithm, {"state": "pending"})["state"] = "running"
        if bag_playback:
            status["bag_playback"] = bag_playback
        if phase:
            if phase != status.get("phase"):
                status["phase_started_at"] = phase_started_at or timestamp
            status["phase"] = phase
        elif phase_started_at:
            status["phase_started_at"] = phase_started_at
        status["updated_at"] = timestamp
        if current_process is not None:
            status["current_process"] = current_process
        if event:
            status["recent_event"] = event
        status["heartbeat"] = {"at": timestamp, "interval_s": 1.0, "phase": status.get("phase")}
        _refresh_elapsed(status, timestamp)
        _write_status_unlocked(run, status)
        return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--algorithm", required=True)
    parser.add_argument("--algorithm-state", choices=sorted(STATUS_ALGORITHM_STATES))
    parser.add_argument("--bag-playback", choices=sorted(STATUS_BAG_STATES), required=True)
    parser.add_argument("--result")
    parser.add_argument("--reason")
    parser.add_argument("--phase")
    parser.add_argument("--event")
    parser.add_argument("--heartbeat", action="store_true")
    args = parser.parse_args()
    if args.heartbeat:
        heartbeat_run_status(args.run.resolve(), args.algorithm, args.bag_playback, phase=args.phase, event=args.event)
    else:
        if not args.algorithm_state:
            parser.error("--algorithm-state is required unless --heartbeat is used")
        update_run_status(args.run.resolve(), args.algorithm, args.algorithm_state, args.bag_playback, args.result, args.reason, phase=args.phase, event=args.event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
