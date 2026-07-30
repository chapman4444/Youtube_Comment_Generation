from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_quality_workflow_covers_supported_python_and_privacy():
    workflow = (ROOT / ".github" / "workflows" / "quality.yml").read_text(
        encoding="utf-8"
    )

    for version in ("3.10", "3.11", "3.12"):
        assert f'"{version}"' in workflow
    assert "privacy_audit.py" in workflow
    assert "pytest -q" in workflow
    assert "verify_clean_install.py" in workflow
    assert "verify_two_runs.py" in workflow
    assert "faster_whisper" in workflow
    assert "constraints/review.txt" in workflow
    assert "PIP_CONSTRAINT" in workflow
