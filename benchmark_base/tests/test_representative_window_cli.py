from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "benchmark_base/bin/lio-benchmark"


class RepresentativeWindowCliTest(unittest.TestCase):
    @staticmethod
    def _load_cli():
        loader = importlib.machinery.SourceFileLoader("lio_benchmark_cli_windows", str(CLI))
        spec = importlib.util.spec_from_loader("lio_benchmark_cli_windows", loader)
        if spec is None:
            raise RuntimeError("unable to load lio-benchmark CLI")
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_plan_representative_windows_exposes_only_run(self) -> None:
        module = self._load_cli()
        args = module.build_parser().parse_args(
            ["plan", "representative-windows", "--run", "/persistent/selector"]
        )
        self.assertEqual("plan", args.command)
        self.assertEqual("representative-windows", args.plan_command)
        self.assertEqual(Path("/persistent/selector"), args.run)
        self.assertEqual("cmd_plan_representative_windows", args.func.__name__)
        with self.assertRaises(SystemExit):
            module.build_parser().parse_args(
                [
                    "plan",
                    "representative-windows",
                    "--run",
                    "/persistent/selector",
                    "--window-duration-s",
                    "30",
                ]
            )

    def test_handler_uses_shared_ros_workspace_runner(self) -> None:
        module = self._load_cli()
        run = Path("/persistent/selector")
        manifest = {"workspace": "/persistent/workspace", "algorithms": {}}
        calls: dict[str, object] = {}
        original_resolve_run = module._core.resolve_run
        original_run_python_ros = module._core.run_python_ros
        original_subprocess_run = module.subprocess.run

        def fake_resolve_run(path: Path):
            calls["resolved"] = path
            return run, manifest

        def fake_run_python_ros(
            resolved_run: Path,
            resolved_manifest: dict,
            script: str,
            arguments: list[str],
        ) -> None:
            calls["ros"] = (resolved_run, resolved_manifest, script, arguments)

        def forbidden_subprocess_run(*args, **kwargs):
            raise AssertionError("representative window planner must use shared ROS workspace runner")

        module._core.resolve_run = fake_resolve_run
        module._core.run_python_ros = fake_run_python_ros
        module.subprocess.run = forbidden_subprocess_run
        try:
            code = module.cmd_plan_representative_windows(SimpleNamespace(run=run))
        finally:
            module._core.resolve_run = original_resolve_run
            module._core.run_python_ros = original_run_python_ros
            module.subprocess.run = original_subprocess_run

        self.assertEqual(0, code)
        self.assertEqual(run, calls["resolved"])
        self.assertEqual(
            (
                run,
                manifest,
                "evaluators/plan_representative_windows.py",
                ["--run", str(run)],
            ),
            calls["ros"],
        )


if __name__ == "__main__":
    unittest.main()
