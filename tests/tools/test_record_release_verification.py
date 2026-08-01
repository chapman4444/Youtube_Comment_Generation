from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from tools.record_release_verification import (
    _redact,
    compare_checkout,
    load_archive_manifest,
    reconstruct_manifest_tree,
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


def test_readme_screenshots_are_not_release_inputs(tmp_path: Path):
    """A PNG cannot change what pytest, ruff or pip check do.

    make_review_zip.bat stages docs\\architecture and not docs\\screenshots.
    While the illustrations counted as release inputs the two tools could never
    agree, and every recording failed on fourteen "unmanifested" entries before
    a single gate ran.
    """

    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("answer = 42\n", encoding="utf-8")
    expected = {
        "src/example.py": hashlib.sha256(source.read_bytes()).hexdigest()
    }
    shot = tmp_path / "docs" / "screenshots" / "start-screen.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"\x89PNG\r\n\x1a\n")

    assert compare_checkout(tmp_path, expected) == ()


def test_the_screenshot_allowance_is_pinned_to_its_one_location(tmp_path: Path):
    """The negative proof, without which the rule could be far too broad.

    The exclusion is a path, not a directory name. A "screenshots" folder
    somewhere else, and the architecture notes beside it, are still release
    inputs and must still be manifested.
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
