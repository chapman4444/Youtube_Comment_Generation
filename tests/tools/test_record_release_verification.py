from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from tools.create_review_evidence import EXCLUDED_NAMES as GENERATED_IN_STAGE
from tools.record_release_verification import (
    ROOT,
    _redact,
    compare_checkout,
    load_archive_manifest,
    reconstruct_manifest_tree,
    release_input_files,
)


def write_archive(path: Path, manifest: str) -> None:
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("REVIEW_FILE_MANIFEST.sha256", manifest)


def test_archive_manifest_is_loaded_with_its_own_identity(tmp_path: Path):
    source = b"answer = 42\n"
    file_digest = hashlib.sha256(source).hexdigest()
    manifest = f"{file_digest}  src/example.py\n"
    archive = tmp_path / "review.zip"
    write_archive(archive, manifest)

    digest, entries = load_archive_manifest(archive)

    assert digest == hashlib.sha256(manifest.encode()).hexdigest()
    assert entries == {"src/example.py": file_digest}


def test_checkout_comparison_reports_missing_and_mismatched_files(
    tmp_path: Path,
):
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("wrong\n", encoding="utf-8")
    expected = {
        "src/example.py": hashlib.sha256(b"right\n").hexdigest(),
        "src/missing.py": hashlib.sha256(b"missing\n").hexdigest(),
    }

    problems = compare_checkout(tmp_path, expected)

    assert "mismatched: src/example.py" in problems
    assert "missing: src/missing.py" in problems


@pytest.mark.parametrize(
    "relative",
    (
        "src/extra.py",
        "conftest.py",
        "pytest.ini",
        "src/package/data.bin",
        "ordinary-unrelated.txt",
    ),
)
def test_checkout_comparison_rejects_every_unmanifested_release_input(
    tmp_path: Path,
    relative: str,
):
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("answer = 42\n", encoding="utf-8")
    expected = {
        "src/example.py": hashlib.sha256(source.read_bytes()).hexdigest()
    }
    extra = tmp_path / relative
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text("extra\n", encoding="utf-8")

    problems = compare_checkout(tmp_path, expected)

    assert f"unmanifested: {Path(relative).as_posix()}" in problems


def test_checkout_comparison_ignores_only_known_runtime_material(
    tmp_path: Path,
):
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("answer = 42\n", encoding="utf-8")
    expected = {
        "src/example.py": hashlib.sha256(source.read_bytes()).hexdigest()
    }
    runtime = tmp_path / ".venv" / "generated.py"
    runtime.parent.mkdir()
    runtime.write_text("runtime\n", encoding="utf-8")

    assert compare_checkout(tmp_path, expected) == ()


def test_manifest_tree_contains_only_verified_manifest_inputs(tmp_path: Path):
    source = tmp_path / "checkout" / "src" / "example.py"
    source.parent.mkdir(parents=True)
    source.write_text("answer = 42\n", encoding="utf-8")
    (tmp_path / "checkout" / "unmanifested.py").write_text(
        "not copied\n", encoding="utf-8"
    )
    entries = {
        "src/example.py": hashlib.sha256(source.read_bytes()).hexdigest()
    }
    destination = tmp_path / "release-source"

    reconstruct_manifest_tree(tmp_path / "checkout", destination, entries)

    assert (destination / "src" / "example.py").is_file()
    assert not (destination / "unmanifested.py").exists()
    assert (destination / "REVIEW_FILE_MANIFEST.sha256").is_file()


def test_invalid_manifest_line_is_rejected(tmp_path: Path):
    archive = tmp_path / "review.zip"
    write_archive(archive, "not a manifest line\n")

    with pytest.raises(ValueError, match="invalid"):
        load_archive_manifest(archive)


def test_redaction_handles_case_and_repeated_windows_separators():
    home = str(Path.home()).replace("\\", "/")
    lower = home.lower()
    doubled = home.replace("/", "//")

    redacted = _redact(f"{lower}/one\n{doubled}/two")

    assert str(Path.home()).lower() not in redacted.lower()
    assert "<user-home>/one" in redacted
    assert "<user-home>/two" in redacted


# --------------------------------------------------------------------------
# The builder stages the committed tree
#
# It used to stage from an allowlist of six robocopy calls and twelve named
# files, while release_input_files excluded by denylist. Two opposite
# policies over one domain drift by construction, and each drift cost a full
# release-matrix run to find: docs/screenshots was a release input that was
# never staged, then docs/SCREENSHOTS.md was added beside it and did the
# same. Exporting the commit removes the second policy, so a file cannot be
# committed and unstaged at the same time.
# --------------------------------------------------------------------------


def test_the_builder_exports_the_committed_tree():
    """A silent return to hand-listed staging is the regression to catch."""

    builder = (ROOT / "make_review_zip.bat").read_text(encoding="utf-8")

    assert "git" in builder and "archive" in builder, (
        "the builder no longer exports the tree with git archive"
    )
    assert "HEAD" in builder, "the builder does not export a commit"

    # Invocations, not prose. The comment above the export explains what it
    # replaced, and matching the bare word would fail on that explanation.
    copying = [
        line.strip() for line in builder.splitlines()
        if line.strip().lower().startswith(("robocopy ", "xcopy "))
    ]
    assert not copying, (
        "hand-listed staging is back; it drifts from the release-input rule: "
        + "; ".join(copying)
    )


def test_documentation_is_a_release_input_now_that_it_is_staged(
    tmp_path: Path,
):
    """The exclusion existed only because docs were not staged.

    git archive exports everything committed, so the documentation ships like
    any other tracked file and must be manifested with it.
    """

    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("answer = 42\n", encoding="utf-8")
    expected = {
        "src/example.py": hashlib.sha256(source.read_bytes()).hexdigest()
    }
    for relative in ("docs/screenshots/start-screen.png", "docs/SCREENSHOTS.md"):
        extra = tmp_path / relative
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_bytes(b"documentation\n")

    problems = compare_checkout(tmp_path, expected)

    assert "unmanifested: docs/screenshots/start-screen.png" in problems
    assert "unmanifested: docs/SCREENSHOTS.md" in problems


def test_runtime_material_is_still_not_a_release_input(tmp_path: Path):
    """Widening the rule must not have swept in the private state trees."""

    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("answer = 42\n", encoding="utf-8")
    expected = {
        "src/example.py": hashlib.sha256(source.read_bytes()).hexdigest()
    }
    for relative in (
        ".venv/generated.py",
        "output/run/packet.md",
        "review_packages/old.zip",
        "local_notes/private.md",
        "src/__pycache__/example.cpython-310.pyc",
    ):
        noise = tmp_path / relative
        noise.parent.mkdir(parents=True, exist_ok=True)
        noise.write_text("runtime\n", encoding="utf-8")

    assert compare_checkout(tmp_path, expected) == ()
