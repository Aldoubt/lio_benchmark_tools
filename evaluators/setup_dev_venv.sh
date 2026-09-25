#!/usr/bin/env bash
set -euo pipefail

# Create the unit-test / development environment (.venv-dev).
# The core benchmark runs under the ROS Humble system Python, so this venv
# inherits system site-packages but is always used with PYTHONNOUSERSITE=1:
# packages in ~/.local (for example NumPy 2.x) must not shadow the apt
# NumPy 1.x / SciPy 1.8 ABI that ROS Humble and the evaluators rely on.

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

venv_dir="${LIO_DEV_VENV:-$repo_root/.venv-dev}"
export PYTHONNOUSERSITE=1

if [[ -e "$venv_dir" && ! -x "$venv_dir/bin/python" ]]; then
  echo "refusing to reuse invalid dev environment: $venv_dir" >&2
  exit 2
fi

if [[ ! -x "$venv_dir/bin/python" ]]; then
  python3 -m venv --system-site-packages "$venv_dir"
fi

"$venv_dir/bin/python" -m pip install --disable-pip-version-check -r benchmark_base/requirements-dev.txt

"$venv_dir/bin/python" - <<'PY_CHECK'
import sys
import jinja2
import numpy
import pytest
import reportlab
import scipy
from scipy.spatial import cKDTree

major, minor = (int(part) for part in numpy.__version__.split(".")[:2])
assert (major, minor) < (1, 25), f"apt SciPy needs NumPy < 1.25, got {numpy.__version__} ({numpy.__file__})"
_ = cKDTree([[0.0, 0.0, 0.0]])
print(
    "dev environment ready: "
    f"python={sys.executable} numpy={numpy.__version__} scipy={scipy.__version__} "
    f"jinja2={jinja2.__version__} reportlab={reportlab.Version} pytest={pytest.__version__}"
)
PY_CHECK
