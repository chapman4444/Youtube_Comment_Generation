"""Captions by way of yt-dlp, when the scrape endpoint refuses.

`youtube-transcript-api` scrapes YouTube's `timedtext` endpoint. yt-dlp asks
the InnerTube player API instead. They are different endpoint families and are
blocked separately, which stopped being a theory on the day this was written:
the operator's address was refused by the first for two days while the second
returned 821 caption events for the same video, in the same minute, from the
same connection.

Two things this buys beyond dodging a block. It sees caption tracks the
scraper does not — 157 languages on that video — and it is the most actively
maintained project in this space precisely because it keeps working around
YouTube's countermeasures, so it is the source more likely to still work next
month.

The library is optional, exactly like the other one: not installed is a state
that comes back as FETCH_FAILED with a detail saying so, never an ImportError
at start-up.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Sequence

from ..domain.statuses import TranscriptAvailability, TranscriptResult
from .external_errors import sanitize_external_error
from .youtube_api import build_session

LOGGER = logging.getLogger(__name__)

SOURCE = "yt-dlp"

#: json3 carries start and duration per event. The subtitle formats beside it
#: (srt, vtt) would have to be parsed back out of display text, and srv1 rounds
#: its timings.
CAPTION_FORMAT = "json3"


def library_available() -> bool:
    """Whether yt-dlp can be imported. `doctor` reports this as a fact."""

    try:
        import yt_dlp  # noqa: F401
    except Exception:                       # noqa: BLE001 - reporting only
        return False
    return True


class _Silent:
    """yt-dlp writes to stdout unless given somewhere else to write.

    A progress bar and a Python-version deprecation notice in the middle of
    this tool's own output is noise the operator cannot act on, and it is the
    same reason the semantic layer's progress trackers had to be redirected.
    """

    def debug(self, message: str) -> None:
        LOGGER.debug("yt-dlp: %s", message)

    info = debug

    def warning(self, message: str) -> None:
        LOGGER.debug("yt-dlp: %s", message)

    def error(self, message: str) -> None:
        LOGGER.warning("yt-dlp: %s", message)


def extract(video_id: str, proxy_url: str = "") -> dict[str, Any]:
    """Video metadata including every caption track. Downloads no media."""

    import yt_dlp

    options: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _Silent(),
        # Metadata only. Without this yt-dlp resolves every media format,
        # which is a pile of extra requests for bytes never read.
        "extract_flat": False,
        "youtube_include_dash_manifest": False,
    }
    if proxy_url:
        options["proxy"] = proxy_url

    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        ) or {}


def choose_track(
    info: dict[str, Any], languages: Sequence[str],
) -> tuple[str, str, bool] | None:
    """Pick (url, language_code, is_generated) for the best caption track.

    A published track beats an automatic one in the same language, and a
    requested language beats an unrequested one either way — the same ranking
    the scraping adapter uses, for the same reason: the words matter more than
    who typed them, but not more than being the right words.
    """

    manual = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    wanted = [code.lower() for code in languages] or ["en"]
    bases = [code.split("-")[0] for code in wanted]

    def rank(code: str, generated: bool) -> tuple[int, int]:
        lowered = code.lower()
        if lowered in wanted:
            language_rank = 0
        elif lowered.split("-")[0] in bases:
            language_rank = 1
        else:
            language_rank = 2
        return (language_rank, 1 if generated else 0)

    candidates: list[tuple[tuple[int, int], str, str, bool]] = []
    for tracks, generated in ((manual, False), (automatic, True)):
        for code, formats in tracks.items():
            for entry in formats or ():
                if entry.get("ext") == CAPTION_FORMAT and entry.get("url"):
                    candidates.append(
                        (rank(code, generated), entry["url"], code, generated)
                    )
                    break

    if not candidates:
        return None
    _, url, code, generated = min(candidates, key=lambda item: item[0])
    return url, code, generated


def parse_json3(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten json3 events into this project's entry records.

    An event's text arrives split across segments, and blank events are used
    as spacing rather than as speech — an empty line counted as an entry would
    show up in the packet as a timestamp with nothing beside it.
    """

    entries: list[dict[str, Any]] = []
    for event in payload.get("events") or ():
        segments = event.get("segs") or ()
        text = "".join(str(seg.get("utf8", "")) for seg in segments)
        text = " ".join(text.split())
        if not text:
            continue
        start = float(event.get("tStartMs", 0)) / 1000.0
        duration = float(event.get("dDurationMs", 0)) / 1000.0
        entries.append({
            "text": text,
            "start": start,
            "duration": duration,
            "end": start + duration,
        })
    return entries


class YtDlpTranscriptAdapter:
    """Implements TranscriptPort against yt-dlp's caption tracks."""

    def __init__(
        self,
        languages: Sequence[str] = ("en",),
        proxy_url: str = "",
        extractor: Callable[..., dict[str, Any]] | None = None,
        reader: Callable[[str], str] | None = None,
    ) -> None:
        self._languages = tuple(languages)
        self._proxy_url = proxy_url or ""
        self._extract = extractor or extract
        self._read = reader or self._read_url
        self._fetched: dict[tuple[str, tuple[str, ...]], TranscriptResult] = {}

    def _read_url(self, url: str) -> str:
        # Through this project's session, so the caption request carries the
        # same User-Agent, retry policy and proxy as everything else it sends.
        session = build_session(self._proxy_url)
        response = session.get(url, timeout=(10, 30))
        response.raise_for_status()
        return response.text

    def fetch(
        self,
        video_id: str,
        languages: Sequence[str] = (),
    ) -> TranscriptResult:
        wanted = tuple(languages) or self._languages

        cached = self._fetched.get((video_id, wanted))
        if cached is not None:
            return cached

        # Only when the real extractor is in use. Probing for the library on
        # every call made an injected extractor depend on the library being
        # installed, which is the opposite of what injecting one is for.
        if self._extract is extract and not library_available():
            return TranscriptResult(
                availability=TranscriptAvailability.FETCH_FAILED,
                source=SOURCE,
                detail=("yt-dlp is not installed, so the player API could not "
                        "be asked for captions"),
            )

        try:
            info = self._extract(video_id, self._proxy_url)
        except Exception as exc:            # noqa: BLE001 - library raises broadly
            return TranscriptResult(
                availability=self._classify(exc),
                source=SOURCE,
                detail=sanitize_external_error(exc, self._proxy_url),
            )

        chosen = choose_track(info, wanted)
        if chosen is None:
            return TranscriptResult(
                availability=TranscriptAvailability.NOT_PUBLISHED,
                source=SOURCE,
                detail="no caption track was offered for this video",
            )

        url, code, generated = chosen
        try:
            entries = parse_json3(json.loads(self._read(url)))
        except Exception as exc:            # noqa: BLE001
            return TranscriptResult(
                availability=TranscriptAvailability.FETCH_FAILED,
                source=SOURCE,
                detail=(f"the caption track was listed but could not be read "
                        f"({type(exc).__name__})"),
            )

        if not entries:
            return TranscriptResult(
                availability=TranscriptAvailability.EMPTY,
                source=SOURCE,
                detail="the caption track contained no text",
            )

        result = TranscriptResult(
            entries=tuple(entries),
            availability=TranscriptAvailability.AVAILABLE,
            language=code,
            language_code=code,
            is_generated=generated,
            source=SOURCE,
        )
        self._fetched[(video_id, wanted)] = result
        return result

    @staticmethod
    def _classify(exc: Exception) -> TranscriptAvailability:
        """Map yt-dlp's failures onto explicit states.

        Matched on the message rather than the exception type: yt-dlp raises
        DownloadError for almost everything and puts the actual reason in the
        text.
        """

        message = str(exc).lower()
        if "private" in message:
            return TranscriptAvailability.NOT_PUBLIC
        if "age" in message and "restrict" in message:
            return TranscriptAvailability.NOT_PUBLIC
        # "unavailable" is ambiguous and must stay retryable: a transient
        # "503 Service Unavailable" or a bot-check "Video unavailable" was
        # being presented as "this video is private", which is terminal and
        # disabled the saved-transcript and Whisper fallbacks the message
        # least applies to (harsh-critic review, finding 15).
        return TranscriptAvailability.FETCH_FAILED
