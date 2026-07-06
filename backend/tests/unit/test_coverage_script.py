import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "coverage.sh"


def test_coverage_script_exists_and_is_executable() -> None:
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert SCRIPT.stat().st_mode & 0o111, f"{SCRIPT} is not executable"


def test_coverage_script_help_does_not_explode() -> None:
    """A `--help` invocation must succeed without running tests."""
    r = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "coverage" in r.stdout.lower()
