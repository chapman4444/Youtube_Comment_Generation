"""Release documentation must describe the implemented project truthfully."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_readme_no_longer_describes_a_prebuild_planning_workspace():
    readme = text("README.md").lower()

    for stale in (
        "phases.md does not exist",
        "create phases.md",
        "do not write production code yet",
        "stop and wait for approval",
        "clean-rebuild planning workspace",
    ):
        assert stale not in readme
    for current in (
        "python 3.10",
        "ytcomment --help",
        "verify_clean_install.py",
        "nothing is posted",
    ):
        assert current in readme


def test_package_manifest_includes_authoritative_resources():
    project = text("pyproject.toml")

    assert "[tool.setuptools.package-data]" in project
    assert '"prompts/*.md"' in project
    assert '"prompts/*.json"' in project
    assert '"wordlists/*.txt"' in project
