"""What actually happened to the replies that were drafted.

The whole engagement question rests on this command, and its single most
important property is negative: **it never says a draft was not posted when
the scan that looked for it was incomplete.** That claim is the one this
project could most easily get wrong, and getting it wrong would quietly
invalidate every conclusion drawn from the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.history import score_history
from ..domain.statuses import (
    HistoryMatchStatus,
    OperationResult,
    RetrievalOutcome,
    RetrievalStatus,
    WarningCode,
)
from ..ports.events import EventKind, ProgressEvent


@dataclass
class Scoreboard:
    rows: list[dict[str, Any]] = field(default_factory=list)
    retrieval: RetrievalOutcome = field(default_factory=RetrievalOutcome)
    counted: bool = True

    @property
    def matched(self) -> list[dict[str, Any]]:
        return [r for r in self.rows
                if r["match_status"] == HistoryMatchStatus.MATCHED]

    @property
    def ambiguous(self) -> list[dict[str, Any]]:
        return [r for r in self.rows
                if r["match_status"] == HistoryMatchStatus.AMBIGUOUS]

    @property
    def unmatched(self) -> list[dict[str, Any]]:
        return [r for r in self.rows
                if r["match_status"] == HistoryMatchStatus.UNMATCHED]

    @property
    def total_likes(self) -> int:
        return sum(int(r.get("likes") or 0) for r in self.matched)


def handle(
    video_id: str,
    *,
    history,
    youtube,
    events,
    max_comments: int = 2000,
) -> OperationResult:
    result = OperationResult()
    events.emit(ProgressEvent(EventKind.STARTED, step="scoreboard",
                              message=f"Scoring {video_id or 'every video'}"))

    drafts = history.load()
    if video_id:
        drafts = [d for d in drafts if d.get("video_id") == video_id]

    outcomes: list[RetrievalOutcome] = []
    posted: list[dict[str, Any]] = []

    if video_id and drafts:
        page = youtube.comment_threads(video_id, order="time",
                                       maximum=max_comments)
        posted.extend(page.comments)
        outcomes.append(page.outcome)
        for comment in list(page.comments):
            if (comment.get("total_reply_count") or 0) > 0:
                thread = youtube.replies(comment["comment_id"], maximum=1000)
                posted.extend(thread.comments)
                outcomes.append(thread.outcome)

    retrieval = RetrievalOutcome(
        status=_worst(outcomes),
        retrieved=len(posted),
        requests_used=getattr(youtube, "requests_used", 0),
        notes=tuple(note for outcome in outcomes for note in outcome.notes),
    )

    rows = score_history(posted, drafts, video_id)

    # The load-bearing refusal. An incomplete scan cannot distinguish "this
    # reply was never posted" from "I did not look far enough", and reporting
    # the first when only the second is known is how the measurement lies.
    if not retrieval.may_conclude_absence:
        for row in rows:
            if row["match_status"] == HistoryMatchStatus.UNMATCHED:
                row["match_status"] = HistoryMatchStatus.AMBIGUOUS
                row["unmatched_because_scan_incomplete"] = True
        result.warn(
            WarningCode.RETRIEVAL_INCOMPLETE,
            f"the scan was {retrieval.status.value}, so no draft can be "
            "reported as unposted; those rows are shown as unconfirmed",
        )

    board = Scoreboard(
        rows=rows,
        retrieval=retrieval,
        counted=retrieval.may_conclude_absence,
    )

    events.emit(ProgressEvent(
        EventKind.FINISHED, step="scoreboard",
        message=f"{len(board.matched)} of {len(rows)} drafts found",
    ))

    result.value = board
    result.metrics = {
        "drafts": len(rows),
        "matched": len(board.matched),
        "ambiguous": len(board.ambiguous),
        "unmatched": len(board.unmatched),
        "likes": board.total_likes,
    }
    return result


def _worst(outcomes: list[RetrievalOutcome]) -> RetrievalStatus:
    order = [
        RetrievalStatus.CANCELLED,
        RetrievalStatus.PAGE_TOKEN_LOOP,
        RetrievalStatus.TOP_LEVEL_TRUNCATED,
        RetrievalStatus.REPLY_THREAD_TRUNCATED,
        RetrievalStatus.COMPLETE,
    ]
    statuses = [o.status for o in outcomes] or [RetrievalStatus.COMPLETE]
    return min(statuses, key=order.index)


def render(board: Scoreboard) -> str:
    """The scoreboard, written so its limits are as visible as its findings."""

    lines = [
        "# What happened to the replies you drafted",
        "",
        f"- drafts recorded: {len(board.rows)}",
        f"- found on YouTube: {len(board.matched)}",
        f"- could not be identified: {len(board.ambiguous)}",
        f"- not found: {len(board.unmatched)}",
        f"- likes on found replies: {board.total_likes:,}",
        "",
    ]

    if not board.counted:
        lines.extend([
            "**This scan was incomplete.** No draft below is reported as",
            "unposted, because an incomplete scan cannot tell 'it is not",
            "there' from 'I did not look far enough'.",
            "",
        ])

    if not board.rows:
        lines.extend(["_No drafts have been recorded yet._", ""])
        return "\n".join(lines)

    if board.matched:
        lines.extend(["## Found", ""])
        for row in sorted(board.matched,
                          key=lambda r: int(r.get("likes") or 0), reverse=True):
            lines.append(
                f"- **{int(row.get('likes') or 0):,} likes** — "
                f"{str(row.get('draft',''))[:100]}"
            )
        lines.append("")

    if board.ambiguous:
        lines.extend([
            "## Could not be identified",
            "",
            "_More than one live reply matched, or the scan was incomplete._",
            "",
        ])
        for row in board.ambiguous:
            lines.append(f"- {str(row.get('draft',''))[:100]}")
        lines.append("")

    if board.unmatched:
        lines.extend(["## Not found on YouTube", "",
                      "_Drafted but apparently never posted._", ""])
        for row in board.unmatched:
            lines.append(f"- {str(row.get('draft',''))[:100]}")
        lines.append("")

    lines.extend([
        "## What this is evidence of",
        "",
        f"- retrieval: {board.retrieval.status.value}",
        f"- comments and replies scanned: {board.retrieval.retrieved:,}",
    ])
    for note in board.retrieval.notes:
        lines.append(f"- {note}")
    return "\n".join(lines)
