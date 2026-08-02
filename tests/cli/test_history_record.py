"""The explicit manual-posting boundary exposed by the CLI."""

from __future__ import annotations

import io
import json

from llm_youtube_comment_generation.infrastructure.sqlite_history import (
    SqliteHistoryStore,
)
from llm_youtube_comment_generation.interfaces.cli.main import main

VIDEO = "gC-J7zwYMAM"


def run(tmp_path, *arguments):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({
            "output_directory": str(tmp_path / "output"),
            "state_directory": str(tmp_path / "private-state"),
        }),
        encoding="utf-8",
    )
    out = io.StringIO()
    code = main(
        ["--config", str(config), "history", "record", *arguments],
        stdout=out,
        stderr=out,
        environment={},
    )
    return code, out.getvalue()


def store(tmp_path):
    return SqliteHistoryStore(
        tmp_path / "private-state" / "engagement_history.sqlite3"
    )


def test_record_requires_and_preserves_explicit_posting_context(tmp_path):
    code, printed = run(
        tmp_path,
        VIDEO,
        "--workflow", "reply",
        "--draft", "the exact manually posted reply",
        "--target", "@alice",
        "--target-comment-id", "reply-a",
        "--run-id", "run-1",
    )

    assert code == 0
    assert "Recorded as posted" in printed
    row = store(tmp_path).load()[0]
    assert row["workflow"] == "reply"
    assert row["target_comment_id"] == "reply-a"
    assert row["draft"] == "the exact manually posted reply"


def test_repeating_the_same_record_command_is_idempotent(tmp_path):
    arguments = (
        VIDEO,
        "--workflow", "comment",
        "--draft", "the manually posted comment",
        "--run-id", "run-1",
    )

    assert run(tmp_path, *arguments)[0] == 0
    _code, printed = run(tmp_path, *arguments)

    assert "already recorded" in printed
    assert len(store(tmp_path).load()) == 1


# --------------------------------------------------------------------------
# Posting-event identity
#
# The documented command supplied neither --event-id nor --run-id, and the
# store's fallback hash ignores posted_at. Two real posts of the same text to
# the same video therefore hashed identically and the second was dropped as a
# duplicate. Engagement history is the one irreplaceable thing this project
# keeps, so a silently missing event is unrecoverable.
# --------------------------------------------------------------------------


def test_recording_without_a_stable_identity_refuses_instead_of_merging(
    tmp_path,
):
    """The old documented command, which silently discarded the second post."""

    code, printed = run(
        tmp_path,
        VIDEO,
        "--workflow", "comment",
        "--draft", "the manually posted comment",
    )

    assert code != 0, "an ambiguous posting event was accepted"
    assert "no stable identity" in printed
    assert "--event-id" in printed, "the operator is not told what to add"
    assert "--run-id" in printed
    assert store(tmp_path).load() == [], "a refused event was still stored"


def test_two_identical_posts_are_kept_apart_by_their_event_ids(tmp_path):
    """The defect itself: same text, same video, two genuine postings."""

    shared = (
        VIDEO,
        "--workflow", "comment",
        "--draft", "the manually posted comment",
    )

    assert run(tmp_path, *shared, "--event-id", "post-1")[0] == 0
    assert run(tmp_path, *shared, "--event-id", "post-2")[0] == 0

    rows = store(tmp_path).load()
    assert len(rows) == 2, "a distinct posting event was discarded"


def test_repeating_one_event_id_records_it_once(tmp_path):
    """Retrying an interrupted run must not invent a second posting."""

    arguments = (
        VIDEO,
        "--workflow", "comment",
        "--draft", "the manually posted comment",
        "--event-id", "post-1",
    )

    assert run(tmp_path, *arguments)[0] == 0
    _code, printed = run(tmp_path, *arguments)

    assert "already recorded" in printed
    assert len(store(tmp_path).load()) == 1


def test_a_different_posted_at_alone_does_not_separate_two_events(tmp_path):
    """Pins the real rule, so the docstring cannot drift back.

    posted_at is deliberately absent from the fallback identity: this command
    generates one when it is omitted, so folding it in would make an ordinary
    retry insert a second row. Two timestamps are therefore not enough to tell
    two postings apart, and only an explicit identity is.
    """

    shared = (
        VIDEO,
        "--workflow", "comment",
        "--draft", "the manually posted comment",
        "--run-id", "run-1",
    )

    assert run(tmp_path, *shared, "--posted-at", "2026-08-01T00:00:00+00:00")[0] == 0
    run(tmp_path, *shared, "--posted-at", "2026-08-02T00:00:00+00:00")

    assert len(store(tmp_path).load()) == 1
