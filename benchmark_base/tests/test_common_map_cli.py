from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import unittest


class CommonMapCliContractTest(unittest.TestCase):
    @staticmethod
    def _load_cli():
        root = Path(__file__).resolve().parents[2]
        path = root / "benchmark_base" / "bin" / "lio-benchmark"
        loader = importlib.machinery.SourceFileLoader("lio_benchmark_cli_common_map", str(path))
        spec = importlib.util.spec_from_loader("lio_benchmark_cli_common_map", loader)
        if spec is None:
            raise RuntimeError("unable to load lio-benchmark CLI")
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_common_map_manifest_cli_exposes_only_run_input(self) -> None:
        module = self._load_cli()
        parser = module.build_parser()
        args = parser.parse_args(
            ["standardize", "common-map-manifest", "--run", "/persistent/run"]
        )
        self.assertEqual("standardize", args.command)
        self.assertEqual("common-map-manifest", args.standardize_command)
        self.assertEqual(Path("/persistent/run"), args.run)
        self.assertEqual("cmd_standardize_common_map_manifest", args.func.__name__)

        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "standardize",
                    "common-map-manifest",
                    "--run",
                    "/persistent/run",
                    "--algorithm",
                    "fast_lio2",
                ]
            )
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "standardize",
                    "common-map-manifest",
                    "--run",
                    "/persistent/run",
                    "--trajectory-time-tolerance-s",
                    "0.1",
                ]
            )
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "standardize",
                    "common-map-manifest",
                    "--run",
                    "/persistent/run",
                    "--overwrite",
                ]
            )

    def test_common_map_handler_uses_shared_ros_workspace_runner(self) -> None:
        module = self._load_cli()
        run = Path("/persistent/run")
        manifest = {"workspace": "/persistent/workspace", "algorithms": {"fast_lio2": {}}}
        calls: dict[str, object] = {}

        original_resolve_run = module._core.resolve_run
        original_run_python_ros = module._core.run_python_ros

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

        module._core.resolve_run = fake_resolve_run
        module._core.run_python_ros = fake_run_python_ros
        try:
            args = module.build_parser().parse_args(
                ["standardize", "common-map-manifest", "--run", str(run)]
            )
            result = args.func(args)
        finally:
            module._core.resolve_run = original_resolve_run
            module._core.run_python_ros = original_run_python_ros

        self.assertIsNone(result)
        self.assertEqual(run, calls["resolved"])
        self.assertEqual(
            (
                run,
                manifest,
                "evaluators/build_common_map_manifest.py",
                ["--run", str(run)],
            ),
            calls["ros"],
        )


if __name__ == "__main__":
    unittest.main()
