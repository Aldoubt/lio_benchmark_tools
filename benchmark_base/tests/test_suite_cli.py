from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "benchmark_base/bin/lio-benchmark"


def load_cli():
    loader = importlib.machinery.SourceFileLoader("lio_benchmark_cli_suite", str(CLI))
    spec = importlib.util.spec_from_loader("lio_benchmark_cli_suite", loader)
    if spec is None:
        raise RuntimeError("unable to load public CLI")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class SuiteCliContractTest(unittest.TestCase):
    def require_interfaces(self, module) -> None:
        required = ("cmd_suite_run", "cmd_suite_status", "cmd_suite_resume")
        missing = [name for name in required if not hasattr(module, name)]
        if not hasattr(module._core, "initialize_run"):
            missing.append("_core.initialize_run")
        if missing:
            self.skipTest(f"suite CLI interfaces intentionally absent in RED: {missing}")

    def test_suite_cli_and_core_initialization_interfaces_exist(self) -> None:
        module = load_cli()
        required = ("cmd_suite_run", "cmd_suite_status", "cmd_suite_resume")
        missing = [name for name in required if not hasattr(module, name)]
        if not hasattr(module._core, "initialize_run"):
            missing.append("_core.initialize_run")
        self.assertEqual([], missing, f"missing P2 suite CLI interfaces: {missing}")

    def test_suite_parser_exposes_only_frozen_v1_surface(self) -> None:
        module = load_cli()
        self.require_interfaces(module)
        parser = module.build_parser()

        run_args = parser.parse_args(
            ["suite", "run", "--config", "/tmp/experiment.json", "--run-id", "suite_smoke_001"]
        )
        self.assertEqual(Path("/tmp/experiment.json"), run_args.config)
        self.assertEqual("suite_smoke_001", run_args.run_id)
        self.assertIs(run_args.func, module.cmd_suite_run)

        status_args = parser.parse_args(["suite", "status", "--run", "/tmp/run", "--json"])
        self.assertEqual(Path("/tmp/run"), status_args.run)
        self.assertTrue(status_args.json)
        self.assertIs(status_args.func, module.cmd_suite_status)

        resume_args = parser.parse_args(["suite", "resume", "--run", "/tmp/run"])
        self.assertEqual(Path("/tmp/run"), resume_args.run)
        self.assertIs(resume_args.func, module.cmd_suite_resume)

        with self.assertRaises(SystemExit):
            parser.parse_args(["suite", "run", "--config", "/tmp/experiment.json"])

        base = ["suite", "run", "--config", "/tmp/experiment.json", "--run-id", "suite_smoke_001"]
        forbidden = (
            ["--algorithms", "fast_lio2"],
            ["--algorithm", "fast_lio2"],
            ["--rate", "2.0"],
            ["--duration-s", "10"],
            ["--start-offset-s", "5"],
            ["--overwrite"],
            ["--force"],
            ["--parallel"],
            ["--jobs", "2"],
            ["--allow-diagnostic-calibration"],
        )
        for extra in forbidden:
            with self.subTest(extra=extra):
                with self.assertRaises(SystemExit):
                    parser.parse_args([*base, *extra])

    def test_initialize_run_preserves_historical_init_artifacts(self) -> None:
        module = load_cli()
        self.require_interfaces(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "experiment.json"
            config.write_text("{}\n", encoding="utf-8")
            source = {
                "schema_version": 2,
                "name": "suite_init_test",
                "output_root": str(root / "runs"),
            }
            resolved = {
                "dataset": {
                    "dataset_id": "dataset_a",
                    "bag_dir": "/data/bag",
                    "sha256": "a" * 64,
                },
                "algorithms": {"fast_lio2": {}},
            }
            with mock.patch.object(module._core, "resolve_config", return_value=(source, resolved)):
                run = module._core.initialize_run(config, "suite_init_001")

            self.assertEqual(root / "runs/suite_init_001", run)
            self.assertTrue((run / "manifest.json").is_file())
            self.assertTrue((run / "input/DATASET.txt").is_file())
            self.assertTrue((run / "RUN_STATUS.md").is_file())
            self.assertTrue((run / "raw/fast_lio2").is_dir())
            frozen = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("suite_init_001", frozen["run_id"])
            self.assertEqual(str(config.resolve()), frozen["source_manifest"])
            self.assertEqual(2, frozen["source_manifest_schema_version"])

            with mock.patch.object(module._core, "resolve_config", return_value=(source, resolved)):
                with self.assertRaises(SystemExit):
                    module._core.initialize_run(config, "suite_init_001")

    def test_historical_cmd_init_is_thin_wrapper_around_initialize_run(self) -> None:
        module = load_cli()
        self.require_interfaces(module)
        args = SimpleNamespace(config=Path("/tmp/config.json"), run_id="run_1")
        expected = Path("/tmp/runs/run_1")
        output = io.StringIO()
        with mock.patch.object(module._core, "initialize_run", return_value=expected) as initialize:
            with mock.patch("sys.stdout", output):
                module._core.cmd_init(args)
        initialize.assert_called_once_with(Path("/tmp/config.json").resolve(), "run_1")
        self.assertEqual(str(expected), output.getvalue().strip())

    def test_suite_status_is_read_only_and_subprocess_free(self) -> None:
        module = load_cli()
        self.require_interfaces(module)
        fake_status = SimpleNamespace(
            run=Path("/tmp/run"),
            profile="SAME_BAG_MAPPING_V1",
            dataset_id="dataset_a",
            selected_algorithms=("fast_livo2", "fast_lio2", "kiss_icp"),
            state="READY",
            stages=(),
        )
        args = SimpleNamespace(run=Path("/tmp/run"), json=True)
        with mock.patch.object(module, "observe_execution", return_value=SimpleNamespace(locked=False, active_invocation_id=None, active_stage_id=None)):
            with mock.patch.object(module, "derive_suite_status", return_value=fake_status) as derive:
                with mock.patch.object(module, "status_to_dict", return_value={"state": "READY"}):
                    with mock.patch.object(module.subprocess, "run", side_effect=AssertionError("status used subprocess")):
                        with mock.patch.object(module._core, "initialize_run", side_effect=AssertionError("status initialized run")):
                            with mock.patch.object(module, "write_suite_plan", side_effect=AssertionError("status wrote plan")):
                                output = io.StringIO()
                                with mock.patch("sys.stdout", output):
                                    code = module.cmd_suite_status(args)
        self.assertEqual(0, code)
        derive.assert_called_once()
        self.assertEqual({"state": "READY"}, json.loads(output.getvalue()))

    def test_suite_run_validates_before_init_then_freezes_plan_and_executes(self) -> None:
        module = load_cli()
        self.require_interfaces(module)
        config = Path("/tmp/config.json")
        run = Path("/tmp/run")
        source = {"schema_version": 2, "name": "suite"}
        resolved = {"dataset": {"sha256": "a" * 64}}
        frozen_manifest = {"run_id": "suite_001", "dataset": {"sha256": "a" * 64}, "algorithms": {a: {} for a in ("fast_livo2", "fast_lio2", "kiss_icp")}}
        plan = {"schema": "lio_benchmark_suite_plan/v1"}
        result = SimpleNamespace(exit_code=0, state="PASS", run=run)
        calls = []

        def resolved_config(path):
            calls.append("validate")
            return source, resolved

        def initialize(path, run_id):
            calls.append("init")
            return run

        def build(run_arg, manifest_arg):
            calls.append("plan-build")
            return plan

        def write(run_arg, payload):
            calls.append("plan-write")
            return run / "metadata/suite/plan.json"

        def execute(run_arg, **kwargs):
            calls.append("execute")
            return result

        with mock.patch.object(module._core, "resolve_config", side_effect=resolved_config):
            with mock.patch.object(module._core, "initialize_run", side_effect=initialize):
                with mock.patch.object(module._core, "load_json", return_value=frozen_manifest):
                    with mock.patch.object(module, "build_suite_plan", side_effect=build):
                        with mock.patch.object(module, "write_suite_plan", side_effect=write):
                            with mock.patch.object(module, "execute_suite", side_effect=execute):
                                code = module.cmd_suite_run(SimpleNamespace(config=config, run_id="suite_001"))
        self.assertEqual(0, code)
        self.assertEqual(["validate", "init", "plan-build", "plan-write", "execute"], calls)

    def test_suite_run_rejects_missing_dataset_identity_before_init(self) -> None:
        module = load_cli()
        self.require_interfaces(module)
        with mock.patch.object(
            module._core,
            "resolve_config",
            return_value=({"schema_version": 2}, {"dataset": {"sha256": None}}),
        ):
            with mock.patch.object(module._core, "initialize_run") as initialize:
                with self.assertRaises(SystemExit):
                    module.cmd_suite_run(SimpleNamespace(config=Path("/tmp/config.json"), run_id="suite_001"))
        initialize.assert_not_called()

    def test_suite_resume_requires_existing_valid_plan_and_never_adopts_history(self) -> None:
        module = load_cli()
        self.require_interfaces(module)
        run = Path("/tmp/run")
        result = SimpleNamespace(exit_code=0, state="PASS", run=run)
        with mock.patch.object(module, "load_and_validate_suite_plan", return_value={"schema": "lio_benchmark_suite_plan/v1"}) as load:
            with mock.patch.object(module, "execute_suite", return_value=result) as execute:
                code = module.cmd_suite_resume(SimpleNamespace(run=run))
        self.assertEqual(0, code)
        load.assert_called_once_with(run.resolve())
        execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
