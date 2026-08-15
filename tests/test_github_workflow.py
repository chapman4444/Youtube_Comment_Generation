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


def test_the_readme_ci_sentence_matches_the_workflow_reality():
    """The old honesty test was a substring check, so restricting three
    gates to Python 3.12 kept it green while the README claimed all three
    versions ran everything. This one compares the claim to the guards."""

    from pathlib import Path

    workflow = Path(".github/workflows/quality.yml").read_text(
        encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    guarded_steps = workflow.count("if: matrix.python-version == '3.12'")

    # The workflow really does restrict some gates to 3.12 — and the README
    # must say so rather than claiming the full matrix runs everything.
    assert guarded_steps >= 3
    compact = " ".join(readme.split())
    assert ("transcript-provider imports, two-run determinism gate, and "
            "clean-wheel install run on Python 3.12 only") in compact
    assert "clean-wheel install on Windows with Python 3.10" not in compact
