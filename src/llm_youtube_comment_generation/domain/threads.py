"""The operator's own comment threads and the time rules around them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .errors import ConfigurationError
from .targeting import annotate_reply_targets


def as_moment(value: Any) -> datetime:
    """Parse a YouTube timestamp. Unparseable values sort first, never newest.

    String comparison looked fine until a fractional second appeared:
    "2026-07-01T12:00:00.123Z" sorts BEFORE "2026-07-01T12:00:00Z" because
    "." precedes "Z", so a reply that arrived after the cutoff was reported as
    older than it.
    """

    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)  # unknown sorts first
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def parse_since(value: str | None, now: datetime | None = None) -> str | None:
    """Accept a day count, an ISO date, or a full ISO datetime.

    ``now`` is injected rather than read from the clock. The legacy version
    called datetime.now() directly, which made "7 days back" untestable
    without freezing time globally; the clock is a port in this architecture.
    """

    text = (value or "").strip()
    if not text:
        return None

    if text.isdigit():
        moment = (now or datetime.now(timezone.utc)) - timedelta(days=int(text))
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigurationError(
            "Invalid --since value. Use a number of days back, an ISO date "
            f"such as 2026-07-01, or a full ISO datetime. Got: {value}"
        ) from exc

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reply_is_new(reply: dict[str, Any], since_iso: str | None) -> bool:
    if not since_iso:
        return True
    return as_moment(reply.get("published_at")) >= as_moment(since_iso)


@dataclass
class OwnerThread:
    """One comment the packet owner posted, with the replies it drew."""

    comment: dict[str, Any] = field(default_factory=dict)
    replies: list[dict[str, Any]] = field(default_factory=list)
    new_replies: list[dict[str, Any]] = field(default_factory=list)
    reported_reply_count: int = 0

    @property
    def comment_id(self) -> str:
        return str(self.comment.get("comment_id") or "")

    @property
    def truncated(self) -> bool:
        return self.reported_reply_count > len(self.replies)

    def audience_replies(self, owner_channel_id: str) -> list[dict[str, Any]]:
        """Replies written by other people. Your own are context, not inbox."""

        if not owner_channel_id:
            return list(self.replies)
        return [
            r for r in self.replies
            if r.get("author_channel_id") != owner_channel_id
        ]

    def new_audience_replies(self, owner_channel_id: str) -> list[dict[str, Any]]:
        if not owner_channel_id:
            return list(self.new_replies)
        return [
            r for r in self.new_replies
            if r.get("author_channel_id") != owner_channel_id
        ]

    def direct_replies(self, owner_channel_id: str) -> list[dict[str, Any]]:
        """Replies that address the owner, not each other.

        "Audience replies" and "replies to you" are different numbers: on one
        real thread 161 audience replies contained only 92 aimed at the owner.
        Reporting the first as the second is misleading.
        """

        return [
            r
            for r in annotate_reply_targets(
                self.comment.get("author", ""),
                self.audience_replies(owner_channel_id),
                owner_channel_id,
            )
            if r.get("responds_to_owner")
        ]

    def new_direct_replies(self, owner_channel_id: str) -> list[dict[str, Any]]:
        new_ids = {str(r.get("comment_id")) for r in self.new_replies}
        return [
            r for r in self.direct_replies(owner_channel_id)
            if str(r.get("comment_id")) in new_ids
        ]
