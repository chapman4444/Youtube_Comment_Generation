"""The record of what was drafted, so it can be scored later.

This is the only irreplaceable state the application owns. Everything else —
packets, reports, transcripts — can be regenerated from YouTube. The draft
history cannot: it is the measurement record the whole engagement question
rests on, and without it every prompt change is unfalsifiable.

Hence ``load`` may raise rather than returning an empty list. Silently
treating an unreadable history as empty and then appending to it is how the
record gets destroyed by the tool that exists to keep it.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class HistoryStore(Protocol):
    def load(self) -> list[dict[str, Any]]:
        """Every recorded draft.

        Raises HistoryCorruptionError when the file exists but cannot be
        read as a list of records. A missing file is not corruption and
        returns an empty list.
        """
        ...

    def append(self, entries: Sequence[dict[str, Any]]) -> int:
        """Add drafts that are not already recorded; return how many were new.

        Deduplication is by (video_id, normalised draft text), because the
        operator may run the same build twice and must not get two rows for
        one reply — that would double-count the likes it eventually earns.
        """
        ...

    def quarantine(self) -> str:
        """Move an unreadable history aside and return where it went.

        Called once per corruption, never once per draft: repeated
        quarantining of the same file turns one problem into a directory
        full of them.
        """
        ...
