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


def test_unstaged_documentation_is_not_a_release_input(tmp_path: Path):
    """Only docs/architecture is staged, so only it can influence a gate.

    Naming individual exclusions did not hold. docs/screenshots was excluded
    first, and every recording still failed once docs/SCREENSHOTS.md was added
    beside it. A document the archive never stages cannot reach the
    reconstructed tree, so the rule follows the builder instead of chasing
    each new file.
    """

    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("answer = 42\n", encoding="utf-8")
    expected = {
        "src/example.py": hashlib.sha256(source.read_bytes()).hexdigest()
    }
    for relative in (
        "docs/screenshots/start-screen.png",
        "docs/SCREENSHOTS.md",
        "docs/some-future-note.md",
    ):
        unstaged = tmp_path / relative
        unstaged.parent.mkdir(parents=True, exist_ok=True)
        unstaged.write_bytes(b"\x89PNG\r\n\x1a\n")

    assert compare_checkout(tmp_path, expected) == ()


def test_the_documentation_allowance_stops_at_the_staged_directory(
    tmp_path: Path,
):
    """The negative proof, without which the rule could be far too broad.

    The allowance is scoped to docs/. A "screenshots" folder anywhere else,
    and the architecture notes that really are staged, remain release inputs
    and must still be manifested.
    """

    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("answer = 42\n", encoding="utf-8")
    expected = {
        "src/example.py": hashlib.sha256(source.read_bytes()).hexdigest()
    }
    for relative in (
        "screenshots/top-level.png",
        "src/screenshots/bundled.png",
        "docs/architecture/01_ARCHITECTURE_OVERVIEW.md",
    ):
        extra = tmp_path / relative
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_bytes(b"extra\n")

    problems = compare_checkout(tmp_path, expected)

    assert "unmanifested: screenshots/top-level.png" in problems
    assert "unmanifested: src/screenshots/bundled.png" in problems
    assert (
        "unmanifested: docs/architecture/01_ARCHITECTURE_OVERVIEW.md"
        in problems
    )


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
# The builder and the release-input rule must agree
#
# make_review_zip.bat stages by allowlist: six robocopy calls and a list of
# named files. release_input_files excludes by denylist. Two opposite
# policies over one domain drift by construction, and every drift is a
# recording that fails ~13 minutes in with "unmanifested".
#
# It happened twice: docs/screenshots, then docs/SCREENSHOTS.md added beside
# it. Both were release inputs the moment they existed and neither was
# staged. This turns that into a one-second failure.
# --------------------------------------------------------------------------


def top_level_release_inputs(root: Path) -> list[str]:
    """Top-level names the builder is responsible for putting in the stage.

    The evidence files are generated inside the stage by
    create_review_evidence.py rather than copied into it, so the builder
    never names them and should not have to. Running this check inside an
    extracted archive is what surfaced that: the manifest sits at the top
    level there and would otherwise look like something the builder forgot.
    """

    return sorted({
        path.relative_to(root).as_posix().split("/")[0]
        for path in release_input_files(root)
        if path.name not in GENERATED_IN_STAGE
    })


def test_every_release_input_is_named_by_the_archive_builder():
    """A new top-level file or directory must be staged or excluded.

    Being neither is the silent failure: it counts as a release input the
    moment it is created, never reaches the staged tree, and the mismatch
    only surfaces once the whole matrix has run.
    """

    builder = (ROOT / "make_review_zip.bat").read_text(encoding="utf-8")

    unnamed = [
        name for name in top_level_release_inputs(ROOT)
        if name not in builder
    ]

    assert not unnamed, (
        "these are release inputs but make_review_zip.bat never names them, "
        "so a recording would fail on 'unmanifested': " + ", ".join(unnamed)
    )


def test_the_builder_check_would_notice_an_unstaged_addition(tmp_path: Path):
    """The negative proof: a tree whose builder names nothing must fail."""

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "example.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "deploy.py").write_text("x = 1\n", encoding="utf-8")

    names = top_level_release_inputs(tmp_path)

    assert "scripts" in names, "a new top-level directory was not even seen"
    assert "src" in names
