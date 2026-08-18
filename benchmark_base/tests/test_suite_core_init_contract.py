from __future__ import annotations

import importlib.machinery
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "benchmark_base/bin/lio-benchmark-core"


def load_core_direct():
    loader = importlib.machinery.SourceFileLoader("lio_benchmark_core_direct_contract", str(CORE))
    spec = importlib.util.spec_from_loader("lio_benchmark_core_direct_contract", loader)
    if spec is None:
        raise RuntimeError("unable to load historical CLI core")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class SuiteCoreInitializationContractTest(unittest.TestCase):
    def test_core_directly_owns_initialize_run_and_cmd_init_is_thin_wrapper(self) -> None:
        core = load_core_direct()
        self.assertTrue(
            hasattr(core, "initialize_run"),
            "lio-benchmark-core must own initialize_run; dispatcher monkey-patching is not initialization reuse",
        )

        args = SimpleNamespace(config=Path("/tmp/config.json"), run_id="run_1")
        expected = Path("/tmp/runs/run_1")
        output = io.StringIO()
        with mock.patch.object(core, "initialize_run", return_value=expected) as initialize:
            with mock.patch("sys.stdout", output):
                core.cmd_init(args)

        initialize.assert_called_once_with(Path("/tmp/config.json").resolve(), "run_1")
        self.assertEqual(str(expected), output.getvalue().strip())


if __name__ == "__main__":
    unittest.main()
