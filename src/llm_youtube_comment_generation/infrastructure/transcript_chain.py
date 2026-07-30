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
from typing import Sequence

from ..domain.statuses import TranscriptAvailability, TranscriptResult

LOGGER = logging.getLogger(__name__)

#: Availabilities that are an answer about the video rather than a failure to
#: reach it. A second source will say the same thing.
CONCLUSIVE_CAPTION_RESULT = frozenset({
    TranscriptAvailability.AVAILABLE,
    TranscriptAvailability.NOT_PUBLISHED,
    TranscriptAvailability.NOT_PUBLIC,
    TranscriptAvailability.EMPTY,
})


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
        attempts: list[TranscriptResult] = []

        terminal: TranscriptResult | None = None
        for source in self._caption_sources:
            result = source.fetch(video_id, languages)
            if result.availability in CONCLUSIVE_CAPTION_RESULT:
                if attempts and result.availability is TranscriptAvailability.AVAILABLE:
                    # Which sources were tried first, and why they did not
                    # answer. Without this a packet says "yt-dlp" and gives no
                    # hint that the usual source is refusing this machine.
                    LOGGER.info(
                        "%s answered after %d source(s) could not",
                        result.source, len(attempts),
                    )
                terminal = result
                break
            attempts.append(result)

        if terminal is not None and terminal.availability in (
            TranscriptAvailability.AVAILABLE,
            TranscriptAvailability.NOT_PUBLIC,
        ):
            return terminal

        # Local transcription is a distinct, explicitly enabled fallback. It
        # may handle no-caption, empty-caption, or unreachable-caption
        # outcomes, but it must never run for a private video.
        if self._local_fallback is not None:
            return self._local_fallback.fetch(video_id, languages)

        # Everything failed to be reached. Report the preferred source's
        # failure rather than optional-fallback noise.
        return terminal or (attempts[0] if attempts else TranscriptResult(
            availability=TranscriptAvailability.FETCH_FAILED,
            detail="no transcript source was configured",
        ))
