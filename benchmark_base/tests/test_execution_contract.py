from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.execution_contract import (
    ExecutionContractError,
    build_blocked_runtime_identity,
    build_runtime_identity,
    fingerprint_executable,
    resolve_execution,
    write_runtime_identity,
)
from evaluators.prepare_fast_lio2_config import fmt as fast_lio2_yaml_vector


class RuntimeExecutionContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        self.run.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _make_executable(self, name: str, content: bytes = b"binary-v1") -> Path:
        path = self.root / name
        path.write_bytes(content)
        path.chmod(path.stat().st_mode | 0o111)
        return path

    def _manifest(self, override: Path | None = None) -> dict:
        value = {
            "workspace": str(self.root / "workspace"),
            "dataset": {"bag_dir": str(self.root / "bag")},
            "algorithms": {
                "fast_lio2": {
                    "execution_implementation": {
                        "repository": "Franklif1/Fast_LIO2_ROS2",
                        "package": "fast_lio",
                        "executable": "fastlio_mapping",
                    }
                }
            },
            "execution_overrides": {},
            "runtime_overlays": {},
            "replay": {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 15.0},
        }
        if override is not None:
            value["execution_overrides"] = {
                "fast_lio2": {"executable": str(override)}
            }
        return value

    def test_explicit_override_wins_and_resolves_realpath(self) -> None:
        binary = self._make_executable("fastlio_mapping")
        result = resolve_execution(self._manifest(binary), "fast_lio2")
        self.assertEqual("EXPLICIT_EXECUTABLE_OVERRIDE", result.resolution_method)
        self.assertEqual(str(binary), result.requested_executable)
        self.assertEqual(binary.resolve(), result.resolved_executable)

    def test_no_override_preserves_registry_default_execution(self) -> None:
        result = resolve_execution(self._manifest(), "fast_lio2")
        self.assertEqual("REGISTRY_DEFAULT_EXECUTION", result.resolution_method)
        self.assertIsNone(result.requested_executable)
        self.assertIsNone(result.resolved_executable)

    def test_missing_override_blocks_without_fallback(self) -> None:
        missing = self.root / "missing_fastlio"
        with self.assertRaisesRegex(ExecutionContractError, "BLOCKED_EXECUTION"):
            resolve_execution(self._manifest(missing), "fast_lio2")

    def test_non_executable_override_blocks_without_fallback(self) -> None:
        path = self.root / "not_executable"
        path.write_text("x", encoding="utf-8")
        path.chmod(0o644)
        with self.assertRaisesRegex(ExecutionContractError, "BLOCKED_EXECUTION"):
            resolve_execution(self._manifest(path), "fast_lio2")

    def test_fingerprint_contains_sha_size_and_mtime(self) -> None:
        binary = self._make_executable("algo", b"abc")
        value = fingerprint_executable(binary)
        self.assertEqual(binary.resolve(), Path(value["realpath"]))
        self.assertEqual(hashlib.sha256(b"abc").hexdigest(), value["sha256"])
        self.assertEqual(3, value["size_bytes"])
        self.assertIsInstance(value["mtime_ns"], int)

    def test_runtime_identity_records_binary_replay_config_and_package_dimensions(self) -> None:
        binary = self._make_executable("fastlio_mapping", b"binary-v2")
        config = self.root / "benchmark.yaml"
        config.write_text("publish:\n  path_en: true\n", encoding="utf-8")
        resolution = resolve_execution(self._manifest(binary), "fast_lio2")
        payload = build_runtime_identity(
            manifest=self._manifest(binary),
            algorithm_id="fast_lio2",
            resolution=resolution,
            effective_command=[str(binary), "--ros-args", "--params-file", str(config)],
            effective_config=config,
            ros_distro="humble",
            source_state={
                "path": str(self.root),
                "remote_origin": "https://github.com/local/custom-fastlio.git",
            },
            runtime_package=None,
            runtime_package_prefix=None,
        )
        self.assertEqual("FROZEN", payload["identity_status"])
        self.assertIsNone(payload["blocking_reason"])
        self.assertEqual("EXPLICIT_EXECUTABLE_OVERRIDE", payload["resolution_method"])
        self.assertEqual(hashlib.sha256(b"binary-v2").hexdigest(), payload["executable_sha256"])
        self.assertEqual(15.0, payload["replay"]["duration_s"])
        self.assertEqual(hashlib.sha256(config.read_bytes()).hexdigest(), payload["effective_config"]["sha256"])
        self.assertEqual("fast_lio", payload["registry_package"])
        self.assertIsNone(payload["runtime_package"])
        self.assertIsNone(payload["runtime_package_prefix"])
        self.assertEqual("REGISTRY_MISMATCH", payload["source_relationship"])

    def test_blocked_execution_identity_preserves_attempt_without_inventing_binary(self) -> None:
        payload = build_blocked_runtime_identity(
            manifest=self._manifest(self.root / "missing"),
            algorithm_id="fast_lio2",
            reason="BLOCKED_EXECUTION: explicit executable cannot be resolved",
        )
        self.assertEqual("BLOCKED_EXECUTION", payload["identity_status"])
        self.assertIn("cannot be resolved", payload["blocking_reason"])
        self.assertEqual("EXPLICIT_EXECUTABLE_OVERRIDE", payload["resolution_method"])
        self.assertIsNone(payload["resolved_executable"])
        self.assertIsNone(payload["executable_sha256"])
        self.assertEqual(15.0, payload["replay"]["duration_s"])

    def test_existing_frozen_identity_is_not_overwritten(self) -> None:
        payload = {
            "schema_version": 1,
            "algorithm_id": "fast_lio2",
            "identity_status": "FROZEN",
        }
        path = write_runtime_identity(self.run, "fast_lio2", payload)
        self.assertTrue(path.is_file())
        with self.assertRaisesRegex(ExecutionContractError, "already exists"):
            write_runtime_identity(self.run, "fast_lio2", payload)
        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("FROZEN", stored["identity_status"])

    def test_fast_lio2_yaml_vector_keeps_float_scalars(self) -> None:
        self.assertEqual("[1.0, 0.0, -2.0, 0.125]", fast_lio2_yaml_vector([1, 0, -2, 0.125]))

    def test_runtime_env_emission_preserves_frozen_overlay_order(self) -> None:
        manifest = self._manifest()
        manifest["runtime_overlays"] = {
            "fast_lio2": [
                "/opt/vendor/first/setup.bash",
                "/opt/vendor/second/setup.bash",
            ]
        }
        (self.run / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                sys.executable,
                str(root / "evaluators/emit_runtime_env.py"),
                "--run",
                str(self.run),
                "--algorithm",
                "fast_lio2",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn("BENCHMARK_RUNTIME_OVERLAY_COUNT=2", lines)
        first = lines.index("BENCHMARK_RUNTIME_OVERLAY_0=/opt/vendor/first/setup.bash")
        second = lines.index("BENCHMARK_RUNTIME_OVERLAY_1=/opt/vendor/second/setup.bash")
        self.assertLess(first, second)

    def test_source_runtime_overlays_helper_applies_indexed_vars_in_order(self) -> None:
        root = Path(__file__).resolve().parents[2]
        helper = root / "evaluators/source_runtime_overlays.sh"
        overlay_a = self.root / "overlay_a/setup.bash"
        overlay_b = self.root / "overlay_b/setup.bash"
        overlay_a.parent.mkdir(parents=True)
        overlay_b.parent.mkdir(parents=True)
        overlay_a.write_text('export ORDER="${ORDER}:a"\n', encoding="utf-8")
        overlay_b.write_text('export ORDER="${ORDER}:b"\n', encoding="utf-8")
        shell = f"""
set -e
ORDER=base
BENCHMARK_RUNTIME_OVERLAY_COUNT=2
BENCHMARK_RUNTIME_OVERLAY_0={str(overlay_a)!r}
BENCHMARK_RUNTIME_OVERLAY_1={str(overlay_b)!r}
source {str(helper)!r}
printf '%s' "$ORDER"
"""
        result = subprocess.run(
            ["bash", "-c", shell], text=True, capture_output=True, check=False
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("base:a:b", result.stdout)

    def test_fast_lio2_runner_supports_direct_override_and_registry_default(self) -> None:
        root = Path(__file__).resolve().parents[2]
        text = (root / "evaluators/run_fast_lio2_test.sh").read_text(encoding="utf-8")
        self.assertIn("EXPLICIT_EXECUTABLE_OVERRIDE", text)
        self.assertIn('"$BENCHMARK_RESOLVED_EXECUTABLE"', text)
        self.assertIn("ros2 launch fast_lio mapping.launch.py", text)
        self.assertIn("BENCHMARK_REPLAY_START_OFFSET_S", text)
        self.assertIn("BENCHMARK_REPLAY_DURATION_S", text)
        self.assertIn("freeze_runtime_identity.py", text)
        self.assertNotIn("/home/yangxuan/RM-NAV/build", text)
        self.assertNotIn("$WORKSPACE/build/fast_lio", text)

    def test_three_smoke_runners_freeze_runtime_identity_and_use_frozen_replay(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for name in (
            "run_fast_livo_test.sh",
            "run_fast_lio2_test.sh",
            "run_kiss_icp_test.sh",
        ):
            with self.subTest(runner=name):
                text = (root / "evaluators" / name).read_text(encoding="utf-8")
                self.assertIn("freeze_runtime_identity.py", text)
                self.assertIn("BENCHMARK_REPLAY_RATE", text)
                self.assertIn("BENCHMARK_REPLAY_START_OFFSET_S", text)
                self.assertIn("BENCHMARK_REPLAY_DURATION_S", text)

    def test_three_smoke_runners_rebuild_and_source_frozen_overlay_stack(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for name in (
            "run_fast_livo_test.sh",
            "run_fast_lio2_test.sh",
            "run_kiss_icp_test.sh",
        ):
            with self.subTest(runner=name):
                text = (root / "evaluators" / name).read_text(encoding="utf-8")
                self.assertIn("unset AMENT_PREFIX_PATH", text)
                self.assertIn("source_runtime_overlays.sh", text)
                self.assertLess(
                    text.index("unset AMENT_PREFIX_PATH"),
                    text.index("source /opt/ros/humble/setup.bash"),
                )
                self.assertLess(
                    text.index("source_runtime_overlays.sh"),
                    text.index("freeze_runtime_identity.py"),
                )
        kiss = (root / "evaluators/run_kiss_icp_test.sh").read_text(encoding="utf-8")
        self.assertNotIn(
            "/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash",
            kiss,
        )


if __name__ == "__main__":
    unittest.main()
