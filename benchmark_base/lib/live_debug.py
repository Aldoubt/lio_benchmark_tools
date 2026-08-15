#!/usr/bin/env python3
"""Generate inspectable manual live-debug sessions for ROS bag replay."""
from __future__ import annotations

import datetime as dt
import json
import shlex
from pathlib import Path
from typing import Any, Iterable

from .artifacts import write_json
from .registry import Registry


def _q(value: str | Path) -> str:
    return shlex.quote(str(value))


def _safe_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
    if not cleaned:
        raise ValueError("session id is empty after sanitization")
    return cleaned


def render_algorithm_script(algorithm: dict[str, Any]) -> str:
    live = algorithm.get("live_debug", {})
    setup = live.get("setup", [])
    processes = live.get("processes", [])
    if not isinstance(setup, list) or not isinstance(processes, list) or not processes:
        raise ValueError(f"algorithm {algorithm['algorithm_id']} has no live_debug process contract")
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)',
        'source "$SCRIPT_DIR/env.sh"',
        'mkdir -p "$SESSION_DIR/logs"',
        "pids=()",
        'cleanup() { for pid in "${pids[@]:-}"; do kill -INT "$pid" 2>/dev/null || true; done; }',
        "trap cleanup EXIT INT TERM",
        "",
    ]
    lines.extend(str(item) for item in setup)
    lines.append("")
    foreground_seen = False
    for process in processes:
        if not isinstance(process, dict) or not process.get("name") or not process.get("command"):
            raise ValueError(f"invalid live_debug process for {algorithm['algorithm_id']}")
        name = str(process["name"])
        command = str(process["command"])
        log = f'$SESSION_DIR/logs/{algorithm["algorithm_id"]}_{name}.log'
        if process.get("background", False):
            lines.append(f"{command} >\"{log}\" 2>&1 &")
            lines.append("pids+=(\"$!\")")
            if process.get("startup_delay_s") is not None:
                lines.append(f"sleep {float(process['startup_delay_s']):g}")
        else:
            if foreground_seen:
                raise ValueError(f"algorithm {algorithm['algorithm_id']} has multiple foreground processes")
            foreground_seen = True
            lines.append(f"{command} 2>&1 | tee \"{log}\"")
    if not foreground_seen:
        lines.append('echo "No foreground estimator process was defined" >&2')
        lines.append("wait")
    lines.append("")
    return "\n".join(lines)


def prepare_session(
    *,
    registry: Registry,
    dataset_id: str,
    algorithm_ids: Iterable[str],
    workspace: str | Path,
    session_root: str | Path,
    benchmark_root: str | Path,
    rate: float = 1.0,
    session_id: str | None = None,
    check_paths: bool = True,
) -> Path:
    if rate <= 0:
        raise ValueError("bag playback rate must be > 0")
    dataset = registry.load_dataset(dataset_id)
    algorithms = [registry.load_algorithm(item) for item in algorithm_ids]
    if not algorithms:
        raise ValueError("at least one live-debug algorithm is required")
    bag_dir = Path(dataset["bag_dir"]).expanduser()
    workspace = Path(workspace).expanduser()
    if check_paths:
        if not bag_dir.is_dir():
            raise ValueError(f"dataset bag_dir does not exist: {bag_dir}")
        if not (bag_dir / "metadata.yaml").is_file():
            raise ValueError(f"dataset bag_dir missing metadata.yaml: {bag_dir}")
        if not workspace.is_dir():
            raise ValueError(f"workspace does not exist: {workspace}")
    if session_id is None:
        session_id = f"{dataset_id}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    session_id = _safe_id(session_id)
    session = Path(session_root).expanduser() / session_id
    if session.exists():
        raise ValueError(f"live-debug session already exists: {session}")
    for relative in ("logs", "markers", "rviz"):
        (session / relative).mkdir(parents=True, exist_ok=False)

    output_topics: dict[str, list[str]] = {}
    namespace_ready = True
    for algorithm in algorithms:
        live = algorithm.get("live_debug", {})
        namespace_ready &= bool(live.get("namespace_capable", False))
        topics = [str(value) for value in algorithm.get("topics", {}).get("outputs", {}).values() if value]
        output_topics[algorithm["algorithm_id"]] = topics
    collisions: dict[str, list[str]] = {}
    owners: dict[str, list[str]] = {}
    for algorithm_id, topics in output_topics.items():
        for topic in topics:
            owners.setdefault(topic, []).append(algorithm_id)
    collisions = {topic: ids for topic, ids in owners.items() if len(ids) > 1}
    simultaneous_safe = namespace_ready and not collisions

    environment = "\n".join(
        (
            "#!/usr/bin/env bash",
            f"export BENCHMARK_ROOT={_q(Path(benchmark_root).resolve())}",
            f"export WORKSPACE={_q(workspace.resolve())}",
            f"export BAG_DIR={_q(bag_dir.resolve() if bag_dir.exists() else bag_dir)}",
            f"export SESSION_DIR={_q(session.resolve())}",
            'export ROS_LOG_DIR="$SESSION_DIR/logs/ros"',
            'mkdir -p "$ROS_LOG_DIR"',
            "",
        )
    )
    (session / "env.sh").write_text(environment, encoding="utf-8")
    (session / "env.sh").chmod(0o755)

    bag_script = "\n".join(
        (
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            'SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)',
            'source "$SCRIPT_DIR/env.sh"',
            "source /opt/ros/humble/setup.bash",
            'if [[ -f "$WORKSPACE/install/setup.bash" ]]; then source "$WORKSPACE/install/setup.bash"; fi',
            f'ros2 bag play "$BAG_DIR" --clock --rate {rate:g}',
            "",
        )
    )
    (session / "01_bag_play.sh").write_text(bag_script, encoding="utf-8")
    (session / "01_bag_play.sh").chmod(0o755)

    scripts: list[str] = []
    for index, algorithm in enumerate(algorithms, start=2):
        filename = f"{index:02d}_{algorithm['algorithm_id']}.sh"
        path = session / filename
        path.write_text(render_algorithm_script(algorithm), encoding="utf-8")
        path.chmod(0o755)
        scripts.append(filename)

    session_payload = {
        "schema": "lio_benchmark_live_session/v2",
        "session_id": session_id,
        "created_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "dataset": dataset,
        "algorithms": [algorithm["algorithm_id"] for algorithm in algorithms],
        "workspace": str(workspace),
        "bag_playback_rate": rate,
        "bag_script": "01_bag_play.sh",
        "algorithm_scripts": scripts,
        "simultaneous_safe": simultaneous_safe,
        "output_topic_collisions": collisions,
    }
    write_json(session / "session.json", session_payload)

    topic_lines: list[str] = []
    for algorithm in algorithms:
        diagnostic = algorithm.get("live_debug", {}).get("diagnostic_topics", [])
        if diagnostic:
            topic_lines.append(f"### {algorithm['display_name']}")
            for topic in diagnostic:
                topic_lines.extend((f"ros2 topic hz {topic}", f"ros2 topic delay {topic}"))
            topic_lines.append("")
    warning = (
        "This session's selected adapters have been verified as namespace-isolated for simultaneous viewing."
        if simultaneous_safe
        else "Run estimator scripts one at a time unless you have separately verified namespace/remap isolation. The session metadata records any output-topic collisions."
    )
    commands = f"""# Live Debug Session `{session_id}`

{warning}

## Suggested terminals

1. `./01_bag_play.sh`
2. open one selected estimator script such as `./{scripts[0]}`
3. open RViz manually or with your saved configuration
4. use the inspection commands below when failure begins

The bag player can be paused/resumed interactively in its terminal. For repeatable diagnosis, reduce `--rate` in a new session rather than changing estimator parameters mid-benchmark.

## Generic inspection

```bash
ros2 topic list
ros2 node list
ros2 run tf2_ros tf2_echo map base_link
```

## Algorithm topic probes

```bash
{chr(10).join(topic_lines).rstrip()}
```

## Mark a failure event

```bash
lio-benchmark mark --session {_q(session)} --algorithm <id> --event repetitive_row_misregistration --bag-time <seconds> --note "what you observed"
```
"""
    (session / "commands.md").write_text(commands, encoding="utf-8")
    return session


def append_marker(
    *,
    session: str | Path,
    algorithm_id: str,
    event: str,
    bag_time_s: float,
    note: str = "",
) -> dict[str, Any]:
    session = Path(session)
    manifest_path = session / "session.json"
    if not manifest_path.is_file():
        raise ValueError(f"invalid live-debug session: {session}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if algorithm_id not in manifest.get("algorithms", []):
        raise ValueError(f"algorithm not part of session: {algorithm_id}")
    if bag_time_s < 0:
        raise ValueError("bag_time_s must be >= 0")
    record = {
        "recorded_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "algorithm_id": algorithm_id,
        "event": event,
        "bag_time_s": float(bag_time_s),
        "note": note,
    }
    path = session / "markers" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
