"""The engagement history store and its migration.

The migration touches the operator's real measurement record, so the
guarantee it makes is that it does not touch it at all.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from llm_youtube_comment_generation.domain.errors import HistoryCorruptionError
from llm_youtube_comment_generation.infrastructure.sqlite_history import (
    SqliteHistoryStore,
    digest_of,
    migrate_json,
)


def store_at(tmp_path):
    return SqliteHistoryStore(tmp_path / "history.sqlite3")


def draft(text, video="v1", **extra):
    return {"video_id": video, "draft": text, **extra}


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def test_a_missing_store_is_simply_an_empty_one(tmp_path):
    assert store_at(tmp_path).load() == []


def test_a_recorded_draft_comes_back(tmp_path):
    store = store_at(tmp_path)

    assert store.append([draft("the reply text", video="v1")]) == 1

    rows = store.load()
    assert len(rows) == 1
    assert rows[0]["draft"] == "the reply text"
    assert rows[0]["video_id"] == "v1"


def test_recording_the_same_draft_twice_adds_one_row(tmp_path):
    """Two rows for one reply would double-count the likes it earns, and
    those numbers are the only measurement this project has."""

    store = store_at(tmp_path)
    entry = draft("identical text")

    assert store.append([entry]) == 1
    assert store.append([entry]) == 0
    assert len(store.load()) == 1


def test_a_lightly_edited_draft_is_the_same_draft(tmp_path):
    store = store_at(tmp_path)
    store.append([draft("The Same Reply, Text!")])

    assert store.append([draft("the same reply text")]) == 0


def test_the_same_text_under_two_videos_is_two_drafts(tmp_path):
    """Deduplication is per video: the same reply on two videos earns two
    separate outcomes."""

    store = store_at(tmp_path)
    store.append([draft("nice video", video="v1")])

    assert store.append([draft("nice video", video="v2")]) == 1
    assert len(store.load()) == 2


def test_an_empty_draft_is_never_recorded(tmp_path):
    assert store_at(tmp_path).append([draft("   ")]) == 0


def test_the_prompt_version_is_recorded_with_the_draft(tmp_path):
    """So a scoreboard can eventually attribute results to the prompt that
    produced them."""

    store = store_at(tmp_path)
    store.append([draft("a reply", prompt_version="e8a7d359ad50",
                        registers=["hostile", "summary"])])

    row = store.load()[0]
    assert row["prompt_version"] == "e8a7d359ad50"
    assert json.loads(row["registers"]) == ["hostile", "summary"]


# --------------------------------------------------------------------------
# Corruption
# --------------------------------------------------------------------------


def test_a_store_that_cannot_be_read_is_never_written_over(tmp_path):
    path = tmp_path / "history.sqlite3"
    path.write_bytes(b"this is not a database")
    store = SqliteHistoryStore(path)

    with pytest.raises(HistoryCorruptionError, match="not been written to"):
        store.load()

    with pytest.raises(HistoryCorruptionError):
        store.append([draft("a reply")])

    assert path.read_bytes() == b"this is not a database"


def test_the_same_corruption_is_quarantined_once_not_once_per_draft(tmp_path):
    """Otherwise one problem becomes a directory full of them."""

    path = tmp_path / "history.sqlite3"
    path.write_bytes(b"not a database")
    store = SqliteHistoryStore(path)

    first = store.quarantine()
    second = store.quarantine()

    assert first == second
    assert len(list(tmp_path.glob("*.corrupt*"))) == 1


def test_quarantine_preserves_the_unreadable_bytes(tmp_path):
    """Even a corrupt record is the only copy of whatever it held."""

    path = tmp_path / "history.sqlite3"
    path.write_bytes(b"not a database")
    store = SqliteHistoryStore(path)

    moved = store.quarantine()

    assert not path.exists()
    assert open(moved, "rb").read() == b"not a database"


# --------------------------------------------------------------------------
# Migration: copy, never move
# --------------------------------------------------------------------------


@pytest.fixture
def legacy_file(tmp_path):
    path = tmp_path / "posted_history.json"
    path.write_text(json.dumps([
        {"video_id": "gC-J7zwYMAM", "video_title": "A video",
         "target": "@alice", "draft": "the first reply", "words": 3,
         "drafted_at": "2026-07-01T00:00:00+00:00", "their_likes": 4},
        {"video_id": "gC-J7zwYMAM", "video_title": "A video",
         "target": "@bob", "draft": "the second reply", "words": 3,
         "drafted_at": "2026-07-02T00:00:00+00:00", "their_likes": 0},
    ], indent=2), encoding="utf-8")
    return path


def test_the_migration_never_touches_the_source(tmp_path, legacy_file):
    """The single most important assertion in this file.

    posted_history.json is not recoverable. The migration reads it and
    nothing else.
    """

    before = digest_of(legacy_file)

    report = migrate_json(legacy_file, store_at(tmp_path))

    assert digest_of(legacy_file) == before
    assert report["source_unchanged"] is True
    assert report["source_sha256"] == before
    assert legacy_file.exists()


def test_the_migration_is_lossless(tmp_path, legacy_file):
    store = store_at(tmp_path)
    original = json.loads(legacy_file.read_text(encoding="utf-8"))

    migrate_json(legacy_file, store)
    rows = store.load()

    assert len(rows) == len(original)
    for source, row in zip(original, rows):
        assert row["draft"] == source["draft"]
        assert row["video_id"] == source["video_id"]
        assert row["video_title"] == source["video_title"]
        assert row["target"] == source["target"]
        assert row["their_likes"] == source["their_likes"]
        assert row["drafted_at"] == source["drafted_at"]


def test_the_migration_is_repeatable(tmp_path, legacy_file):
    """Running it twice must not double the record."""

    store = store_at(tmp_path)

    first = migrate_json(legacy_file, store)
    second = migrate_json(legacy_file, store)

    assert first["records_added"] == 2
    assert second["records_added"] == 0
    assert second["records_already_present"] == 2
    assert len(store.load()) == 2


def test_migrated_rows_are_marked_as_migrated(tmp_path, legacy_file):
    """So a later question about provenance has an answer."""

    store = store_at(tmp_path)
    migrate_json(legacy_file, store)

    assert {row["source"] for row in store.load()} == {"migrated"}


def test_an_unreadable_source_is_refused_and_left_alone(tmp_path):
    path = tmp_path / "posted_history.json"
    path.write_text("{ not json", encoding="utf-8")
    before = digest_of(path)

    with pytest.raises(HistoryCorruptionError, match="not been modified"):
        migrate_json(path, store_at(tmp_path))

    assert digest_of(path) == before


def test_a_source_that_is_not_a_list_is_refused(tmp_path):
    path = tmp_path / "posted_history.json"
    path.write_text('{"drafts": []}', encoding="utf-8")

    with pytest.raises(HistoryCorruptionError, match="list of records"):
        migrate_json(path, store_at(tmp_path))


def test_a_missing_source_is_refused_clearly(tmp_path):
    with pytest.raises(HistoryCorruptionError, match="No history file"):
        migrate_json(tmp_path / "nothing.json", store_at(tmp_path))
