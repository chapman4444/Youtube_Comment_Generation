"""Fall back to a transcript this machine already has.

The caption endpoint is a third-party scraper and it rate-limits by IP. Twenty
builds of one video in an afternoon was enough to get this machine blocked,
and every build afterwards refused — while the transcript sat in the previous
run's directory, unchanged and perfectly usable.

Losing a build to that is absurd. A published video's captions do not change
between one hour and the next, and the operator already has them.

Two rules make this safe rather than merely convenient:

Only on failure. A live transcript always wins, so the fallback cannot hide a
transcript that has since been corrected or translated.

Never silent. The result says where the transcript came from and when it was
saved, that detail reaches the packet's own transcript status, and the run
record keeps it. A packet built from an hour-old transcript is fine; a packet
built from one without saying so is not.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable, Sequence

from ..domain.statuses import TranscriptAvailability, TranscriptResult

LOGGER = logging.getLogger(__name__)

SOURCE = "saved-transcript"
TIMESTAMPED = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\]\s*(.*)$")


def parse_timestamped(text: str) -> list[dict[str, object]]:
    """Turn a saved transcript_timestamped.txt back into entries.

    The saved form has no durations — it was rendered for a human — so each
    entry runs until the next one starts. The last entry gets the same gap as
    the one before it rather than a fabricated length.
    """

    starts: list[tuple[float, str]] = []
    for line in (text or "").splitlines():
        found = TIMESTAMPED.match(line.strip())
        if not found:
            continue
        hours, minutes, seconds, body = found.groups()
        starts.append(
            (int(hours) * 3600 + int(minutes) * 60 + int(seconds), body)
        )

    entries: list[dict[str, object]] = []
    for index, (start, body) in enumerate(starts):
        if index + 1 < len(starts):
            duration = max(0.0, starts[index + 1][0] - start)
        else:
            duration = entries[-1]["duration"] if entries else 0.0
        entries.append({"text": body, "start": float(start),
                        "duration": float(duration)})
    return entries


def find_saved(output_directory: Path, video_id: str) -> Path | None:
    """The most recently written saved transcript for this video."""

    if not video_id or not output_directory.is_dir():
        return None
    candidates = [
        path
        for path in output_directory.glob(f"{video_id}_*/transcript_timestamped.txt")
        if path.is_file() and path.stat().st_size > 0
    ]
    if not candidates:
        return None
    # Ordered by the run stamp in the directory name, not by mtime. Three
    # runs written in the same second tie on mtime and the winner is then
    # arbitrary, and copying a run directory changes its mtime without
    # changing when the transcript was actually fetched.
    return max(candidates, key=lambda path: path.parent.name)


class SavedTranscriptFallback:
    """Try published captions, then disk, then an approved local transcript."""

    def __init__(
        self,
        inner,
        output_directory,
        *,
        local_fallback=None,
        approve_local_fallback: Callable[[TranscriptResult], bool] | None = None,
    ) -> None:
        self._inner = inner
        self._output = Path(output_directory)
        self._local_fallback = local_fallback
        self._approve_local_fallback = approve_local_fallback

    def fetch(
        self, video_id: str, languages: Sequence[str] = (),
    ) -> TranscriptResult:
        live = (
            self._inner.fetch(video_id, languages)
            if self._inner is not None
            else TranscriptResult(
                availability=TranscriptAvailability.FETCH_FAILED,
                source="saved-transcript",
                detail="manual saved-transcript lookup",
            )
        )
        if live.entries:
            return live
        if live.availability is TranscriptAvailability.NOT_PUBLIC:
            # A private video is terminal. Reusing an older public transcript
            # would turn the current access state into AVAILABLE and make a
            # new packet look supportable from evidence that is no longer
            # publicly reachable.
            return live

        saved = find_saved(self._output, video_id)
        if saved is not None:
            entries = parse_timestamped(saved.read_text(encoding="utf-8"))
            if entries:
                when = saved.parent.name.split("_", 1)[-1]
                LOGGER.info(
                    "using the transcript saved in %s: %s",
                    saved.parent,
                    live.detail,
                )
                return TranscriptResult(
                    availability=TranscriptAvailability.AVAILABLE,
                    entries=entries,
                    source=SOURCE,
                    detail=(
                        f"the live fetch failed ({_reason(live)}), so this is "
                        f"the transcript saved with run {when}. It is reused "
                        "unchanged and was not fetched again."
                    ),
                )

        if self._local_fallback is None:
            return live
        if (
            self._approve_local_fallback is not None
            and not self._approve_local_fallback(live)
        ):
            return live
        return self._local_fallback.fetch(video_id, languages)


def _reason(live: TranscriptResult) -> str:
    """The failure in a few words.

    The caption library's message is a thousand characters of README links.
    Printing all of it buried the one sentence the operator needed inside a
    wall of text about cloud providers. The whole thing still goes to the log.
    """

    detail = (live.detail or "").strip()
    first = next((line.strip() for line in detail.splitlines() if line.strip()),
                 "")
    first = first.rstrip("!:. ")
    if not first:
        return live.availability.value
    return first if len(first) <= 80 else first[:77].rstrip() + "..."
