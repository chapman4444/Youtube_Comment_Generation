"""Try each transcript source in turn, and say which one answered.

There are now three ways to get the words: the scrape endpoint, yt-dlp's
player API, and this machine's own saved copy from an earlier run. They fail
independently — an address blocked from the first was serving the second in
the same minute — so the useful thing is not picking one but ordering them.

Caption discovery and local transcription answer different questions.

**A caption source that says the video has no captions ends caption
discovery.** When, and only when, the operator explicitly supplied a local
transcriber, that result becomes the reason to run it. A private video remains
terminal and never triggers an audio download.

**The result always says where it came from.** `TranscriptResult.source`
reaches the run record, so a packet built from yt-dlp and a packet built from
a transcript saved an hour ago are distinguishable after the fact. Reusing is
legitimate; reusing quietly is the failure this project keeps having to fix.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Sequence

from ..domain.statuses import TranscriptAvailability, TranscriptResult

LOGGER = logging.getLogger(__name__)

TERMINAL_CAPTION_RESULT = frozenset({
    TranscriptAvailability.AVAILABLE,
    TranscriptAvailability.NOT_PUBLIC,
})

UNAVAILABLE_STRENGTH = {
    TranscriptAvailability.FETCH_FAILED: 1,
    TranscriptAvailability.EMPTY: 2,
    TranscriptAvailability.LANGUAGE_UNAVAILABLE: 3,
    TranscriptAvailability.NOT_PUBLISHED: 4,
}


class ChainedTranscripts:
    """Implements TranscriptPort over several sources, in preference order."""

    def __init__(self, *sources, local_fallback=None) -> None:
        if not sources:
            raise ValueError("a transcript chain needs at least one source")
        self._caption_sources = sources
        self._local_fallback = local_fallback
        # Kept as the complete ordered inventory for diagnostics and existing
        # construction tests.
        self._sources = sources + ((local_fallback,) if local_fallback else ())

    def fetch(
        self,
        video_id: str,
        languages: Sequence[str] = (),
    ) -> TranscriptResult:
        results: list[TranscriptResult] = []
        for source in self._caption_sources:
            result = source.fetch(video_id, languages)
            results.append(result)
            if result.availability in TERMINAL_CAPTION_RESULT:
                if len(results) > 1 and \
                        result.availability is TranscriptAvailability.AVAILABLE:
                    # Which sources were tried first, and why they did not
                    # answer. Without this a packet says "yt-dlp" and gives no
                    # hint that the usual source is refusing this machine.
                    LOGGER.info(
                        "%s answered after %d source(s) could not",
                        result.source, len(results) - 1,
                    )
                return replace(result, attempts=_attempt_records(results))

        # Local transcription is a distinct, explicitly enabled fallback. It
        # may handle no-caption, empty-caption, or unreachable-caption
        # outcomes, but it must never run for a private video.
        if self._local_fallback is not None:
            local = self._local_fallback.fetch(video_id, languages)
            return replace(local, attempts=_attempt_records(results))

        if results:
            strongest = max(
                enumerate(results),
                key=lambda item: (
                    UNAVAILABLE_STRENGTH.get(item[1].availability, 0),
                    -item[0],
                ),
            )[1]
            return replace(
                strongest,
                attempts=_attempt_records(results),
                detail=_with_attempts(strongest.detail, results),
            )
        return TranscriptResult(
            availability=TranscriptAvailability.FETCH_FAILED,
            detail="no transcript source was configured",
        )


def _attempt_records(results: list[TranscriptResult]) -> tuple[dict[str, str], ...]:
    return tuple({
        "source": str(result.source or ""),
        "availability": result.availability.value,
        "detail": str(result.detail or ""),
    } for result in results)


def _with_attempts(detail: str, results: list[TranscriptResult]) -> str:
    summary = "; ".join(
        f"{result.source or 'unknown'}={result.availability.value}"
        for result in results
    )
    prefix = str(detail or "").strip().rstrip(".")
    return f"{prefix + '. ' if prefix else ''}Caption attempts: {summary}."
