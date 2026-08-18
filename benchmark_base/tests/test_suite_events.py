from __future__ import annotations

import importlib
import importlib.util
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import time
import unittest

from benchmark_base.lib.manifest import sha256_file
from benchmark_base.lib.suite_plan import build_suite_plan, write_suite_plan
from benchmark_base.lib.suite_status import derive_suite_status
from benchmark_base.tests.suite_test_utils import create_frozen_run


MODULE_NAME = "benchmark_base.lib.suite_events"


def _hold_lock(run_text: str, ready: mp.Event, release: mp.Event) -> None:
    module = importlib.import_module(MODULE_NAME)
    with module.SuiteExecutionLock(Path(run_text)):
        ready.set()
        release.wait(timeout=10.0)


class SuiteEventsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = importlib.util.find_spec(MODULE_NAME)
        cls.module = importlib.import_module(MODULE_NAME) if cls.spec is not None else None

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.run, manifest = create_frozen_run(Path(self.tmp.name))
        plan = build_suite_plan(self.run, manifest, created_at="2026-08-18T00:00:00+00:00")
        self.plan_path = write_suite_plan(self.run, plan)
        self.plan_sha = sha256_file(self.plan_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def require_module(self):
        if self.module is None:
            self.skipTest("suite_events production module is intentionally absent in RED")
        return self.module

    def test_suite_events_module_exists(self) -> None:
        self.assertIsNotNone(
            self.spec,
            "Benchmark Suite Orchestrator V1 requires benchmark_base.lib.suite_events",
        )

    def test_events_are_monotonic_append_only_and_schema_validated(self) -> None:
        module = self.require_module()
        first = module.append_event(
            self.run,
            invocation_id="inv-1",
            event_type="SUITE_INVOCATION_STARTED",
            stage_id=None,
            plan_sha256=self.plan_sha,
            timestamp="2026-08-18T00:00:00+00:00",
        )
        second = module.append_event(
            self.run,
            invocation_id="inv-1",
            event_type="STAGE_STARTED",
            stage_id="snapshot",
            plan_sha256=self.plan_sha,
            command=["python3", "lio-benchmark", "snapshot"],
            timestamp="2026-08-18T00:00:01+00:00",
        )
        self.assertEqual("000001.json", first.name)
        self.assertEqual("000002.json", second.name)
        self.assertEqual([1, 2], [event["event_id"] for event in module.read_events(self.run)])
        self.assertEqual(
            {"lio_benchmark_suite_event/v1"},
            {event["schema"] for event in module.read_events(self.run)},
        )
        before = first.read_bytes()
        module.append_event(
            self.run,
            invocation_id="inv-1",
            event_type="STAGE_FINISHED",
            stage_id="snapshot",
            plan_sha256=self.plan_sha,
            returncode=0,
            observed_state="PASS",
            timestamp="2026-08-18T00:00:02+00:00",
        )
        self.assertEqual(before, first.read_bytes())

    def test_event_ledger_gap_or_filename_id_mismatch_fails_closed(self) -> None:
        module = self.require_module()
        events = self.run / "metadata/suite/events"
        events.mkdir(parents=True)
        (events / "000002.json").write_text(
            json.dumps(
                {
                    "schema": "lio_benchmark_suite_event/v1",
                    "event_id": 1,
                    "invocation_id": "inv-1",
                    "event_type": "SUITE_INVOCATION_STARTED",
                    "stage_id": None,
                    "timestamp": "2026-08-18T00:00:00+00:00",
                    "plan_sha256": self.plan_sha,
                    "command": None,
                    "returncode": None,
                    "observed_state": None,
                    "reason_code": None,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(module.SuiteEventError):
            module.read_events(self.run)

    def test_second_executor_is_blocked_by_kernel_flock(self) -> None:
        module = self.require_module()
        ready = mp.Event()
        release = mp.Event()
        process = mp.Process(target=_hold_lock, args=(str(self.run), ready, release))
        process.start()
        self.assertTrue(ready.wait(timeout=5.0))
        try:
            with self.assertRaises(module.SuiteEventError) as ctx:
                with module.SuiteExecutionLock(self.run):
                    self.fail("second executor unexpectedly acquired lock")
            self.assertIn("BLOCKED_EXECUTOR_LOCKED", str(ctx.exception))
        finally:
            release.set()
            process.join(timeout=5.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2.0)

    def test_status_lock_observation_does_not_create_absent_lock_file(self) -> None:
        module = self.require_module()
        lock = self.run / "metadata/suite/suite.lock"
        self.assertFalse(lock.exists())
        observation = module.observe_execution(self.run)
        self.assertFalse(observation.locked)
        self.assertFalse(lock.exists())

    def test_historical_unmatched_stage_started_is_not_running_without_live_lock(self) -> None:
        module = self.require_module()
        module.append_event(
            self.run,
            invocation_id="historical",
            event_type="SUITE_INVOCATION_STARTED",
            stage_id=None,
            plan_sha256=self.plan_sha,
            timestamp="2026-08-18T00:00:00+00:00",
        )
        module.append_event(
            self.run,
            invocation_id="historical",
            event_type="STAGE_STARTED",
            stage_id="snapshot",
            plan_sha256=self.plan_sha,
            command=["snapshot"],
            timestamp="2026-08-18T00:00:01+00:00",
        )
        observation = module.observe_execution(self.run)
        self.assertFalse(observation.locked)
        status = derive_suite_status(self.run, execution=observation)
        snapshot = next(stage for stage in status.stages if stage.stage_id == "snapshot")
        self.assertEqual("READY", snapshot.state)

    def test_live_lock_plus_unmatched_stage_event_is_running(self) -> None:
        module = self.require_module()
        module.append_event(
            self.run,
            invocation_id="live",
            event_type="SUITE_INVOCATION_STARTED",
            stage_id=None,
            plan_sha256=self.plan_sha,
            timestamp="2026-08-18T00:00:00+00:00",
        )
        module.append_event(
            self.run,
            invocation_id="live",
            event_type="STAGE_STARTED",
            stage_id="snapshot",
            plan_sha256=self.plan_sha,
            command=["snapshot"],
            timestamp="2026-08-18T00:00:01+00:00",
        )

        ready = mp.Event()
        release = mp.Event()
        process = mp.Process(target=_hold_lock, args=(str(self.run), ready, release))
        process.start()
        self.assertTrue(ready.wait(timeout=5.0))
        try:
            observation = module.observe_execution(self.run)
            self.assertTrue(observation.locked)
            self.assertEqual("live", observation.active_invocation_id)
            self.assertEqual("snapshot", observation.active_stage_id)
            status = derive_suite_status(self.run, execution=observation)
            snapshot = next(stage for stage in status.stages if stage.stage_id == "snapshot")
            self.assertEqual("RUNNING", snapshot.state)
            self.assertEqual("RUNNING", status.state)
        finally:
            release.set()
            process.join(timeout=5.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
