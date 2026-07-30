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


def test_fuzzy_similarity_is_not_persistence_identity(tmp_path):
    store = store_at(tmp_path)
    store.append([draft("The Same Reply, Text!")])

    assert store.append([draft("the same reply text")]) == 1
    assert len(store.load()) == 2


def test_identical_text_to_two_targets_is_two_posting_events(tmp_path):
    store = store_at(tmp_path)

    assert store.append([
        draft("same words", target="@alice", target_comment_id="a"),
        draft("same words", target="@bob", target_comment_id="b"),
    ]) == 2


def test_an_exact_event_retry_is_idempotent(tmp_path):
    store = store_at(tmp_path)
    entry = draft(
        "same words",
        target="@alice",
        target_comment_id="a",
        run_id="run-1",
        workflow="reply",
    )

    assert store.append([entry]) == 1
    assert store.append([entry]) == 0


def test_a_non_latin_draft_is_preserved(tmp_path):
    store = store_at(tmp_path)

    assert store.append([draft("これは投稿された返信です", event_id="jp-1")]) == 1
    assert store.load()[0]["draft"] == "これは投稿された返信です"


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


@pytest.mark.parametrize("malformed", [
    "not an object",
    {"video_id": "v1"},
    {"video_id": "v1", "draft": ""},
    {"video_id": "v1", "draft": "   "},
    {"video_id": "v1", "draft": 123},
])
def test_malformed_migration_records_abort_without_partial_import(
    tmp_path,
    malformed,
):
    source = tmp_path / "posted_history.json"
    source.write_text(
        json.dumps([draft("valid first"), malformed, draft("valid last")]),
        encoding="utf-8",
    )
    before = digest_of(source)
    store = store_at(tmp_path)

    with pytest.raises(
        HistoryCorruptionError,
        match=r"malformed record\(s\).*index\(es\) 1",
    ):
        migrate_json(source, store)

    assert store.load() == []
    assert digest_of(source) == before


def test_v1_database_is_backed_up_and_migrated_without_losing_rows(tmp_path):
    path = tmp_path / "history.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            video_title TEXT NOT NULL DEFAULT '',
            target TEXT NOT NULL DEFAULT '',
            draft TEXT NOT NULL,
            match_key TEXT NOT NULL,
            words INTEGER NOT NULL DEFAULT 0,
            their_likes INTEGER NOT NULL DEFAULT 0,
            drafted_at TEXT NOT NULL DEFAULT '',
            prompt_version TEXT NOT NULL DEFAULT '',
            registers TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'native',
            UNIQUE (video_id, match_key)
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta VALUES ('schema_version', '1');
        INSERT INTO drafts
            (video_id, target, draft, match_key, words, source)
        VALUES ('v1', '@alice', 'legacy reply', 'legacy reply', 2, 'migrated');
    """)
    connection.commit()
    connection.close()
    before = digest_of(path)

    rows = SqliteHistoryStore(path).load()

    assert len(rows) == 1
    assert rows[0]["draft"] == "legacy reply"
    backups = list(tmp_path.glob("history.sqlite3.v1.bak*"))
    assert len(backups) == 1
    assert digest_of(backups[0]) == before
    with sqlite3.connect(path) as migrated:
        version = migrated.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0]
    assert version == "2"


def test_a_future_schema_is_refused_without_writing(tmp_path):
    path = tmp_path / "history.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta VALUES ('schema_version', '999');
    """)
    connection.commit()
    connection.close()
    before = digest_of(path)

    with pytest.raises(HistoryCorruptionError, match="newer"):
        SqliteHistoryStore(path).load()

    assert digest_of(path) == before


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
