#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

venv_dir="${LIO_FREEZE_VENV:-$repo_root/.venv-freeze}"

if [[ -e "$venv_dir" && ! -x "$venv_dir/bin/python" ]]; then
  echo "refusing to reuse invalid freeze environment: $venv_dir" >&2
  exit 2
fi

if [[ ! -x "$venv_dir/bin/python" ]]; then
  python3 -m venv --system-site-packages "$venv_dir"
fi

# Dependency resolution must ignore ~/.local as well as runtime imports. Otherwise
# pip can incorrectly treat user-site packages (for example pyarrow/Jinja2) as
# satisfying the venv even though PYTHONNOUSERSITE=1 later hides them.
env PYTHONNOUSERSITE=1 "$venv_dir/bin/python" -m pip install --upgrade pip
env PYTHONNOUSERSITE=1 "$venv_dir/bin/python" -m pip install -r benchmark_base/requirements-freeze.txt

# Do not run a global `pip check` here. This venv intentionally inherits ROS/
# Ubuntu system packages via --system-site-packages, so unrelated apt packages
# can have incomplete Python metadata/dependencies and must not block Freeze.
# Instead, validate the exact dependency/runtime surface used by Freeze.
PYTHONNOUSERSITE=1 "$venv_dir/bin/python" - <<'PY'
import sys
import jinja2
import matplotlib
import numpy
import pyarrow
import reportlab
import rerun
import scipy
from scipy.spatial import cKDTree

assert numpy.__version__ == "2.2.6", numpy.__version__
assert scipy.__version__ == "1.14.1", scipy.__version__
assert matplotlib.__version__ == "3.10.5", matplotlib.__version__
assert jinja2.__version__ == "3.1.6", jinja2.__version__
assert reportlab.Version == "4.4.9", reportlab.Version
assert rerun.__version__ == "0.36.3", rerun.__version__
_ = cKDTree([[0.0, 0.0, 0.0]])
print(
    "freeze environment ready: "
    f"python={sys.executable} "
    f"numpy={numpy.__version__} scipy={scipy.__version__} "
    f"matplotlib={matplotlib.__version__} jinja2={jinja2.__version__} "
    f"pyarrow={pyarrow.__version__} reportlab={reportlab.Version} "
    f"rerun={rerun.__version__}"
)
PY

cat <<EOF
Freeze environment created/verified:
  $venv_dir

Use it explicitly with:
  ./evaluators/check_freeze_pipeline.sh --freeze-python "$venv_dir/bin/python" --run <RUN_DIR>
EOF
