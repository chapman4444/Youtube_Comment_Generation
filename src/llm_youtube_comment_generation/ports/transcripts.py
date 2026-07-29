"""Transcript access.

Separate from the YouTube port because it is a separate system: the caption
library is a third-party scraper, not the Data API, and it fails in ways the
API does not. Merging them would mean a transcript outage looked like a
YouTube outage.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from ..domain.statuses import TranscriptResult


@runtime_checkable
class TranscriptPort(Protocol):
    def fetch(
        self,
        video_id: str,
        languages: Sequence[str] = ("en",),
    ) -> TranscriptResult:
        """Return a transcript, or a precise account of why there is none.

        This never raises for an absent transcript. A video without captions
        is an ordinary outcome that must not fail the run — the packet is
        still worth building — so the absence arrives as a
        ``TranscriptAvailability`` value and the caller decides.
        """
        ...
