from __future__ import annotations

import hashlib
from pathlib import Path

from tools.create_review_evidence import (
    GateResult,
    compare_final_tree,
    remove_generated_test_artifacts,
    snapshot_hashes,
    verification_provenance,
    write_evidence,
    snapshot_files,
    write_manifest,
)


def test_manifest_is_stable_portable_and_excludes_evidence(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "example.py").write_text(
        "answer = 42\n", encoding="utf-8"
    )
    (tmp_path / "REVIEW_VERIFICATION.md").write_text(
        "old evidence", encoding="utf-8"
    )

    files = snapshot_files(tmp_path)
    digest = write_manifest(tmp_path, files)
    manifest = (tmp_path / "REVIEW_FILE_MANIFEST.sha256").read_text(
        encoding="utf-8"
    )

    file_digest = hashlib.sha256(
        (tmp_path / "src" / "example.py").read_bytes()
    ).hexdigest()
    assert files == (tmp_path / "src" / "example.py",)
    assert manifest == f"{file_digest}  src/example.py\n"
    assert digest == hashlib.sha256(manifest.encode()).hexdigest()


def test_generated_test_caches_are_removed_without_touching_source(
    tmp_path: Path,
):
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("answer = 42\n", encoding="utf-8")
    bytecode = tmp_path / "src" / "__pycache__" / "example.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"generated")
    pytest_cache = tmp_path / ".pytest_cache" / "v" / "cache"
    pytest_cache.mkdir(parents=True)
    (pytest_cache / "nodeids").write_text("[]", encoding="utf-8")
    ruff_cache = tmp_path / ".ruff_cache"
    ruff_cache.mkdir()
    (ruff_cache / "CACHEDIR.TAG").write_text("generated", encoding="utf-8")

    remove_generated_test_artifacts(tmp_path)

    assert source.is_file()
    assert not bytecode.parent.exists()
    assert not (tmp_path / ".pytest_cache").exists()
    assert not ruff_cache.exists()


def test_final_tree_rejects_added_modified_and_deleted_files(tmp_path: Path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("first\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")
    expected = snapshot_hashes(tmp_path)

    first.write_text("modified\n", encoding="utf-8")
    second.unlink()
    (tmp_path / "added.py").write_text("added\n", encoding="utf-8")

    problems = "\n".join(compare_final_tree(tmp_path, expected))

    assert "added files" in problems
    assert "modified files" in problems
    assert "missing files" in problems


def test_empty_runtime_output_is_removed_before_final_comparison(
    tmp_path: Path,
):
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    expected = snapshot_hashes(tmp_path)
    (tmp_path / "output").mkdir()

    remove_generated_test_artifacts(tmp_path)

    assert not (tmp_path / "output").exists()
    assert compare_final_tree(tmp_path, expected) == ()


def test_unexpected_empty_directory_is_rejected(tmp_path: Path):
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    expected = snapshot_hashes(tmp_path)
    (tmp_path / "surprise").mkdir()

    problems = "\n".join(compare_final_tree(tmp_path, expected))

    assert "unexpected directories" in problems
    assert "surprise" in problems


def test_evidence_discloses_material_overrides_versions_and_exit_codes(
    tmp_path: Path,
):
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    files = snapshot_files(tmp_path)
    environment = {
        "PYTHONPATH": str(tmp_path / "src"),
        "PYTEST_ADDOPTS": "--strict-markers",
    }
    provenance = verification_provenance(tmp_path, environment)

    write_evidence(
        tmp_path,
        files=files,
        manifest_digest="a" * 64,
        gates=(GateResult("Tests", "python -m pytest", 0, "1 passed"),),
        provenance=provenance,
    )
    report = (tmp_path / "REVIEW_VERIFICATION.md").read_text(
        encoding="utf-8"
    )

    assert "PYTHONPATH: `<review-root>/src`" in report
    assert "PYTEST_ADDOPTS: `--strict-markers`" in report
    assert "Python executable:" in report
    assert "pytest:" in report
    assert "ruff:" in report
    assert "requests:" in report
    assert "Exit code: `0`" in report
    assert str(tmp_path) not in report
    assert "## Evidence layers" in report
    assert "Test source is not a test result" in report
    assert "not an independent reviewer rerun" in report
    assert "clean-wheel installation" in report
    assert "explicitly does not claim those results" in report
