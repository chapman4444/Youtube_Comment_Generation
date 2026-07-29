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

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Directories and files that must never be committed. Each is something a
#: real run writes into the working tree.
MUST_BE_IGNORED = (
    "output/",
    "posted_history.json",
    "comment_drafts.md",
    "replies_to_review.md",
    "window_settings.json",
)

#: Shapes of identifying data. Checked against everything that would be
#: committed, not only the files somebody remembered to look at.
IDENTIFIERS = (
    # A YouTube channel id, which names a person as precisely as a handle.
    re.compile(r"\bUC[A-Za-z0-9_-]{22}\b"),
    # A Windows home directory, which carries the account name.
    re.compile(r"[Cc]:\\Users\\(?!<)[A-Za-z0-9._-]+"),
)

TEXT_SUFFIXES = {".py", ".bat", ".md", ".txt", ".json", ".toml", ".cfg", ".ini"}

SKIP_DIRECTORIES = {
    "output", "__pycache__", ".git", ".venv", "venv", ".pytest_cache",
    "ab_compare", "previous_runs", "node_modules", "build", "dist",
}


def committable_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if SKIP_DIRECTORIES & set(path.relative_to(ROOT).parts):
            continue
        yield path


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

    offenders: list[str] = []
    for path in committable_files():
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in IDENTIFIERS:
            for found in pattern.findall(body):
                offenders.append(f"{path.relative_to(ROOT)}: {found}")

    assert not offenders, (
        "identifying data in files that would be committed:\n  "
        + "\n  ".join(sorted(set(offenders))[:20])
    )


def test_the_api_key_is_never_written_down():
    """It lives in the environment. The key file was deleted on purpose."""

    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "YOUTUBE_API_KEY.txt" in ignored
    assert "*.key" in ignored
