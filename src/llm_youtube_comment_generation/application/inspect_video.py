"""The first use case: retrieve a video and report honestly what is there.

Deliberately the smallest thing that exercises the whole stack. It proves the
adapters, the ports, the domain rules and the exit-code mapping on real data
before anything harder is built on them.

Nothing here formats output. The handler returns a typed result and the CLI
or GUI renders it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.comments import merge_comments, select_reply_parents
from ..domain.section_profile import CommentRegister, measure_comment_register
from ..domain.statuses import (
    OperationResult,
    RetrievalOutcome,
    RetrievalStatus,
    TranscriptAvailability,
    WarningCode,
)
from ..ports.events import EventKind, ProgressEvent
from ..domain.statuses import TranscriptResult
from .commands import InspectVideoCommand

# How many threads get their replies fetched. A quota decision: fetching
# every thread on a busy video would spend the day's allowance on one run.
# Reported whenever it bites — see the truncation outcome in handle().
REPLY_THREAD_LIMIT = 20


@dataclass
class VideoInspection:
    """What `video inspect` found."""

    video: dict[str, Any] = field(default_factory=dict)
    relevance_comments: list[dict[str, Any]] = field(default_factory=list)
    recent_comments: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    replies: list[dict[str, Any]] = field(default_factory=list)
    register: CommentRegister = field(default_factory=CommentRegister)
    retrieval: RetrievalOutcome = field(default_factory=RetrievalOutcome)
    transcript_availability: TranscriptAvailability = (
        TranscriptAvailability.NOT_PUBLISHED
    )
    transcript_language: str = ""
    transcript_entries: int = 0
    # Internal build context. Public formatters continue to expose the
    # summary fields above, while packet construction reuses this exact
    # acquisition instead of asking the transcript provider a second time.
    transcript: TranscriptResult | None = None
    api_operations_used: int = 0
    dry_run: bool = False


def worst(outcomes: list[RetrievalOutcome]) -> RetrievalStatus:
    """The least complete status among several retrievals.

    A run is only as honest as its weakest scan. Reporting COMPLETE because
    most pages finished would be exactly the overstatement this whole status
    model exists to prevent.
    """

    order = [
        RetrievalStatus.CANCELLED,
        RetrievalStatus.PAGE_TOKEN_LOOP,
        RetrievalStatus.TOP_LEVEL_TRUNCATED,
        RetrievalStatus.REPLY_THREAD_TRUNCATED,
        RetrievalStatus.COMPLETE,
    ]
    statuses = [outcome.status for outcome in outcomes] or [RetrievalStatus.COMPLETE]
    return min(statuses, key=order.index)


def handle(
    command: InspectVideoCommand,
    *,
    youtube,
    transcripts,
    events,
) -> OperationResult:
    result = OperationResult()

    events.emit(ProgressEvent(
        EventKind.STARTED, step="inspect",
        message=f"Inspecting {command.video_id}",
    ))

    if command.dry_run:
        # A dry run must perform no request at all. Reporting what *would*
        # happen is the whole value: an operator checking a command before
        # spending quota gets no benefit from a version that spends some.
        events.emit(ProgressEvent(
            EventKind.FINISHED, step="inspect",
            message="Dry run: no request was sent",
        ))
        result.value = VideoInspection(
            video={"video_id": command.video_id},
            dry_run=True,
        )
        result.metrics = {"api_operations": 0}
        return result

    events.emit(ProgressEvent(EventKind.STEP, step="video",
                              message="Fetching video metadata"))
    video = youtube.video(command.video_id)

    outcomes: list[RetrievalOutcome] = []
    pages = []
    for order in ("relevance", "time"):
        events.emit(ProgressEvent(
            EventKind.STEP, step="comments",
            message=f"Fetching comments by {order}",
        ))
        page = youtube.comment_threads(
            command.video_id, order=order, maximum=command.max_comments
        )
        pages.append(page)
        outcomes.append(page.outcome)

    comments = merge_comments([page.comments for page in pages])
    events.emit(ProgressEvent(
        EventKind.PROGRESS, step="comments",
        current=len(comments), total=len(comments),
        message="Comments retrieved",
    ))

    replies: list[dict[str, Any]] = []
    if command.include_replies:
        with_replies = [c for c in comments
                        if (c.get("total_reply_count") or 0) > 0]
        parents = select_reply_parents(comments, REPLY_THREAD_LIMIT)

        # The cap is a quota decision, and applying it silently would let the
        # run report COMPLETE while never having asked for some replies at
        # all. A limit the caller cannot see is indistinguishable from an
        # absence, which is the one confusion this application must not make.
        if len(with_replies) > len(parents):
            outcomes.append(RetrievalOutcome(
                status=RetrievalStatus.REPLY_THREAD_TRUNCATED,
                retrieved=len(parents),
                reported_total=len(with_replies),
                notes=(
                    f"replies were fetched for the {len(parents)} busiest "
                    f"threads of {len(with_replies)} that have any; the rest "
                    "were not requested",
                ),
            ))

        for index, parent in enumerate(parents, 1):
            page = youtube.replies(
                parent["comment_id"],
                maximum=command.max_replies_per_thread,
            )
            replies.extend(page.comments)
            outcomes.append(page.outcome)
            events.emit(ProgressEvent(
                EventKind.PROGRESS, step="replies",
                current=index, total=len(parents),
            ))

    events.emit(ProgressEvent(
        EventKind.STEP, step="transcript",
        message="Fetching the transcript",
    ))
    transcript = transcripts.fetch(
        command.video_id, command.transcript_languages
    )
    if not transcript.available:
        result.warn(
            WarningCode.TRANSCRIPT_UNAVAILABLE,
            transcript.detail or transcript.availability.value,
        )

    retrieval = RetrievalOutcome(
        status=worst(outcomes),
        retrieved=len(comments) + len(replies),
        reported_total=video.get("comment_count"),
        api_operations_used=youtube.api_operations_used,
        notes=tuple(note for outcome in outcomes for note in outcome.notes),
    )
    if not retrieval.may_conclude_absence:
        # Warn on the honest question — "can this run prove a comment is
        # absent" — rather than on the status alone. A complete scan with an
        # unexplained shortfall still cannot.
        shortfall = (f", {retrieval.missing:,} fewer than the {retrieval.reported_total:,} "
                     "reported" if retrieval.has_shortfall else "")
        result.warn(
            WarningCode.RETRIEVAL_INCOMPLETE,
            f"retrieval was {retrieval.status.value}; "
            f"{retrieval.retrieved:,} items were seen{shortfall}",
        )

    events.emit(ProgressEvent(
        EventKind.FINISHED, step="inspect",
        message=(
            f"Done. {youtube.api_operations_used} logical YouTube API "
            "operations used"
        ),
    ))

    result.value = VideoInspection(
        video=video,
        relevance_comments=list(pages[0].comments),
        recent_comments=list(pages[1].comments),
        comments=comments,
        replies=replies,
        register=measure_comment_register(comments, replies),
        retrieval=retrieval,
        transcript_availability=transcript.availability,
        transcript_language=transcript.language,
        transcript_entries=len(transcript.entries),
        transcript=transcript,
        api_operations_used=youtube.api_operations_used,
    )
    result.metrics = {
        "comments": len(comments),
        "replies": len(replies),
        "api_operations": youtube.api_operations_used,
    }
    return result
