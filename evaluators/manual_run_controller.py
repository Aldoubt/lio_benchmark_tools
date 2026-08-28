#!/usr/bin/env python3
"""Clock-anchor-aware facade for the existing manual LIO run controller.

The large, battle-tested lifecycle implementation stays in
manual_run_controller_base.py. This facade adds strict /clock capture without
copying or forking the rest of the controller logic.
"""
from __future__ import annotations

import signal
import sys
from pathlib import Path
from typing import Any, Callable

import manual_run_controller_base as _base

REPO_ROOT = Path(__file__).resolve().parents[1]
ControllerError = _base.ControllerError
MAIN_TOPICS = _base.MAIN_TOPICS
_BaseManualRunController = _base.ManualRunController


def _make_manual_controller_class(base_class: type) -> type:
    class ClockAnchoredManualRunController(base_class):
        """Add strict /clock anchor capture without duplicating controller logic."""

        def _start_clock_anchor_recorder(self) -> None:
            if self._output_dir is None:
                raise ControllerError(
                    "clock anchor recorder requires an allocated output directory"
                )
            existing = self._processes.get("clock_anchor")
            if existing is not None and self._poll(existing) is None:
                return
            command = [
                sys.executable,
                str(REPO_ROOT / "evaluators/clock_anchor_recorder.py"),
                "--output", str(self._output_dir / "clock_anchors.json"),
            ]
            process = self._spawn("clock_anchor", self._shell_script(command), self._output_dir / "clock_anchor_recorder.log")
            self._sleep(0.25)
            if self._poll(process) is not None:
                raise ControllerError(
                    "clock anchor recorder exited during prepare, "
                    f"returncode={self._poll(process)}"
                )

        def prepare(self) -> dict[str, Any]:
            super().prepare()
            try:
                self._start_clock_anchor_recorder()
            except Exception:
                self._finalize(
                    bag_state="failed",
                    forced_status="RUNTIME_CRASH",
                    reason="clock anchor recorder failed during prepare",
                )
                raise
            return self.snapshot()

        def _finalize(self, **kwargs: Any) -> dict[str, Any]:
            # Stop playback first so the last /clock sample can arrive. Then
            # stop the recorder and let its finally block atomically write the
            # status=finished snapshot before the base finalizer continues.
            if self._bag_process is not None and self._poll(self._bag_process) is None:
                self._terminate("bag_play", signal.SIGINT, 5.0)
            if "clock_anchor" in self._processes:
                self._terminate("clock_anchor", signal.SIGTERM, 5.0)
            return super()._finalize(**kwargs)

    ClockAnchoredManualRunController.__name__ = "ManualRunController"
    ClockAnchoredManualRunController.__qualname__ = "ManualRunController"
    return ClockAnchoredManualRunController


ManualRunController = _make_manual_controller_class(_BaseManualRunController)


class RunQueueWorker(_base.RunQueueWorker):
    """Use the clock-anchor-aware controller for queued manual runs by default."""

    def __init__(
        self,
        run_dir: Path,
        algorithms: list[str],
        *,
        bag_dir: Path | None = None,
        duration_s: float | None = None,
        controller_factory: Callable[..., ManualRunController] = ManualRunController,
    ) -> None:
        super().__init__(
            run_dir,
            algorithms,
            bag_dir=bag_dir,
            duration_s=duration_s,
            controller_factory=controller_factory,
        )


def main() -> int:
    # The legacy CLI resolves its controller through module globals at runtime.
    _base.ManualRunController = ManualRunController
    _base.RunQueueWorker = RunQueueWorker
    return int(_base.main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
