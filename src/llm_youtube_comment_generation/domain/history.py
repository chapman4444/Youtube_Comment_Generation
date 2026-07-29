"""Matching drafted replies against what is actually on YouTube now.

Only the matching rule lives here. Reading and writing the history file is
I/O and belongs to an adapter; this module is given the two lists and decides
what corresponds to what.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from .targeting import strip_invisible
from .video import as_int


def normalise_for_match(text: str) -> str:
    """Reduce a reply to something that survives a trip through YouTube."""

    body = strip_invisible(str(text or "")).casefold()
    body = re.sub(r"^@[\w.\-]+\s*", "", body)      # a leading mention
    body = re.sub(r"[^a-z0-9 ]+", " ", body)
    return " ".join(body.split())


def score_history(
    posted: Sequence[dict[str, Any]],
    history: Sequence[dict[str, Any]],
    video_id: str = "",
) -> list[dict[str, Any]]:
    """Match drafts against what is actually on YouTube now.

    Matching is on normalised text rather than an ID, because the operator
    posts by hand and may edit before posting. A prefix match is enough to
    identify a reply and tolerant enough to survive a small edit.

    One live reply may satisfy at most one draft. Prefix matching alone, with
    nothing ever consumed, let two drafts that opened the same way both claim
    the same posted reply and its likes, which silently doubled the only
    numbers this project measures. Exact text is settled first so a prefix
    collision cannot steal a certain match, and a draft left with more than
    one candidate is reported ambiguous rather than guessed at.

    Ambiguous is not the same as unmatched: one says the reply cannot be
    identified, the other says it is not there. Collapsing them would put an
    uncertain row under a heading that reads as a finding.
    """

    live = []
    for reply in posted:
        body = normalise_for_match(reply.get("text"))
        if body:
            live.append((body, as_int(reply.get("like_count")) or 0, reply))

    rows = [entry for entry in history
            if not (video_id and entry.get("video_id") != video_id)]
    wanted = [normalise_for_match(entry.get("draft", "")) for entry in rows]

    matched: dict[int, int] = {}    # row index -> index into live
    claimed: set[int] = set()
    unsure: set[int] = set()

    def claim(row: int, candidates: list[int]) -> None:
        """One candidate is an identification. Two is a coin toss."""

        if len(candidates) == 1:
            matched[row] = candidates[0]
            claimed.add(candidates[0])
            unsure.discard(row)
        elif len(candidates) > 1:
            unsure.add(row)

    # Every exact pair is settled before any prefix matching, so a draft that
    # merely opens like a posted reply cannot consume the reply that another
    # draft matches word for word.
    for row, text in enumerate(wanted):
        if not text:
            continue
        claim(row, [j for j, item in enumerate(live)
                    if j not in claimed and item[0] == text])

    for row, text in enumerate(wanted):
        if not text or row in matched:
            continue
        head = text[:60]
        claim(row, [
            j for j, item in enumerate(live)
            if j not in claimed
            and (item[0].startswith(head) or text.startswith(item[0][:60]))
        ])

    scored: list[dict[str, Any]] = []
    for row, entry in enumerate(rows):
        if not wanted[row]:
            continue
        found = live[matched[row]] if row in matched else None
        if found is not None:
            status = "matched"
        elif row in unsure:
            status = "ambiguous"
        else:
            status = "unmatched"
        scored.append({
            **entry,
            "posted": found is not None,
            "likes": found[1] if found else None,
            "posted_text": found[2].get("text") if found else "",
            "match_status": status,
        })
    return scored
