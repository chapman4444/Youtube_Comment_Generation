"""The real transcript adapter.

The caption library is an optional dependency and a third-party scraper. Both
facts are handled here rather than leaking upward: if it is not installed,
that is a state (``NOT_PUBLISHED`` cannot be distinguished, so it reports
``FETCH_FAILED`` with a detail saying so) and never an ImportError at
start-up.

Every failure becomes a ``TranscriptAvailability`` value. Nothing above this
line has to match on English to find out why there is no transcript.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from ..domain.statuses import TranscriptAvailability, TranscriptResult
from .youtube_api import build_session
from .external_errors import sanitize_external_error

LOGGER = logging.getLogger(__name__)

SOURCE = "youtube-transcript-api"


def library_available() -> bool:
    """Whether the caption library can be imported.

    Used by `doctor`, which must report a missing transcript adapter as a
    fact without failing.
    """

    try:
        import youtube_transcript_api  # noqa: F401
    except Exception:                       # noqa: BLE001 - reporting only
        return False
    return True


def normalise_entries(fetched: Any) -> list[dict[str, Any]]:
    """Flatten the library's objects into plain records with an end time."""

    raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            item = {
                "text": getattr(item, "text", ""),
                "start": getattr(item, "start", 0.0),
                "duration": getattr(item, "duration", 0.0),
            }
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start = float(item.get("start") or 0.0)
        duration = float(item.get("duration") or 0.0)
        entries.append({
            "text": text,
            "start": start,
            "duration": duration,
            "end": start + duration,
        })
    return entries


def choose(transcripts: Sequence[Any], languages: Sequence[str]) -> Any:
    """Prefer a human transcript in a requested language, then anything.

    A generated transcript in the right language beats a human one in the
    wrong language: the words matter more than who typed them.
    """

    wanted = [code.lower() for code in languages]
    ordered = list(transcripts)

    def rank(transcript: Any) -> tuple[int, int]:
        code = str(getattr(transcript, "language_code", "")).lower()
        base = code.split("-")[0]
        generated = bool(getattr(transcript, "is_generated", False))
        if code in wanted:
            language_rank = 0
        elif base in [w.split("-")[0] for w in wanted]:
            language_rank = 1
        else:
            language_rank = 2
        return (language_rank, 1 if generated else 0)

    return min(ordered, key=rank) if ordered else None


def transcript_client(proxy_url: str = "") -> Any:
    """The caption API, talking through this project's own HTTP session.

    Taken from the old application, which passed its session in and which this
    rebuild had quietly dropped. The difference is not cosmetic. A bare
    ``YouTubeTranscriptApi()`` builds its own session, so every caption request
    went out as ``python-requests/2.32.3`` with no retry policy and no proxy —
    while the Data API calls beside them carried a real User-Agent, backoff on
    429, and whatever ``proxy_url`` was set to.

    One session means one place where the User-Agent, the retry policy and the
    proxy are decided, and it is the same place the Data API uses. It is also
    how ``proxy_url`` finally reaches the endpoint that actually gets banned:
    the setting existed for the whole project and only ever reached the
    authenticated, quota-metered API that never is.

    Falls back to the library's own session if this version will not accept
    one, because a missing improvement must not become a crash on the path
    that is already failing.
    """

    from youtube_transcript_api import YouTubeTranscriptApi

    try:
        return YouTubeTranscriptApi(http_client=build_session(proxy_url))
    except TypeError:                       # pragma: no cover - older library
        LOGGER.warning(
            "this youtube-transcript-api does not accept a session; the "
            "User-Agent, retry policy and proxy_url will not apply to caption "
            "requests"
        )
        return YouTubeTranscriptApi()


#: Consecutive live failures after which this process stops trying. An IP ban
#: does not clear while you keep knocking, and the fourth refusal carries no
#: information the third did not.
GIVE_UP_AFTER = 3


class TranscriptAdapter:
    """Implements TranscriptPort against youtube-transcript-api.

    Two guards, both added after this tool got the operator's own address
    blocked for two days. A sweep built nine packets from one video and
    fetched that video's transcript for every one of them, plus retries: about
    twenty requests for one caption track that had not changed.

    **The same transcript is fetched once per process.** A published video's
    captions do not change between one packet and the next, so every request
    after the first was pure cost and the whole reason the endpoint objected.

    **Repeated failure stops the process trying.** Once the address is
    refused, continuing to ask cannot succeed and can only deepen it.

    Neither replaces `SavedTranscriptFallback`, which reuses a transcript
    across processes; these stop the requests being made at all.
    """

    def __init__(
        self,
        languages: Sequence[str] = ("en",),
        proxy_url: str = "",
        give_up_after: int = GIVE_UP_AFTER,
    ) -> None:
        self._languages = tuple(languages)
        self._proxy_url = proxy_url or ""
        self._give_up_after = max(1, give_up_after)
        self._fetched: dict[tuple[str, tuple[str, ...]], TranscriptResult] = {}
        self._consecutive_failures = 0
        self._last_failure: TranscriptResult | None = None

    def fetch(
        self,
        video_id: str,
        languages: Sequence[str] = (),
    ) -> TranscriptResult:
        wanted = tuple(languages) or self._languages

        cached = self._fetched.get((video_id, wanted))
        if cached is not None:
            LOGGER.debug("reusing the transcript already fetched for %s",
                         video_id)
            return cached

        if self._consecutive_failures >= self._give_up_after:
            return self._exhausted()

        result = self._fetch_live(video_id, wanted)

        if result.availability is TranscriptAvailability.AVAILABLE:
            self._fetched[(video_id, wanted)] = result
            self._consecutive_failures = 0
        elif result.availability is TranscriptAvailability.FETCH_FAILED:
            # Only FETCH_FAILED counts. "This video has no captions" is an
            # answer about the video, not a sign the endpoint is refusing us,
            # and counting it would stop a run over a video that simply has
            # no transcript.
            self._consecutive_failures += 1
            self._last_failure = result
        return result

    def _exhausted(self) -> TranscriptResult:
        """Refuse without asking, and say why."""

        previous = (self._last_failure.detail or "").strip().splitlines()
        reason = previous[0] if previous else "the endpoint refused"
        return TranscriptResult(
            availability=TranscriptAvailability.FETCH_FAILED,
            source=SOURCE,
            detail=(
                f"not attempted: the caption endpoint refused "
                f"{self._consecutive_failures} times in this run "
                f"({reason}). Asking again cannot succeed and can deepen an "
                "address block, so this run stopped trying. Set proxy_url, "
                "or use `ytcomment comment rebuild` to re-render a finished "
                "run without fetching anything."
            ),
        )

    def _fetch_live(
        self, video_id: str, wanted: tuple[str, ...],
    ) -> TranscriptResult:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except Exception as exc:            # noqa: BLE001 - absence is a state
            return TranscriptResult(
                availability=TranscriptAvailability.FETCH_FAILED,
                source=SOURCE,
                detail=(
                    "the transcript library is not installed, so no caption "
                    f"track could be looked up ({type(exc).__name__})"
                ),
            )

        try:
            listing = list(transcript_client(self._proxy_url).list(video_id))
        except Exception as exc:            # noqa: BLE001 - library raises broadly
            return TranscriptResult(
                availability=self._classify(exc),
                source=SOURCE,
                detail=sanitize_external_error(exc, self._proxy_url),
            )

        if not listing:
            return TranscriptResult(
                availability=TranscriptAvailability.NOT_PUBLISHED,
                source=SOURCE,
                detail="no caption tracks were published",
            )

        chosen = choose(listing, wanted)
        if chosen is None:
            return TranscriptResult(
                availability=TranscriptAvailability.LANGUAGE_UNAVAILABLE,
                source=SOURCE,
                detail="no caption track matched the requested languages",
            )

        try:
            entries = normalise_entries(chosen.fetch())
        except Exception as exc:            # noqa: BLE001
            return TranscriptResult(
                availability=TranscriptAvailability.FETCH_FAILED,
                source=SOURCE,
                detail=sanitize_external_error(exc, self._proxy_url),
            )

        if not entries:
            return TranscriptResult(
                availability=TranscriptAvailability.EMPTY,
                source=SOURCE,
                detail="the caption track contained no text",
            )

        return TranscriptResult(
            entries=tuple(entries),
            availability=TranscriptAvailability.AVAILABLE,
            language=str(getattr(chosen, "language", "") or ""),
            language_code=str(getattr(chosen, "language_code", "") or ""),
            is_generated=bool(getattr(chosen, "is_generated", False)),
            source=SOURCE,
        )

    @staticmethod
    def _classify(exc: Exception) -> TranscriptAvailability:
        """Map the library's exception names onto explicit states.

        Matched on the class name rather than by importing every exception
        type, because the library renames them between versions and an
        ImportError here would turn a missing transcript into a crash.
        """

        name = type(exc).__name__
        if "TranscriptsDisabled" in name or "NoTranscriptFound" in name:
            return TranscriptAvailability.NOT_PUBLISHED
        if "VideoUnavailable" in name or "VideoUnplayable" in name:
            return TranscriptAvailability.NOT_PUBLIC
        if "NotTranslatable" in name or "TranslationLanguage" in name:
            return TranscriptAvailability.LANGUAGE_UNAVAILABLE
        return TranscriptAvailability.FETCH_FAILED
