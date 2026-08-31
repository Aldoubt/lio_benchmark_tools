from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_freeze_gate_separates_system_python_from_freeze_python():
    script = (ROOT / "evaluators/check_freeze_pipeline.sh").read_text(encoding="utf-8")
    assert "PYTHONNOUSERSITE=1" in script
    assert "--freeze-python" in script
    assert ".venv-freeze/bin/python" in script
    assert "freeze_py()" in script
    assert "freeze_py -m pytest -q" in script


def test_freeze_requirements_pin_numpy2_compatible_scientific_stack():
    requirements = (ROOT / "benchmark_base/requirements-freeze.txt").read_text(
        encoding="utf-8"
    )
    for item in (
        "numpy==2.2.6",
        "scipy==1.14.1",
        "matplotlib==3.10.5",
        "rerun-sdk==0.36.3",
        "Jinja2==3.1.6",
        "reportlab==4.4.9",
    ):
        assert item in requirements


def test_freeze_venv_setup_is_repo_local_and_keeps_ros_system_packages_visible():
    script = (ROOT / "evaluators/setup_freeze_venv.sh").read_text(encoding="utf-8")
    assert "python3 -m venv --system-site-packages" in script
    assert ".venv-freeze" in script
    assert "benchmark_base/requirements-freeze.txt" in script
    assert "python3 -m pip install 'rerun-sdk==0.36.3'" not in script


def test_freeze_venv_dependency_resolution_ignores_user_site():
    script = (ROOT / "evaluators/setup_freeze_venv.sh").read_text(encoding="utf-8")
    assert (
        'env PYTHONNOUSERSITE=1 "$venv_dir/bin/python" -m pip install --upgrade pip'
        in script
    )
    assert (
        'env PYTHONNOUSERSITE=1 "$venv_dir/bin/python" -m pip install '
        '-r benchmark_base/requirements-freeze.txt'
        in script
    )
    assert "import pyarrow" in script
    assert "import jinja2" in script


def test_freeze_setup_does_not_global_pip_check_inherited_ros_packages():
    script = (ROOT / "evaluators/setup_freeze_venv.sh").read_text(encoding="utf-8")
    assert "-m pip check" not in script
    assert "from scipy.spatial import cKDTree" in script
    assert "import rerun" in script
    assert "import pyarrow" in script


def test_report_and_rerun_tests_run_in_freeze_python_not_system_python():
    script = (ROOT / "evaluators/check_freeze_pipeline.sh").read_text(encoding="utf-8")
    marker = "freeze_py -m pytest -q"
    assert marker in script
    freeze_section = script.split(marker, 1)[1]
    for test_name in (
        "tests/test_freeze_rerun.py",
        "tests/test_report_html.py",
        "tests/test_report_pdf.py",
        "tests/test_report_pointcloud_evidence.py",
    ):
        assert test_name in freeze_section


def test_freeze_python_path_normalization_does_not_resolve_venv_symlink():
    script = (ROOT / "evaluators/check_freeze_pipeline.sh").read_text(encoding="utf-8")
    normalization_line = next(
        line for line in script.splitlines() if line.startswith("freeze_python=$(")
    )
    assert "os.path.abspath" in normalization_line
    assert ".resolve()" not in normalization_line
