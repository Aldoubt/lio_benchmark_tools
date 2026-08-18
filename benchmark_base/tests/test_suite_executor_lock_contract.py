from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
import tempfile
import unittest

from benchmark_base.lib.suite_events import SuiteExecutionLock
from benchmark_base.lib.suite_orchestrator import execute_suite
from benchmark_base.lib.suite_plan import build_suite_plan, write_suite_plan
from benchmark_base.tests.suite_test_utils import create_frozen_run


def _hold_lock(run_text: str, ready: mp.Event, release: mp.Event) -> None:
    with SuiteExecutionLock(Path(run_text)):
        ready.set()
        release.wait(timeout=10.0)


class SuiteExecutorLockContractTest(unittest.TestCase):
    def test_second_executor_returns_blocked_contract_without_running_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run, manifest = create_frozen_run(Path(tmp))
            plan = build_suite_plan(run, manifest, created_at="2026-08-18T00:00:00+00:00")
            write_suite_plan(run, plan)

            ready = mp.Event()
            release = mp.Event()
            process = mp.Process(target=_hold_lock, args=(str(run), ready, release))
            process.start()
            self.assertTrue(ready.wait(timeout=5.0))
            try:
                result = execute_suite(
                    run,
                    cli_path=Path("/repo/benchmark_base/bin/lio-benchmark"),
                    command_runner=lambda _argv: self.fail("blocked executor ran a stage"),
                    install_signal_handlers=False,
                )
            finally:
                release.set()
                process.join(timeout=5.0)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=2.0)

            self.assertEqual("BLOCKED", result.state)
            self.assertEqual(2, result.exit_code)
            self.assertEqual((), result.started_stage_ids)
            self.assertEqual("BLOCKED_EXECUTOR_LOCKED", result.stop_reason)


if __name__ == "__main__":
    unittest.main()
