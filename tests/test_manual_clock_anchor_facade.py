import inspect
from pathlib import Path

import manual_run_controller as module


def test_prepare_starts_clock_recorder_after_base_prepare(tmp_path):
    events = []

    class FakeBase:
        def __init__(self, *_args, **_kwargs):
            self._output_dir = tmp_path
            self._processes = {}
            self._bag_process = None

        def prepare(self):
            events.append("base_prepare")
            return {"ok": True}

        def snapshot(self):
            return {"snapshot": True}

        def _shell_script(self, command):
            return " ".join(map(str, command))

        def _spawn(self, name, _script, _output, _stderr=None):
            events.append(name)

            class Process:
                pid = 1

                def poll(self):
                    return None

            process = Process()
            self._processes[name] = process
            return process

        def _sleep(self, _seconds):
            return None

        def _poll(self, process):
            return process.poll() if process else None

        def _terminate(self, name, *_args, **_kwargs):
            events.append("stop:" + name)
            return 0

        def _finalize(self, **kwargs):
            events.append("base_finalize")
            return kwargs

    controller_class = module._make_manual_controller_class(FakeBase)
    controller = controller_class(tmp_path, "demo")
    assert controller.prepare() == {"snapshot": True}
    assert events[:2] == ["base_prepare", "clock_anchor_recorder"]


def test_finalize_stops_bag_then_clock_before_base_finalize(tmp_path):
    events = []

    class Process:
        def poll(self):
            return None

    class FakeBase:
        def __init__(self, *_args, **_kwargs):
            self._output_dir = tmp_path
            self._processes = {
                "clock_anchor_recorder": Process(),
                "bag_play": Process(),
            }
            self._bag_process = self._processes["bag_play"]

        def _poll(self, process):
            return process.poll() if process else None

        def _terminate(self, name, *_args, **_kwargs):
            events.append(name)
            return 0

        def _finalize(self, **kwargs):
            events.append("base")
            return kwargs

    controller_class = module._make_manual_controller_class(FakeBase)
    controller = controller_class(tmp_path, "demo")
    controller._finalize(bag_state="stopped")
    assert events[:3] == ["bag_play", "clock_anchor_recorder", "base"]


def test_queue_defaults_to_clock_anchor_aware_controller():
    parameter = inspect.signature(module.RunQueueWorker.__init__).parameters[
        "controller_factory"
    ]
    assert parameter.default is module.ManualRunController
