"""Typed commands. Both interfaces create these; neither implements the work.

A command is what the operator asked for, validated. The CLI parses arguments
into one of these and the GUI will build the same object from its form, which
is what makes CLI/GUI parity structural rather than a promise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.errors import ConfigurationError
from ..domain.ids import extract_video_id


@dataclass(frozen=True)
class InspectVideoCommand:
    """Retrieve a video and report what is actually there.

    Validation happens in __post_init__ so an invalid command cannot exist.
    A handler that has to re-check its own input is a handler that will
    eventually forget.
    """

    video: str
    max_comments: int = 500
    max_relevance_comments: int | None = None
    max_recent_comments: int | None = None
    max_reply_threads: int = 20
    max_replies_per_thread: int = 100
    include_replies: bool = False
    transcript_languages: tuple[str, ...] = ("en",)
    dry_run: bool = False

    video_id: str = field(init=False, default="")

    def __post_init__(self) -> None:
        object.__setattr__(self, "video_id", extract_video_id(self.video))
        if self.max_comments < 1:
            raise ConfigurationError("max_comments must be at least 1.")
        if self.max_relevance_comments is not None and \
                self.max_relevance_comments < 1:
            raise ConfigurationError(
                "max_relevance_comments must be at least 1."
            )
        if self.max_recent_comments is not None and \
                self.max_recent_comments < 1:
            raise ConfigurationError(
                "max_recent_comments must be at least 1."
            )
        if self.max_reply_threads < 1:
            raise ConfigurationError("max_reply_threads must be at least 1.")
        if self.max_replies_per_thread < 1:
            raise ConfigurationError(
                "max_replies_per_thread must be at least 1."
            )
