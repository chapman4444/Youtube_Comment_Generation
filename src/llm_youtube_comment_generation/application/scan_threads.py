"""Find the operator's own threads and work out who is owed a reply.

Thread assembly is the only new logic here; the answered-state rules are the
ported domain, unchanged. That split is deliberate — this is where the legacy
application's subtlest bugs lived, and ported tests rather than fresh
judgement are the safety net.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.candidates import ReplyCandidate, candidates_across_threads
from ..domain.comments import merge_comments
from ..domain.errors import ConfigurationError
from ..domain.ids import extract_video_id, normalise_handle, validate_channel_id
from ..domain.statuses import (
    OperationResult,
    RetrievalOutcome,
    RetrievalStatus,
    WarningCode,
)
from ..domain.threads import OwnerThread, parse_since, reply_is_new
from ..ports.events import EventKind, ProgressEvent


@dataclass(frozen=True)
class ScanMyThreadsCommand:
    video: str
    channel_id: str = ""
    handle: str = ""
    since: str = ""
    max_comments: int = 500
    max_replies_per_thread: int = 100
    only_unanswered: bool = True

    video_id: str = field(init=False, default="")

    def __post_init__(self) -> None:
        object.__setattr__(self, "video_id", extract_video_id(self.video))
        if self.max_comments < 1:
            raise ConfigurationError("max_comments must be at least 1.")
        if self.max_replies_per_thread < 1:
            raise ConfigurationError(
                "max_replies_per_thread must be at least 1."
            )
        if not self.channel_id and not self.handle:
            raise ConfigurationError(
                "Reply mode needs to know who you are. Pass --my-handle "
                "@yourchannel (or --my-channel-id), or set it once with "
                "YTCOMMENT_MY_HANDLE so you never have to pass it again."
            )


@dataclass
class ThreadScan:
    threads: list[OwnerThread] = field(default_factory=list)
    candidates: list[ReplyCandidate] = field(default_factory=list)
    owner_channel_id: str = ""
    retrieval: RetrievalOutcome = field(default_factory=RetrievalOutcome)
    api_operations_used: int = 0
    scanned_comments: int = 0


def resolve_identity(command: ScanMyThreadsCommand, youtube) -> str:
    """Turn whatever the operator gave us into a channel ID.

    Refuses rather than continuing without one. A scan with no identity would
    treat every reply as somebody else's and report an empty queue, which
    looks exactly like having nothing to answer.
    """

    if command.channel_id:
        return validate_channel_id(command.channel_id)
    return youtube.channel_id_for_handle(normalise_handle(command.handle))


def handle(
    command: ScanMyThreadsCommand,
    *,
    youtube,
    events,
    clock=None,
) -> OperationResult:
    result = OperationResult()
    events.emit(ProgressEvent(EventKind.STARTED, step="scan",
                              message=f"Scanning {command.video_id}"))

    owner = resolve_identity(command, youtube)
    cutoff = parse_since(
        command.since, now=clock.now() if clock else None
    ) if command.since else None

    outcomes: list[RetrievalOutcome] = []
    pages = []
    for order in ("relevance", "time"):
        events.emit(ProgressEvent(EventKind.STEP, step="scan",
                                  message=f"Scanning comments by {order}"))
        page = youtube.comment_threads(
            command.video_id, order=order, maximum=command.max_comments
        )
        pages.append(page)
        outcomes.append(page.outcome)

    scanned = merge_comments([page.comments for page in pages])
    mine = [c for c in scanned if c.get("author_channel_id") == owner]

    if not mine:
        # Silence here reads as "you have no threads", which is a different
        # and much more misleading claim than "I did not find them".
        result.warn(
            WarningCode.RETRIEVAL_INCOMPLETE,
            f"no comment by {owner} was found in the first "
            f"{len(scanned):,} comments of either ordering. Raise "
            "--max-comments if your comment is further down.",
        )

    threads: list[OwnerThread] = []
    for index, comment in enumerate(mine, 1):
        page = youtube.replies(
            comment["comment_id"],
            maximum=command.max_replies_per_thread,
        )
        outcomes.append(page.outcome)
        new = [r for r in page.comments if reply_is_new(r, cutoff)]
        threads.append(OwnerThread(
            comment=comment,
            replies=page.comments,
            new_replies=new,
            reported_reply_count=comment.get("total_reply_count", 0) or 0,
        ))
        events.emit(ProgressEvent(EventKind.PROGRESS, step="threads",
                                  current=index, total=len(mine)))

    truncated = [t for t in threads if t.truncated]
    if truncated:
        outcomes.append(RetrievalOutcome(
            status=RetrievalStatus.REPLY_THREAD_TRUNCATED,
            retrieved=sum(len(t.replies) for t in truncated),
            reported_total=sum(t.reported_reply_count for t in truncated),
            notes=tuple(
                f"thread {t.comment_id} reported {t.reported_reply_count:,} "
                f"replies but {len(t.replies):,} were retrieved"
                for t in truncated
            ),
        ))

    candidates = candidates_across_threads(owner, threads)

    retrieval = RetrievalOutcome(
        status=_worst(outcomes),
        retrieved=len(scanned) + sum(len(t.replies) for t in threads),
        reported_total=None,
        api_operations_used=youtube.api_operations_used,
        notes=tuple(note for outcome in outcomes for note in outcome.notes),
    )
    if not retrieval.may_conclude_absence:
        # The honest framing: an incomplete scan cannot prove somebody is not
        # waiting for an answer, which is the claim an empty queue implies.
        result.warn(
            WarningCode.RETRIEVAL_INCOMPLETE,
            f"retrieval was {retrieval.status.value}, so this queue may be "
            "missing people who are owed a reply",
        )

    events.emit(ProgressEvent(
        EventKind.FINISHED, step="scan",
        message=f"{len(candidates)} people found across {len(threads)} threads",
    ))

    result.value = ThreadScan(
        threads=threads,
        candidates=candidates,
        owner_channel_id=owner,
        retrieval=retrieval,
        api_operations_used=youtube.api_operations_used,
        scanned_comments=len(scanned),
    )
    result.metrics = {
        "threads": len(threads),
        "candidates": len(candidates),
        "outstanding": sum(1 for c in candidates if c.outstanding),
        "api_operations": youtube.api_operations_used,
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


def select_target(
    scan: ThreadScan,
    *,
    comment_id: str = "",
    handle: str = "",
) -> ReplyCandidate:
    """Pick one person to answer, by their comment id or their handle.

    Refuses on ambiguity rather than choosing. Two people with the same
    display name is a thing that happens, and answering the wrong one is not
    recoverable once it is posted.
    """

    if comment_id:
        matches = [c for c in scan.candidates
                   if str(c.reply.get("comment_id")) == comment_id]
        if matches:
            return matches[0]
        # A candidate holds one representative message per person, but the
        # packet answers every response in the thread — so any retrieved
        # response id, or the owner comment's own id, selects its thread.
        for thread in scan.threads:
            held = (str(thread.comment_id) == comment_id
                    or any(str(r.get("comment_id")) == comment_id
                           for r in thread.replies))
            if not held:
                continue
            owners = [c for c in scan.candidates
                      if c.thread_id == thread.comment_id]
            if owners:
                return owners[0]
            raise ConfigurationError(
                f"Comment {comment_id} is in one of your threads, but "
                "nobody there is outstanding. Use --all to include people "
                "you already answered."
            )
        raise ConfigurationError(
            f"No retrieved comment matches {comment_id}. Run "
            "`reply scan-mine` to see the ids."
        )

    if not handle:
        raise ConfigurationError("Choose a target by --comment-id or --handle.")

    wanted = handle.lstrip("@").casefold()
    matches = [c for c in scan.candidates
               if c.author.lstrip("@").casefold() == wanted]
    if not matches:
        raise ConfigurationError(
            f"Nobody called {handle} is in this queue. Run `reply scan-mine` "
            "to see who is."
        )
    if len(matches) > 1:
        ids = ", ".join(str(c.reply.get("comment_id")) for c in matches)
        raise ConfigurationError(
            f"{handle} matches {len(matches)} people in this queue, which "
            f"happens when two accounts share a display name. Choose by "
            f"--comment-id instead: {ids}"
        )
    return matches[0]
