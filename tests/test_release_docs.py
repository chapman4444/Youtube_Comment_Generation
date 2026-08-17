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


def test_clean_install_frontend_is_declared_and_documented():
    project = text("pyproject.toml")
    readme = text("README.md")
    tool = text("tools/verify_clean_install.py")

    assert 'verify = ["pytest>=7.4", "build>=1.2"]' in project
    assert '.[verify,transcripts]' in readme
    assert '.[local-transcription]' in readme
    assert '[verify,transcripts,local-transcription]' in tool
    for dependency in (
        "youtube_transcript_api",
        "yt_dlp",
        "faster_whisper",
    ):
        assert dependency in tool


def test_the_readme_separates_the_three_evidence_layers():
    """The evidence-layer contract lived in REVIEW_PROMPT.md until the
    operator had that file removed (2026-08-17); the contract itself is
    load-bearing — reviews have been marked down for collapsing the
    layers — so it moved into the README's Review package section rather
    than leaving with the file."""

    readme = text("README.md")
    normalized = " ".join(readme.split())

    assert not (ROOT / "REVIEW_PROMPT.md").exists(), (
        "REVIEW_PROMPT.md was removed at the operator's direction; its "
        "evidence-layer contract lives in the README now"
    )
    assert "Source and tests in the snapshot" in readme
    assert "Recorded staged verification" in readme
    assert "Separately recorded release gates" in readme
    assert "is not proof that a test ran or passed" in normalized
    assert "not a fresh execution performed by the reviewer" in normalized
    assert "validated companion release evidence is included" in normalized
    assert "those release gates remain unverified" in normalized
    assert "not an independent reviewer rerun" in normalized
    assert "explicitly does not claim" not in readme


def test_architecture_documents_state_the_implemented_contracts():
    structure = text("docs/architecture/02_PROJECT_STRUCTURE.md")
    pipeline = text("docs/architecture/05_PACKET_BUILD_PIPELINE.md")
    interfaces = text("docs/architecture/06_CLI_GUI_CONTRACT.md")

    assert structure.startswith("# Current Project Structure")
    assert "one build never" in pipeline
    assert "same directory as `packet.md` and `run.json`" in pipeline
    assert "--window --dry-run" in interfaces
    assert "reply_scan_comments" in interfaces
    assert "Record as posted" in interfaces


# --------------------------------------------------------------------------
# The README carries no local image reference
#
# The gallery reached reviewers as fourteen broken images while the archive
# staged an allowlist that omitted docs/screenshots. Rewriting the README
# during staging was tried and reverted: it broke the byte-identical match
# between the archived files and the checkout, which is the property the
# release evidence exists to prove. Linking the gallery out worked but split
# the documentation in two.
#
# git archive HEAD stages every committed file, so the images ship and the
# references resolve. This runs in whichever tree it sits in, the repository
# and the archive alike, and resolving each path is meaningful in both now
# that neither is missing them by design.
# --------------------------------------------------------------------------

import re

IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def local_image_references(markdown: str) -> list[str]:
    found = []
    for target in IMAGE.findall(markdown):
        reference = target.split()[0].strip("<>")
        if reference.startswith(("http://", "https://", "data:", "#")):
            continue
        found.append(reference)
    return found


def test_the_scan_recognises_a_local_image_and_ignores_a_remote_one():
    """Otherwise an empty result would prove nothing about the README."""

    sample = (
        "![a](docs/screenshots/one.png) "
        "![b](https://example.invalid/badge.svg)"
    )

    assert local_image_references(sample) == ["docs/screenshots/one.png"]


def test_every_local_readme_image_resolves_in_this_tree():
    found = local_image_references(text("README.md"))
    missing = [
        reference for reference in found if not (ROOT / reference).is_file()
    ]

    assert found, "the README gallery has lost every image"
    assert not missing, (
        "README references local images absent from this tree: "
        + ", ".join(sorted(missing))
    )

