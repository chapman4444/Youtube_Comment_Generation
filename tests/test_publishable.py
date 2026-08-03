"""Nothing in this repository may identify the operator or anyone else.

He intends to publish it. Until he said so there was no .gitignore at all,
which meant publishing would have carried `output/` with it: hundreds of real
YouTube users' display names and their words, fetched to build one packet. It
is not ours to republish.

Two separate hazards, and both had already happened once:

**His identity.** A handle was hardcoded in a launcher.

**Other people's.** Fetched comment sections, his own drafts, and his
measurement history all sit in the working tree beside the code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_youtube_comment_generation.application.privacy import (
    audit_files,
    render_findings,
)
from llm_youtube_comment_generation.infrastructure.git_files import tracked_files

ROOT = Path(__file__).resolve().parents[1]

#: Directories and files that must never be committed. Each is something a
#: real run writes into the working tree.
MUST_BE_IGNORED = (
    "output/",
    "posted_history.json",
    "comment_drafts.md",
    "replies_to_review.md",
    "window_settings.json",
    "writing_presets.json",
)

# Resolve this at collection time, before the harness blocks subprocesses.
# The publishable set is Git's index, not a second denylist that can drift
# away from .gitignore and accuse ignored private notes or release artifacts.
TRACKED_FILES = tracked_files(ROOT)


def test_a_gitignore_exists_at_all():
    """There was none. Everything below depends on this one existing."""

    assert (ROOT / ".gitignore").is_file()


@pytest.mark.parametrize("entry", MUST_BE_IGNORED)
def test_what_a_run_writes_is_never_committed(entry):
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert entry in ignored, (
        f"{entry} is written by a real run and is not ignored. "
        "Publishing would carry it."
    )


def test_no_committable_file_names_a_person():
    """Channel ids and home paths, anywhere that would be published.

    Scanned rather than spot-checked so documentation cannot become an
    unnoticed identity leak.
    """

    findings = audit_files(ROOT, TRACKED_FILES)

    assert not findings, render_findings(findings)


def test_ignored_work_and_release_directories_are_not_committable():
    tracked = {Path(relative).parts[0].casefold() for relative in TRACKED_FILES}

    assert not tracked & {
        "env",
        "local_notes",
        "models",
        "review_packages",
    }


def test_the_api_key_is_never_written_down():
    """It lives in the environment. The key file was deleted on purpose."""

    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "YOUTUBE_API_KEY.txt" in ignored
    assert "*.key" in ignored


def test_local_work_notes_are_ignored_in_every_clone():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "/local_notes/" in ignored
    for name in ("HANDOFF.md", "CHANGES_MADE.md", "cmd_dump.ahk"):
        assert f"/{name}" in ignored
