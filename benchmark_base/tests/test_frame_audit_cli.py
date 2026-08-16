from __future__ import annotations

import importlib.machinery
import importlib.util
import unittest
from pathlib import Path


class FrameAuditCliTest(unittest.TestCase):
    @staticmethod
    def _load_cli():
        root = Path(__file__).resolve().parents[2]
        path = root / "benchmark_base/bin/lio-benchmark"
        loader = importlib.machinery.SourceFileLoader("lio_benchmark_cli", str(path))
        spec = importlib.util.spec_from_loader("lio_benchmark_cli", loader)
        if spec is None:
            raise RuntimeError("unable to load lio-benchmark CLI")
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_trajectory_frame_audit_is_exposed_through_main_cli(self) -> None:
        module = self._load_cli()
        args = module.build_parser().parse_args(
            [
                "audit",
                "trajectory-frames",
                "--run",
                "/tmp/run",
                "--algorithms",
                "fast_livo2",
                "fast_lio2",
                "kiss_icp",
            ]
        )
        self.assertEqual("audit", args.command)
        self.assertEqual("trajectory-frames", args.audit_command)
        self.assertEqual(["fast_livo2", "fast_lio2", "kiss_icp"], args.algorithms)
        self.assertEqual("cmd_audit_trajectory_frames", args.func.__name__)


if __name__ == "__main__":
    unittest.main()
