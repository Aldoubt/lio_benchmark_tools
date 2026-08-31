from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_freeze_gate_separates_system_python_from_freeze_python():
    script = (ROOT / "evaluators/check_freeze_pipeline.sh").read_text(encoding="utf-8")
    assert "PYTHONNOUSERSITE=1" in script
    assert "--freeze-python" in script
    assert ".venv-freeze/bin/python" in script


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
