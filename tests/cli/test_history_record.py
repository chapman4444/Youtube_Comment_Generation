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
