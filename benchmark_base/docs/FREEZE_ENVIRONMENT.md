# Freeze / Native Rerun Python environment

The immutable Freeze pipeline intentionally uses two Python environments on the Ubuntu 22.04 / ROS 2 Humble benchmark host.

## Why isolation is required

`rerun-sdk==0.36.3` resolves to NumPy 2.x. The Ubuntu 22.04 apt SciPy used by the existing ROS/benchmark scientific stack is built against the NumPy 1.x ABI and requires NumPy `<1.25`. Installing Rerun directly with the normal user Python can therefore place NumPy 2 in `~/.local`, shadow the apt NumPy, and make SciPy C extensions fail during import with errors such as:

```text
ValueError: numpy.dtype size changed, may indicate binary incompatibility
```

Do not install the Freeze requirements into the ROS system Python or `~/.local`.

## Supported layout

The repository uses:

```text
ROS/system Python
  -> benchmark static/unit tests
  -> PYTHONNOUSERSITE=1
  -> Ubuntu/ROS NumPy + SciPy

.venv-freeze
  -> immutable Freeze workflow
  -> Native Rerun 0.36.3
  -> NumPy 2.2.6
  -> SciPy 1.14.1
  -> Matplotlib 3.10.5
  -> Jinja2 / ReportLab
  -> --system-site-packages so sourced ROS/Livox message modules remain visible
```

Create or refresh the dedicated environment after sourcing the required ROS overlays:

```bash
cd ~/lio_benchmark_tools
source /opt/ros/humble/setup.bash
# source the workspace/overlay that provides the bag's exact Livox message type

./evaluators/setup_freeze_venv.sh
```

The dependency set is pinned in:

```text
benchmark_base/requirements-freeze.txt
```

## Acceptance

Static gate only:

```bash
./evaluators/check_freeze_pipeline.sh
```

Real completed-run acceptance:

```bash
./evaluators/check_freeze_pipeline.sh \
  --run /absolute/path/to/completed_run \
  --baseline fast_livo2 \
  --lang zh-CN
```

The default real-run interpreter is `.venv-freeze/bin/python`. An equivalent environment can be supplied explicitly:

```bash
./evaluators/check_freeze_pipeline.sh \
  --freeze-python /path/to/venv/bin/python \
  --run /absolute/path/to/completed_run
```

Add `--open` only when the host has a working graphical Native Rerun session and the `.rrd` reopen itself is part of the acceptance run.

## Recovering a host polluted by a user-site NumPy 2 install

If NumPy 2 was installed into `~/.local` by a previous direct Rerun install, remove the user-site Rerun/NumPy packages and verify the ROS/system stack without user-site packages:

```bash
python3 -m pip uninstall -y rerun-sdk numpy

PYTHONNOUSERSITE=1 python3 - <<'PY'
import numpy
import scipy
from scipy.spatial import cKDTree
print("numpy", numpy.__version__, numpy.__file__)
print("scipy", scipy.__version__, scipy.__file__)
_ = cKDTree([[0.0, 0.0, 0.0]])
print("system scientific stack OK")
PY
```

Then recreate `.venv-freeze` with `./evaluators/setup_freeze_venv.sh`. Do not reinstall `rerun-sdk` with a bare `python3 -m pip install ...` on the benchmark host.
