"""Engagement history in SQLite.

This is the only irreplaceable state this project owns. Everything else —
packets, reports, transcripts — can be rebuilt from YouTube. The draft history
cannot: it is the measurement record the whole engagement question rests on,
and without it every prompt change is unfalsifiable.

So the rules here are stricter than anywhere else:

- **Migration copies. It never moves, edits, or deletes the source.** The
  operator's ``posted_history.json`` is left byte-identical, and a test
  asserts its checksum before and after.
- **A store that cannot be read is never written over.** It is quarantined
  once — not once per draft — and the caller is told.
- **Recording a draft twice adds one row.** The same run repeated must not
  double-count the likes a reply eventually earns, because those numbers are
  the only measurement this project has.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import contextlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ..domain.errors import HistoryCorruptionError
from ..domain.history import normalise_for_match

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key      TEXT NOT NULL UNIQUE,
    video_id       TEXT NOT NULL,
    video_title    TEXT NOT NULL DEFAULT '',
    target         TEXT NOT NULL DEFAULT '',
    target_comment_id TEXT NOT NULL DEFAULT '',
    thread_id      TEXT NOT NULL DEFAULT '',
    workflow       TEXT NOT NULL DEFAULT '',
    operator_channel_id TEXT NOT NULL DEFAULT '',
    run_id         TEXT NOT NULL DEFAULT '',
    draft          TEXT NOT NULL,
    match_key      TEXT NOT NULL,
    words          INTEGER NOT NULL DEFAULT 0,
    their_likes    INTEGER NOT NULL DEFAULT 0,
    drafted_at     TEXT NOT NULL DEFAULT '',
    posted_at      TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    registers      TEXT NOT NULL DEFAULT '',
    source         TEXT NOT NULL DEFAULT 'native'
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SqliteHistoryStore:
    """Implements HistoryStore over a SQLite file."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._quarantined: list[Path] = []

    @property
    def path(self) -> Path:
        return self._path

    # -- port surface ----------------------------------------------------

    def load(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []                       # missing is not corruption
        with contextlib.closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT event_key, video_id, video_title, target, "
                "target_comment_id, thread_id, workflow, "
                "operator_channel_id, run_id, draft, match_key, words, "
                "their_likes, drafted_at, posted_at, prompt_version, "
                "registers, source "
                "FROM drafts ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def append(self, entries: Sequence[dict[str, Any]]) -> int:
        """Insert drafts that are not already recorded; return how many were new.

        Identity is ``event_id`` when the caller supplies one. Otherwise it is
        a hash of video, workflow, target, target comment, thread, run, draft,
        ``drafted_at`` and source.

        Note which timestamp that is. ``drafted_at`` participates; ``posted_at``
        does not. This docstring used to say "timestamp" without saying which,
        which read as though two posts of the same text were distinguished by
        when they were posted. They are not. A caller that supplies neither an
        ``event_id`` nor a distinguishing ``run_id``/``drafted_at`` will have a
        second identical post treated as a duplicate and dropped, so callers
        that cannot guarantee one must establish identity themselves rather
        than rely on this method to separate the events.

        ``match_key`` is normalized text retained only for later scoreboard
        matching; it is not persistence identity.
        """

        added = 0
        with contextlib.closing(self._connect()) as connection, connection:
            for entry in entries:
                draft = str(entry.get("draft") or "").strip()
                if not draft:
                    continue
                video_id = str(entry.get("video_id") or "")
                key = normalise_for_match(draft)
                event_key = _event_key(entry, draft)
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO drafts "
                    "(event_key, video_id, video_title, target, "
                    " target_comment_id, thread_id, workflow, "
                    " operator_channel_id, run_id, draft, match_key, words, "
                    " their_likes, drafted_at, posted_at, prompt_version, "
                    " registers, source) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        event_key,
                        video_id,
                        str(entry.get("video_title") or ""),
                        str(entry.get("target") or ""),
                        str(entry.get("target_comment_id") or ""),
                        str(entry.get("thread_id") or ""),
                        str(entry.get("workflow") or ""),
                        str(entry.get("operator_channel_id") or ""),
                        str(entry.get("run_id") or ""),
                        draft,
                        key,
                        int(entry.get("words") or len(draft.split())),
                        int(entry.get("their_likes") or 0),
                        str(entry.get("drafted_at")
                            or datetime.now(timezone.utc).isoformat()),
                        str(entry.get("posted_at") or ""),
                        str(entry.get("prompt_version") or ""),
                        json.dumps(list(entry.get("registers") or [])),
                        str(entry.get("source") or "native"),
                    ),
                )
                added += cursor.rowcount or 0
        return added

    def quarantine(self) -> str:
        """Move an unreadable store aside, once per corruption.

        Repeated quarantining of the same file turns one problem into a
        directory full of them, so a store that has already been set aside
        during this session is not set aside again.
        """

        if self._quarantined:
            return str(self._quarantined[0])
        if not self._path.exists():
            return ""
        target = self._path.with_suffix(
            self._path.suffix + ".corrupt"
        )
        counter = 1
        while target.exists():
            counter += 1
            target = self._path.with_suffix(f"{self._path.suffix}.corrupt{counter}")
        shutil.move(str(self._path), str(target))
        self._quarantined.append(target)
        return str(target)

    # -- internals -------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            existed = self._path.exists()
            connection = sqlite3.connect(self._path)
            connection.row_factory = sqlite3.Row
            if not existed:
                connection.executescript(SCHEMA)
                connection.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
                connection.commit()
                return connection

            version = _schema_version(connection)
            if version > SCHEMA_VERSION:
                connection.close()
                raise HistoryCorruptionError(
                    f"the history store at {self._path} uses schema version "
                    f"{version}, newer than this application's version "
                    f"{SCHEMA_VERSION}. It has not been written to."
                )
            if version < 1:
                connection.close()
                raise HistoryCorruptionError(
                    f"the history store at {self._path} has no supported "
                    "schema version. It has not been written to."
                )
            if version == 1:
                self._backup_v1()
                _migrate_v1(connection)
            connection.executescript(SCHEMA)
            return connection
        except sqlite3.DatabaseError as exc:
            raise HistoryCorruptionError(
                f"the history store at {self._path} could not be opened "
                f"({exc}). It has not been written to. Run "
                "`ytcomment history quarantine` to set it aside."
            ) from exc

    def _backup_v1(self) -> Path:
        """Copy the final v1 bytes before applying the schema migration.

        Once. A retried migration used to mint .v1.bak2, .v1.bak3, … on
        every attempt, copying the whole database each time; the first
        backup is the pre-migration bytes and is the only one worth having.
        """

        target = self._path.with_suffix(self._path.suffix + ".v1.bak")
        if not target.exists():
            shutil.copy2(self._path, target)
        return target


def _event_key(entry: dict[str, Any], draft: str) -> str:
    """Stable identity for one confirmed posting event."""

    supplied = str(entry.get("event_key") or entry.get("event_id") or "").strip()
    if supplied:
        return supplied
    identity = {
        "video_id": str(entry.get("video_id") or ""),
        "workflow": str(entry.get("workflow") or ""),
        "target": str(entry.get("target") or ""),
        "target_comment_id": str(entry.get("target_comment_id") or ""),
        "thread_id": str(entry.get("thread_id") or ""),
        "run_id": str(entry.get("run_id") or ""),
        "draft": draft,
        "drafted_at": str(entry.get("drafted_at") or ""),
        "source": str(entry.get("source") or "native"),
    }
    encoded = json.dumps(
        identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _schema_version(connection: sqlite3.Connection) -> int:
    meta = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if meta is None:
        return 0
    row = connection.execute(
        "SELECT value FROM meta WHERE key='schema_version'"
    ).fetchone()
    try:
        return int(row[0]) if row else 0
    except (TypeError, ValueError):
        return 0


def _migrate_v1(connection: sqlite3.Connection) -> None:
    """Transactionally rebuild v1 without fuzzy-text uniqueness."""

    rows = connection.execute(
        "SELECT id, video_id, video_title, target, draft, match_key, words, "
        "their_likes, drafted_at, prompt_version, registers, source "
        "FROM drafts ORDER BY id"
    ).fetchall()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""
            CREATE TABLE drafts_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                video_id TEXT NOT NULL,
                video_title TEXT NOT NULL DEFAULT '',
                target TEXT NOT NULL DEFAULT '',
                target_comment_id TEXT NOT NULL DEFAULT '',
                thread_id TEXT NOT NULL DEFAULT '',
                workflow TEXT NOT NULL DEFAULT '',
                operator_channel_id TEXT NOT NULL DEFAULT '',
                run_id TEXT NOT NULL DEFAULT '',
                draft TEXT NOT NULL,
                match_key TEXT NOT NULL,
                words INTEGER NOT NULL DEFAULT 0,
                their_likes INTEGER NOT NULL DEFAULT 0,
                drafted_at TEXT NOT NULL DEFAULT '',
                posted_at TEXT NOT NULL DEFAULT '',
                prompt_version TEXT NOT NULL DEFAULT '',
                registers TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'native'
            )
        """)
        for row in rows:
            entry = dict(row)
            connection.execute(
                "INSERT OR IGNORE INTO drafts_v2 "
                "(id, event_key, video_id, video_title, target, draft, "
                "match_key, words, their_likes, drafted_at, prompt_version, "
                "registers, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    entry["id"],
                    _event_key(entry, str(entry["draft"])),
                    entry["video_id"],
                    entry["video_title"],
                    entry["target"],
                    entry["draft"],
                    entry["match_key"],
                    entry["words"],
                    entry["their_likes"],
                    entry["drafted_at"],
                    entry["prompt_version"],
                    entry["registers"],
                    entry["source"],
                ),
            )
        connection.execute("DROP TABLE drafts")
        connection.execute("ALTER TABLE drafts_v2 RENAME TO drafts")
        connection.execute(
            "UPDATE meta SET value=? WHERE key='schema_version'",
            (str(SCHEMA_VERSION),),
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def migrate_json(
    source: Path | str,
    store: SqliteHistoryStore,
) -> dict[str, Any]:
    """Copy a legacy posted_history.json into the store.

    Copy, never move. The source is opened read-only and its checksum is
    compared before and after: this function is the one place in the project
    that touches the operator's real measurement record, and the guarantee it
    makes is that it does not touch it at all.

    Repeatable. Running it twice adds nothing the second time, because the
    store deduplicates on the same key the recorder uses.
    """

    source = Path(source)
    if not source.is_file():
        raise HistoryCorruptionError(f"No history file at {source}")

    before = digest_of(source)
    raw = source.read_bytes()
    try:
        entries = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HistoryCorruptionError(
            f"{source} is not readable as JSON ({exc}). It has not been "
            "modified."
        ) from exc

    if not isinstance(entries, list):
        raise HistoryCorruptionError(
            f"{source} does not contain a list of records. It has not been "
            "modified."
        )

    malformed = [
        index
        for index, entry in enumerate(entries)
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("draft"), str)
            or not entry["draft"].strip()
        )
    ]
    if malformed:
        sample = ", ".join(str(index) for index in malformed[:10])
        more = (
            f" and {len(malformed) - 10} more"
            if len(malformed) > 10
            else ""
        )
        raise HistoryCorruptionError(
            f"{source} contains {len(malformed)} malformed record(s) at "
            f"zero-based index(es) {sample}{more}. Every record must be an "
            "object with a non-empty text draft. Nothing was imported and "
            "the source has not been modified."
        )

    validated = [
        dict(entry, source="migrated")
        for entry in entries
    ]
    added = store.append(validated)

    after = digest_of(source)
    if before != after:
        raise HistoryCorruptionError(
            f"{source} changed during migration. This should be impossible; "
            "the migration only reads."
        )

    return {
        "source": str(source),
        "source_sha256": before,
        "source_unchanged": True,
        "records_in_source": len(entries),
        "records_added": added,
        "records_already_present": len(entries) - added,
    }
