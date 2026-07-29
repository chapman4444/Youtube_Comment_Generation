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
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ..domain.errors import HistoryCorruptionError
from ..domain.history import normalise_for_match

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id       TEXT NOT NULL,
    video_title    TEXT NOT NULL DEFAULT '',
    target         TEXT NOT NULL DEFAULT '',
    draft          TEXT NOT NULL,
    match_key      TEXT NOT NULL,
    words          INTEGER NOT NULL DEFAULT 0,
    their_likes    INTEGER NOT NULL DEFAULT 0,
    drafted_at     TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    registers      TEXT NOT NULL DEFAULT '',
    source         TEXT NOT NULL DEFAULT 'native',
    UNIQUE (video_id, match_key)
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
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT video_id, video_title, target, draft, words, "
                "their_likes, drafted_at, prompt_version, registers, source "
                "FROM drafts ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def append(self, entries: Sequence[dict[str, Any]]) -> int:
        """Insert drafts that are not already recorded; return how many were new.

        Deduplication is on the normalised draft text within a video, because
        the operator may build the same packet twice and must not get two rows
        for one reply.
        """

        added = 0
        with self._connect() as connection:
            for entry in entries:
                draft = str(entry.get("draft") or "").strip()
                if not draft:
                    continue
                video_id = str(entry.get("video_id") or "")
                key = normalise_for_match(draft)
                if not key:
                    continue
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO drafts "
                    "(video_id, video_title, target, draft, match_key, words, "
                    " their_likes, drafted_at, prompt_version, registers, source) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        video_id,
                        str(entry.get("video_title") or ""),
                        str(entry.get("target") or ""),
                        draft,
                        key,
                        int(entry.get("words") or len(draft.split())),
                        int(entry.get("their_likes") or 0),
                        str(entry.get("drafted_at")
                            or datetime.now(timezone.utc).isoformat()),
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
            connection = sqlite3.connect(self._path)
            connection.row_factory = sqlite3.Row
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            return connection
        except sqlite3.DatabaseError as exc:
            raise HistoryCorruptionError(
                f"the history store at {self._path} could not be opened "
                f"({exc}). It has not been written to. Run "
                "`ytcomment history quarantine` to set it aside."
            ) from exc


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

    added = store.append([
        dict(entry, source="migrated")
        for entry in entries if isinstance(entry, dict)
    ])

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
