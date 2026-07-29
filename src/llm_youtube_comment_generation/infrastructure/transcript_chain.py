"""Try each transcript source in turn, and say which one answered.

There are now three ways to get the words: the scrape endpoint, yt-dlp's
player API, and this machine's own saved copy from an earlier run. They fail
independently — an address blocked from the first was serving the second in
the same minute — so the useful thing is not picking one but ordering them.

Two rules, and the second is the one that matters.

**A source that says the video has no captions ends the search.** That is an
answer about the video, not a failure to reach it, and asking a second source
the same question wastes a request to be told the same thing. Only a failure
to *reach* a source moves on to the next.

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
CONCLUSIVE = frozenset({
    TranscriptAvailability.AVAILABLE,
    TranscriptAvailability.NOT_PUBLISHED,
    TranscriptAvailability.NOT_PUBLIC,
    TranscriptAvailability.EMPTY,
})


class ChainedTranscripts:
    """Implements TranscriptPort over several sources, in preference order."""

    def __init__(self, *sources) -> None:
        if not sources:
            raise ValueError("a transcript chain needs at least one source")
        self._sources = sources

    def fetch(
        self,
        video_id: str,
        languages: Sequence[str] = (),
    ) -> TranscriptResult:
        attempts: list[TranscriptResult] = []

        for source in self._sources:
            result = source.fetch(video_id, languages)
            if result.availability in CONCLUSIVE:
                if attempts and result.availability is TranscriptAvailability.AVAILABLE:
                    # Which sources were tried first, and why they did not
                    # answer. Without this a packet says "yt-dlp" and gives no
                    # hint that the usual source is refusing this machine.
                    LOGGER.info(
                        "%s answered after %d source(s) could not",
                        result.source, len(attempts),
                    )
                return result
            attempts.append(result)

        # Everything failed to be reached. Report the first failure rather
        # than the last: it is the one from the preferred source, and the
        # later ones are usually "not installed" noise about fallbacks the
        # operator never chose.
        return attempts[0] if attempts else TranscriptResult(
            availability=TranscriptAvailability.FETCH_FAILED,
            detail="no transcript source was configured",
        )
