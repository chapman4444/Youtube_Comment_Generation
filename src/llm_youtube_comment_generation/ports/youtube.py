"""Read-only access to YouTube.

Read-only is a product decision, not an oversight. This application never
posts: the operator writes and posts by hand, and the packet is a drafting
aid. There is deliberately no `post_reply` on this port, so no future use
case can quietly acquire the ability.

The port speaks in the application's terms — "give me the comments, and tell
me honestly whether that was all of them" — rather than in pages and tokens.
Pagination is the adapter's problem; completeness is the application's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

from ..domain.statuses import RetrievalOutcome


@dataclass
class CommentPage:
    """Comments plus an honest account of whether that is all of them.

    Returning the outcome alongside the data, rather than a bare list, is the
    whole point. A caller cannot forget to ask whether retrieval finished,
    because it arrives in the same object.
    """

    comments: list[dict[str, Any]] = field(default_factory=list)
    outcome: RetrievalOutcome = field(default_factory=RetrievalOutcome)

    def __len__(self) -> int:
        return len(self.comments)


@runtime_checkable
class YouTubePort(Protocol):
    """Everything the application needs from the YouTube Data API."""

    def video(self, video_id: str) -> dict[str, Any]:
        """Metadata for one video.

        Raises CommentsDisabledError, QuotaExceededError or YouTubeAPIError
        from the domain hierarchy. The adapter translates HTTP into those; no
        caller above this line sees a status code.
        """
        ...

    def comment_threads(
        self,
        video_id: str,
        *,
        order: str = "relevance",
        maximum: int = 100,
    ) -> CommentPage:
        """Top-level comments in the requested ordering.

        ``order`` is "relevance" or "time". Both orderings are fetched and
        merged by the application, because neither alone is complete: the
        relevance ordering hides recent comments and the time ordering hides
        the ones the room actually responded to.
        """
        ...

    def replies(
        self,
        parent_comment_id: str,
        *,
        maximum: int = 100,
    ) -> CommentPage:
        """Replies under one top-level comment, oldest first.

        Oldest-first is the API's own ordering and is preserved rather than
        corrected here: on a busy thread the first page is the oldest replies,
        and the application ranks the fetched window itself.
        """
        ...

    def channel_id_for_handle(self, handle: str) -> str:
        """Resolve an @handle to a channel ID.

        Raises ConfigurationError when no channel matches, rather than
        returning an empty string: a run that proceeds with no identity would
        silently treat every reply as somebody else's.
        """
        ...

    @property
    def api_operations_used(self) -> int:
        """Logical YouTube Data API operations issued so far.

        One adapter ``get`` call is one operation, whether the HTTP transport
        sends it once or retries it. This is a logical-operation metric, not a
        physical-network-attempt counter.
        """
        ...


@runtime_checkable
class SupportsCancellation(Protocol):
    """Something a long retrieval can consult between pages."""

    def cancelled(self) -> bool: ...
