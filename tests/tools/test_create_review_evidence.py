from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.create_review_evidence import (
    GateResult,
    compare_final_tree,
    remove_generated_test_artifacts,
    snapshot_hashes,
    validate_release_evidence,
    verification_provenance,
    write_evidence,
    snapshot_files,
    write_manifest,
)
from tools.release_evidence_format import (
    clean_install_payload,
    render_release_report,
)


def write_valid_release_evidence(root: Path, digest: str) -> dict:
    clean_payload = {
        "wheel": "package-0.1-py3-none-any.whl",
        "wheel_sha256": "1" * 64,
        "sdist": "package-0.1.tar.gz",
        "sdist_sha256": "2" * 64,
    }
    gates = []
    for name in (
        "Python 3.10 Windows matrix",
        "Python 3.11 Windows matrix",
        "Python 3.12 Windows matrix",
        "Two-run determinism",
        "Clean-wheel installation",
    ):
        output = (
            json.dumps(clean_payload, indent=2)
            if name == "Clean-wheel installation"
            else "gate passed"
        )
        gates.append({
            "name": name,
            "commands": ["python gate.py"],
            "returncode": 0,
            "status": "PASS",
            "output": output,
            "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        })
    record = {
        "schema_version": 1,
        "recorder": "tools/record_release_verification.py",
        "generated": "2026-07-30T12:00:00+00:00",
        "manifest_sha256": digest,
        "review_archive": "review.zip",
        "source_tree_mode": "manifest-reconstructed",
        "overall_result": "PASSED",
        "initial_source_identity": {"status": "PASS", "problems": []},
        "gates": gates,
        "final_source_identity": {"status": "PASS", "problems": []},
        "distribution_artifacts": clean_payload,
    }
    (root / "RELEASE_VERIFICATION.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "RELEASE_VERIFICATION.md").write_text(
        render_release_report(record), encoding="utf-8"
    )
    return record


def test_clean_install_payload_allows_recorded_exit_line_after_json():
    output = (
        "$ python tools/verify_clean_install.py\n"
        '{"wheel": "example.whl", "wheel_sha256": "'
        + "a" * 64
        + '"}\n[exit code 0]'
    )

    assert clean_install_payload(output)["wheel"] == "example.whl"


def test_manifest_is_stable_portable_and_excludes_evidence(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "example.py").write_text(
        "answer = 42\n", encoding="utf-8"
    )
    (tmp_path / "REVIEW_VERIFICATION.md").write_text(
        "old evidence", encoding="utf-8"
    )
    (tmp_path / "RELEASE_VERIFICATION.md").write_text(
        "old release evidence", encoding="utf-8"
    )
    generated = tmp_path / "tools" / "__pycache__" / "helper.pyc"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"generated")

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


def test_release_evidence_must_match_the_manifest_and_every_release_gate(
    tmp_path: Path,
):
    digest = "a" * 64
    write_valid_release_evidence(tmp_path, digest)

    assert validate_release_evidence(tmp_path, digest)


def test_stale_release_evidence_is_rejected(tmp_path: Path):
    write_valid_release_evidence(tmp_path, "b" * 64)

    with pytest.raises(ValueError, match="stale, incomplete"):
        validate_release_evidence(tmp_path, "a" * 64)


def test_token_only_release_report_is_rejected(tmp_path: Path):
    digest = "a" * 64
    (tmp_path / "RELEASE_VERIFICATION.md").write_text(
        "- Overall result: **PASSED**\n"
        f"- Manifest SHA-256: `{digest}`\n"
        "## Python 3.10 Windows matrix: PASS\n"
        "## Python 3.11 Windows matrix: PASS\n"
        "## Python 3.12 Windows matrix: PASS\n"
        "## Two-run determinism: PASS\n"
        "## Clean-wheel installation: PASS\n"
        "## Final source identity: PASS\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="incomplete"):
        validate_release_evidence(tmp_path, digest)


def test_nonzero_exit_code_behind_pass_is_rejected(tmp_path: Path):
    digest = "a" * 64
    record = write_valid_release_evidence(tmp_path, digest)
    record["gates"][0]["returncode"] = 1
    (tmp_path / "RELEASE_VERIFICATION.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    (tmp_path / "RELEASE_VERIFICATION.md").write_text(
        render_release_report(record), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="nonzero"):
        validate_release_evidence(tmp_path, digest)


def test_duplicate_or_contradictory_gate_is_rejected(tmp_path: Path):
    digest = "a" * 64
    record = write_valid_release_evidence(tmp_path, digest)
    duplicate = dict(record["gates"][0])
    duplicate["status"] = "FAIL"
    record["gates"].append(duplicate)
    (tmp_path / "RELEASE_VERIFICATION.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    (tmp_path / "RELEASE_VERIFICATION.md").write_text(
        render_release_report(record), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="duplicated"):
        validate_release_evidence(tmp_path, digest)


def test_truncated_release_report_is_rejected(tmp_path: Path):
    digest = "a" * 64
    write_valid_release_evidence(tmp_path, digest)
    report = tmp_path / "RELEASE_VERIFICATION.md"
    report.write_text(
        report.read_text(encoding="utf-8")[:100], encoding="utf-8"
    )

    with pytest.raises(ValueError, match="does not exactly match"):
        validate_release_evidence(tmp_path, digest)


def test_altered_wheel_hash_is_rejected(tmp_path: Path):
    digest = "a" * 64
    record = write_valid_release_evidence(tmp_path, digest)
    record["distribution_artifacts"]["wheel_sha256"] = "f" * 64
    (tmp_path / "RELEASE_VERIFICATION.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    (tmp_path / "RELEASE_VERIFICATION.md").write_text(
        render_release_report(record), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="contradicts"):
        validate_release_evidence(tmp_path, digest)


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
