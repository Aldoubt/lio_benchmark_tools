#!/usr/bin/env bash
set -euo pipefail

# Run the unit tests in .venv-dev with ~/.local hidden.
# Usage: ./evaluators/run_tests.sh [pytest args...]

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

venv_dir="${LIO_DEV_VENV:-$repo_root/.venv-dev}"
if [[ ! -x "$venv_dir/bin/python" ]]; then
  echo "missing $venv_dir; run ./evaluators/setup_dev_venv.sh first" >&2
  exit 2
fi

export PYTHONNOUSERSITE=1
if [[ -f /opt/ros/humble/setup.bash ]]; then
  set +u
  # shellcheck disable=SC1091
  source /opt/ros/humble/setup.bash
  set -u
fi
exec "$venv_dir/bin/python" -m pytest -q "$@"
