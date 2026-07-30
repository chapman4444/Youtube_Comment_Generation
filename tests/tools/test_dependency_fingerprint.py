from __future__ import annotations

from pathlib import Path

from tools.dependency_fingerprint import fingerprint


def test_dependency_fingerprint_changes_with_project_metadata(tmp_path: Path):
    (tmp_path / "constraints").mkdir()
    project = tmp_path / "pyproject.toml"
    constraints = tmp_path / "constraints" / "review.txt"
    project.write_text("[project]\nname='example'\n", encoding="utf-8")
    constraints.write_text("requests==2.32.5\n", encoding="utf-8")
    original = fingerprint(tmp_path)

    project.write_text(
        "[project]\nname='example'\ndependencies=['packaging']\n",
        encoding="utf-8",
    )

    assert fingerprint(tmp_path) != original


def test_dependency_fingerprint_changes_with_reviewed_constraints(
    tmp_path: Path,
):
    (tmp_path / "constraints").mkdir()
    project = tmp_path / "pyproject.toml"
    constraints = tmp_path / "constraints" / "review.txt"
    project.write_text("[project]\nname='example'\n", encoding="utf-8")
    constraints.write_text("requests==2.32.5\n", encoding="utf-8")
    original = fingerprint(tmp_path)

    constraints.write_text("requests==2.32.6\n", encoding="utf-8")

    assert fingerprint(tmp_path) != original
