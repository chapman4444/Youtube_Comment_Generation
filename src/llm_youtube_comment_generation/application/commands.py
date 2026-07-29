"""Typed commands. Both interfaces create these; neither implements the work.

A command is what the operator asked for, validated. The CLI parses arguments
into one of these and the GUI will build the same object from its form, which
is what makes CLI/GUI parity structural rather than a promise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    include_replies: bool = False
    transcript_languages: tuple[str, ...] = ("en",)
    dry_run: bool = False

    video_id: str = field(init=False, default="")

    def __post_init__(self) -> None:
        object.__setattr__(self, "video_id", extract_video_id(self.video))
