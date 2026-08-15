"""In-memory implementations of every port.

These are what make Phases 3-9 testable without a network, a display, or
quota. A fake is not a stub: each one enforces the same contract the real
adapter must, so a use case written against these behaves the same way
against the real thing. Where a fake is deliberately more permissive, the
contract test says so.

Every fake can be told to fail, because the interesting tests are the ones
where something goes wrong.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from llm_youtube_comment_generation.domain.errors import (
    ConfigurationError,
    HistoryCorruptionError,
)
from llm_youtube_comment_generation.domain.statuses import (
    RetrievalOutcome,
    RetrievalStatus,
    TranscriptAvailability,
    TranscriptResult,
)
from llm_youtube_comment_generation.ports.events import EventKind, ProgressEvent
from llm_youtube_comment_generation.ports.youtube import CommentPage


class FakeClock:
    """Time that only moves when a test moves it."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
        if self._now.tzinfo is None:
            raise ValueError("a clock must be timezone-aware")

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs) -> datetime:
        self._now += timedelta(**kwargs)
        return self._now


class FakeClipboard:
    """A clipboard that is just a variable."""

    def __init__(self, text: str = "") -> None:
        self._text = text
        self.writes: list[str] = []

    def read(self) -> str:
        return self._text

    def write(self, text: str) -> None:
        self._text = str(text)
        self.writes.append(self._text)


class FakeEventSink:
    """Records events so a test can assert a step happened."""

    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)

    def kinds(self) -> list[EventKind]:
        return [event.kind for event in self.events]

    def steps(self) -> list[str]:
        return [event.step for event in self.events if event.step]

    def messages(self) -> list[str]:
        return [event.message for event in self.events if event.message]


class BrokenEventSink:
    """A sink that always raises.

    Exists to prove the contract that a failing sink cannot take down the run
    reporting to it — a closed pipe or a destroyed window must not lose work.
    """

    def emit(self, event: ProgressEvent) -> None:
        raise RuntimeError("this sink is broken on purpose")


class FakeSettingsStore:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self._values = dict(values or {})
        self.unreadable = False

    def load(self) -> dict[str, Any]:
        if self.unreadable:
            return {}                      # never raises; a log line, not a refusal
        return dict(self._values)

    def save(self, values: dict[str, Any]) -> None:
        rejected = [k for k in values if "key" in k.lower()
                    or "secret" in k.lower() or "token" in k.lower()]
        if rejected:
            raise ValueError(
                f"settings must never hold a credential: {', '.join(rejected)}"
            )
        self._values = dict(values)


class FakeHistoryStore:
    """History in memory, with the same refusals as the real one."""

    def __init__(self, entries: Sequence[dict[str, Any]] | None = None) -> None:
        self._entries = [dict(e) for e in (entries or [])]
        self.corrupt = False
        self.quarantined: list[str] = []

    def load(self) -> list[dict[str, Any]]:
        if self.corrupt:
            raise HistoryCorruptionError(
                "the history file could not be read as a list of records"
            )
        return [dict(e) for e in self._entries]

    def append(self, entries: Sequence[dict[str, Any]]) -> int:
        # Identity mirrors SqliteHistoryStore._event_key: the exact event —
        # raw draft plus its identifying metadata — never normalized text.
        # This fake used to dedupe on normalise_for_match, which asserted a
        # fuzzy uniqueness the real v2 store deliberately removed (its
        # migration docstring says why: it merged genuinely distinct
        # events). A contract test in test_real_adapters_honor_the_contracts
        # holds the two implementations to the same answer.
        if self.corrupt:
            raise HistoryCorruptionError(
                "the history file could not be read as a list of records"
            )
        known = {self._event_key(e) for e in self._entries}
        added = 0
        for entry in entries:
            draft = str(entry.get("draft") or "").strip()
            if not draft:
                continue
            key = self._event_key(entry)
            if key in known:
                continue
            known.add(key)
            self._entries.append(dict(entry))
            added += 1
        return added

    @staticmethod
    def _event_key(entry: dict[str, Any]) -> tuple[str, ...]:
        supplied = str(
            entry.get("event_key") or entry.get("event_id") or ""
        ).strip()
        if supplied:
            return (supplied,)
        return tuple(
            str(entry.get(field) or "")
            for field in ("video_id", "workflow", "target",
                          "target_comment_id", "thread_id", "run_id",
                          "drafted_at", "source")
        ) + (str(entry.get("draft") or "").strip(),)

    def quarantine(self) -> str:
        # Once per corruption, never once per draft.
        if not self.quarantined:
            self.quarantined.append("posted_history.corrupt.json")
        self.corrupt = False
        return self.quarantined[0]


class FakeArtifactStore:
    """Staging and atomic commit, in memory."""

    def __init__(self) -> None:
        self._staged: dict[str, str] = {}
        self._committed: dict[str, str] = {}
        self.fail_on_commit = ""

    def stage(self, name: str, content: str) -> None:
        self._staged[name] = content

    def commit(self) -> tuple[str, ...]:
        if self.fail_on_commit and self.fail_on_commit in self._staged:
            # All or nothing: the previous set survives untouched.
            self._staged.clear()
            raise OSError(f"could not write {self.fail_on_commit}")
        previous = dict(self._committed)
        try:
            self._committed.update(self._staged)
        except Exception:
            self._committed = previous
            raise
        published = tuple(sorted(self._staged))
        self._staged.clear()
        return published

    def rollback(self) -> None:
        self._staged.clear()

    def read(self, name: str) -> str:
        if name not in self._committed:
            raise FileNotFoundError(name)
        return self._committed[name]

    def committed_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._committed))

    def staged_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._staged))


class FakeTranscriptPort:
    def __init__(
        self,
        entries: Sequence[dict[str, Any]] | None = None,
        availability: TranscriptAvailability = TranscriptAvailability.AVAILABLE,
    ) -> None:
        self.entries = tuple(entries or ({"text": "hello", "start": 0.0, "duration": 1.0},))
        self.availability = availability

    def fetch(
        self,
        video_id: str,
        languages: Sequence[str] = ("en",),
    ) -> TranscriptResult:
        if not self.availability.is_available:
            # Never raises: an absent transcript is an ordinary outcome.
            return TranscriptResult(
                availability=self.availability,
                detail=f"no transcript for {video_id}",
                source="fake",
            )
        return TranscriptResult(
            entries=self.entries,
            availability=TranscriptAvailability.AVAILABLE,
            language="English",
            language_code=languages[0] if languages else "en",
            is_generated=False,
            source="fake",
        )


class FakeYouTubePort:
    """Enough YouTube to build the whole application against.

    Holds comments and replies in memory and reports retrieval honestly: ask
    for fewer than exist and it says TOP_LEVEL_TRUNCATED with the counts,
    exactly as the real adapter must.
    """

    def __init__(
        self,
        videos: dict[str, dict[str, Any]] | None = None,
        comments: Sequence[dict[str, Any]] | None = None,
        replies: dict[str, list[dict[str, Any]]] | None = None,
        handles: dict[str, str] | None = None,
    ) -> None:
        self.videos = dict(videos or {})
        self.comments = [dict(c) for c in (comments or [])]
        # Stored under a private name: `self.replies = {...}` would shadow the
        # replies() port method on the instance and make it uncallable.
        self._replies = {k: [dict(r) for r in v] for k, v in (replies or {}).items()}
        self.handles = dict(handles or {})
        self._api_operations = 0
        self.raise_on_video: Exception | None = None

    @property
    def api_operations_used(self) -> int:
        return self._api_operations

    def video(self, video_id: str) -> dict[str, Any]:
        self._api_operations += 1
        if self.raise_on_video is not None:
            raise self.raise_on_video
        if video_id not in self.videos:
            raise ConfigurationError(f"No video was found for {video_id}")
        return dict(self.videos[video_id])

    def comment_threads(
        self,
        video_id: str,
        *,
        order: str = "relevance",
        maximum: int = 100,
    ) -> CommentPage:
        self._api_operations += 1
        pool = [dict(c, order_source=order) for c in self.comments]
        taken = pool[:maximum]
        complete = len(taken) == len(pool)
        return CommentPage(
            comments=taken,
            outcome=RetrievalOutcome(
                status=(RetrievalStatus.COMPLETE if complete
                        else RetrievalStatus.TOP_LEVEL_TRUNCATED),
                retrieved=len(taken),
                reported_total=len(pool),
                api_operations_used=1,
                notes=() if complete else (
                    f"stopped after {len(taken):,} of {len(pool):,} comments",
                ),
            ),
        )

    def replies(self, parent_comment_id: str, *, maximum: int = 100) -> CommentPage:
        self._api_operations += 1
        pool = self.replies_for(parent_comment_id)
        taken = pool[:maximum]
        complete = len(taken) == len(pool)
        return CommentPage(
            comments=taken,
            outcome=RetrievalOutcome(
                status=(RetrievalStatus.COMPLETE if complete
                        else RetrievalStatus.REPLY_THREAD_TRUNCATED),
                retrieved=len(taken),
                reported_total=len(pool),
                api_operations_used=1,
            ),
        )

    def replies_for(self, parent_comment_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._replies.get(parent_comment_id, [])]

    def channel_id_for_handle(self, handle: str) -> str:
        self._api_operations += 1
        wanted = handle if handle.startswith("@") else "@" + handle
        found = self.handles.get(wanted)
        if not found:
            raise ConfigurationError(f"No channel was found for handle: {wanted}")
        return found
