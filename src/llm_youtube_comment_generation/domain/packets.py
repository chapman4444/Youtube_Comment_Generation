"""Packet budgeting: how much of each section the character budget affords.

Budgeting only. Rendering is a separate concern and arrives with the packet
builder; the legacy ``fit_caps_to_budget`` measured by rendering candidate
packets and re-measuring, which is the "repeated render-and-shrink" pattern
08_ANTI_PATTERNS.md names. Measuring and allocating happens here, before any
text is produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Sequence

from .video import as_int


@dataclass(frozen=True)
class SectionCaps:
    """Upper bounds for each packet section at full fidelity."""

    relevant_comments: int = 75
    most_liked_comments: int = 30
    most_replied_comments: int = 20
    recent_comments: int = 40
    reply_threads: int = 20
    replies_per_thread: int = 8
    comment_body: int = 1_600
    reply_body: int = 1_000
    description: int = 8_000

    @property
    def protected_comment_slots(self) -> int:
        """Every top-level slot the allocator refuses to reduce.

        most_replied_comments belongs here: that section is rendered and its
        count is never cut, so leaving it out understated the mandatory cost
        and made the advertised minimum unreachable on any video whose
        comments actually have replies.
        """

        return (
            self.relevant_comments
            + self.most_liked_comments
            + self.recent_comments
            + self.most_replied_comments
        )


@dataclass(frozen=True)
class SectionFloors:
    """Lower bounds that packet fitting will not cut below."""

    comment_body: int = 500
    description: int = 2_000
    transcript: int = 20_000


CAPS = SectionCaps()
FLOORS = SectionFloors()

# Assembly overhead that is not attributable to any single section: the
# workflow contract, boundaries, metadata block, section headers, reduction
# summary and final output check.
PACKET_SCAFFOLDING_ALLOWANCE = 12_000
COMMENT_RENDER_OVERHEAD = 160

# The smallest budget the allocator can actually satisfy. Top-level comment
# coverage is never reduced, so the protected slots at their floor body size
# plus the transcript and description floors plus scaffolding is a hard bound.
MINIMUM_PACKET_CHARACTERS = (
    PACKET_SCAFFOLDING_ALLOWANCE
    + FLOORS.transcript
    + FLOORS.description
    + CAPS.protected_comment_slots * (FLOORS.comment_body + COMMENT_RENDER_OVERHEAD)
)
DEFAULT_PACKET_CHARACTERS = 280_000

# The share of the budget the selectable registers and dials may consume.
# Instructions that grow without bound would silently displace evidence.
INSTRUCTION_BUDGET_SHARE = 0.10


@dataclass
class PacketSelection:
    """Which comments and threads each packet section will render."""

    most_replied: list[dict[str, Any]] = field(default_factory=list)
    relevant: list[dict[str, Any]] = field(default_factory=list)
    most_liked: list[dict[str, Any]] = field(default_factory=list)
    recent: list[dict[str, Any]] = field(default_factory=list)
    threads: list[tuple[dict[str, Any], list[dict[str, Any]]]] = field(
        default_factory=list
    )
    relevant_eligible: int = 0
    most_liked_eligible: int = 0
    most_replied_eligible: int = 0
    recent_eligible: int = 0
    threads_eligible: int = 0

    @property
    def rendered_ids(self) -> set[str]:
        return {
            comment.get("comment_id", "")
            for group in (
                self.most_liked,
                self.most_replied,
                self.relevant,
                self.recent,
            )
            for comment in group
            if comment.get("comment_id")
        }


@dataclass
class PacketAllocation:
    """The size decisions the allocator made, reported verbatim in the packet."""

    comment_body: int = CAPS.comment_body
    reply_body: int = CAPS.reply_body
    reply_threads: int = CAPS.reply_threads
    replies_per_thread: int = CAPS.replies_per_thread
    description: int = CAPS.description
    transcript: int = 0
    transcript_reduced: bool = False


def select_packet_sections(
    top_comments: Sequence[dict[str, Any]],
    recent_comments: Sequence[dict[str, Any]],
    comments: Sequence[dict[str, Any]],
    replies: Sequence[dict[str, Any]],
    *,
    caps: SectionCaps = CAPS,
) -> PacketSelection:
    """Choose section contents once, so every later step agrees on the counts."""

    by_id = {
        comment.get("comment_id", ""): comment
        for comment in comments
        if comment.get("comment_id")
    }
    used: set[str] = set()

    def take(
        source: Iterable[dict[str, Any]],
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        chosen: list[dict[str, Any]] = []
        eligible = 0
        for comment in source:
            comment_id = comment.get("comment_id", "")
            if not comment_id or comment_id in used:
                continue
            eligible += 1
            if len(chosen) < limit:
                chosen.append(by_id.get(comment_id, comment))
        for comment in chosen:
            used.add(comment.get("comment_id", ""))
        return chosen, eligible

    # Most-liked is taken first. When relevance went first it consumed the
    # highest-liked comments, leaving the "highest-liked" section holding the
    # leftovers: on one measured video its ceiling was 82 likes while the
    # relevance section above it carried a comment with 7,211.
    most_liked_source = sorted(
        comments,
        key=lambda comment: (
            as_int(comment.get("like_count")) or 0,
            str(comment.get("published_at") or ""),
        ),
        reverse=True,
    )
    most_liked, most_liked_eligible = take(most_liked_source, caps.most_liked_comments)

    # Replies are a separate outcome from likes. Measured across 1,506 real
    # comments the two top-40 lists overlap only 67 percent, and the comments
    # that draw replies name a specific person far more often (30 percent
    # against a 19 percent baseline). Surfacing them separately gives the
    # reader both signals instead of one.
    most_replied_source = sorted(
        comments,
        key=lambda comment: (
            as_int(comment.get("total_reply_count")) or 0,
            as_int(comment.get("like_count")) or 0,
        ),
        reverse=True,
    )
    most_replied, most_replied_eligible = take(
        [
            comment
            for comment in most_replied_source
            if (as_int(comment.get("total_reply_count")) or 0) > 0
        ],
        caps.most_replied_comments,
    )

    relevant, relevant_eligible = take(top_comments, caps.relevant_comments)
    recent, recent_eligible = take(recent_comments, caps.recent_comments)

    by_parent: dict[str, list[dict[str, Any]]] = {}
    for reply in replies:
        parent_id = reply.get("parent_comment_id") or ""
        if parent_id:
            by_parent.setdefault(parent_id, []).append(reply)

    ordered_threads = sorted(
        by_parent.items(),
        key=lambda item: (
            as_int(by_id.get(item[0], {}).get("total_reply_count")) or 0,
            len(item[1]),
            as_int(by_id.get(item[0], {}).get("like_count")) or 0,
        ),
        reverse=True,
    )
    threads = [
        (
            by_id.get(parent_id, {"comment_id": parent_id}),
            sorted(thread, key=lambda reply: str(reply.get("published_at") or "")),
        )
        for parent_id, thread in ordered_threads
    ]

    return PacketSelection(
        most_replied=most_replied,
        relevant=relevant,
        most_liked=most_liked,
        recent=recent,
        threads=threads,
        relevant_eligible=relevant_eligible,
        most_liked_eligible=most_liked_eligible,
        most_replied_eligible=most_replied_eligible,
        recent_eligible=recent_eligible,
        threads_eligible=len(threads),
    )


def grow(caps: SectionCaps, factor: int) -> SectionCaps:
    """Scale the sections that should absorb spare budget.

    The highest-liked section is a fixed top-N showcase and stays at its
    default: scaling it too made it swallow the entire retrieved pool, leaving
    the relevance and recent sections empty. Spare budget goes to the relevance
    sample, which is where additional coverage is actually useful, and to the
    recent sample at a slower rate.
    """

    return replace(
        caps,
        relevant_comments=caps.relevant_comments * factor,
        recent_comments=caps.recent_comments + (caps.recent_comments * (factor - 1)) // 2,
    )
