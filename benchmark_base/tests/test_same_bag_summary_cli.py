from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "benchmark_base/bin/lio-benchmark"


class SameBagSummaryCliContractTest(unittest.TestCase):
    @staticmethod
    def _load_cli():
        loader = importlib.machinery.SourceFileLoader("lio_benchmark_cli_same_bag", str(CLI))
        spec = importlib.util.spec_from_loader("lio_benchmark_cli_same_bag", loader)
        if spec is None:
            raise RuntimeError("unable to load lio-benchmark CLI")
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_parser_exposes_only_existing_run_input(self) -> None:
        module = self._load_cli()
        args = module.build_parser().parse_args(
            ["summarize", "same-bag", "--run", "/frozen/full_run"]
        )
        self.assertEqual("summarize", args.command)
        self.assertEqual("same-bag", args.summarize_command)
        self.assertEqual(Path("/frozen/full_run"), args.run)
        self.assertEqual("cmd_summarize_same_bag", args.func.__name__)

        for extra in (["--algorithm", "fast_livo2"], ["--overwrite"], ["--rebuild-maps"]):
            with self.subTest(extra=extra), self.assertRaises(SystemExit):
                module.build_parser().parse_args(
                    ["summarize", "same-bag", "--run", "/frozen/full_run", *extra]
                )

    def test_handler_invokes_only_pure_python_summary_evaluator(self) -> None:
        module = self._load_cli()
        calls: dict[str, object] = {}
        original_run_python_ros = module._core.run_python_ros
        original_subprocess_run = module.subprocess.run

        def forbidden_run_python_ros(*args, **kwargs):
            raise AssertionError("same-bag summarizer must not source ROS or replay a bag")

        class Completed:
            returncode = 0

        def fake_subprocess_run(command, cwd=None, check=None):
            calls["command"] = command
            calls["cwd"] = cwd
            calls["check"] = check
            return Completed()

        module._core.run_python_ros = forbidden_run_python_ros
        module.subprocess.run = fake_subprocess_run
        try:
            code = module.cmd_summarize_same_bag(SimpleNamespace(run=Path("/frozen/full_run")))
        finally:
            module._core.run_python_ros = original_run_python_ros
            module.subprocess.run = original_subprocess_run

        self.assertEqual(0, code)
        self.assertEqual(
            [
                module.sys.executable,
                str(ROOT / "evaluators/summarize_same_bag.py"),
                "--run",
                "/frozen/full_run",
            ],
            calls["command"],
        )
        self.assertEqual(ROOT, calls["cwd"])
        self.assertFalse(calls["check"])

    def test_evaluator_has_no_ros_or_estimator_execution_dependency(self) -> None:
        evaluator = ROOT / "evaluators/summarize_same_bag.py"
        self.assertTrue(evaluator.is_file())
        text = evaluator.read_text(encoding="utf-8").lower()
        self.assertNotIn("rclpy", text)
        self.assertNotIn("rosbag2_py", text)
        self.assertNotIn("ros2 bag", text)
        self.assertNotIn("run-all", text)
        self.assertNotIn("standardize_map", text)


if __name__ == "__main__":
    unittest.main()
