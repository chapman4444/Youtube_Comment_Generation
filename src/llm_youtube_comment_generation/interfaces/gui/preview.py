"""A window to press the buttons on, with no queue and no network.

The window only opens when somebody has replied to one of the operator's own
comments and has not heard back. That is the right rule and it is also why he
had never seen the window: it needs a video he commented on, a reply to that
comment, and no answer from him yet. Two runs on a video he had never commented
on both ended with a correct refusal and no window.

So: the same window, the same controller, the same state machine, the same
prompt templates, driven by a session made up here. Nothing is fetched and
nothing is written -- the artifact store is in memory -- so this costs no quota
and leaves no run directory that looks like work.

The sample text says what it is in its own words. A preview that looked like
real evidence would be the same mistake this project keeps refusing to make
elsewhere.
"""

from __future__ import annotations

from ...application.guided_session import GuidedSession
from ...domain.candidates import build_reply_candidates
from ...domain.threads import OwnerThread
from ...infrastructure.memory_artifacts import MemoryArtifactStore

#: Which templates a caller must supply. Named here, loaded by the caller: the
#: gui package does not read files, and a window that knew a filename would be
#: a second place the layout is defined. tests/gui/test_gui_boundaries.py
#: enforces it, and caught this module getting it wrong.
TEMPLATE_NAMES = ("reply_workflow", "reply_final_check")

TITLE = "YouTube reply packets  —  PREVIEW (nothing is fetched or saved)"

OWNER_CHANNEL = "UC" + "0" * 22
OWNER_HANDLE = "@you"

VIDEO = {
    "video_id": "PREVIEW0000",
    "title": "Sample video — this is a preview, not a real run",
    "channel_title": "Sample channel",
    "description": "Nothing here was fetched from YouTube.",
}

OWNER_COMMENT = {
    "comment_id": "preview-owner",
    "author": OWNER_HANDLE,
    "author_channel_id": OWNER_CHANNEL,
    "text": ("This is a made-up comment of yours, so the window has a thread "
             "to work through. Nothing here came from YouTube."),
    "like_count": 12,
    "published_at": "2026-07-01T09:00:00Z",
    "updated_at": "2026-07-01T09:00:00Z",
}

REPLIES = [
    {
        "comment_id": "preview-reply-1",
        "author": "@sample_person_one",
        "author_channel_id": "UC" + "1" * 22,
        "text": ("Sample reply one. Disagrees with you and gives a reason, "
                 "which is the case the packet is built for."),
        "like_count": 9,
        "published_at": "2026-07-02T10:00:00Z",
        "updated_at": "2026-07-02T10:00:00Z",
    },
    {
        "comment_id": "preview-reply-2",
        "author": "@sample_person_two",
        "author_channel_id": "UC" + "2" * 22,
        "text": ("Sample reply two. Asks you a direct question, so you can "
                 "see what a second person in the queue looks like."),
        "like_count": 3,
        "published_at": "2026-07-02T11:00:00Z",
        "updated_at": "2026-07-02T11:00:00Z",
    },
]


def build_session(templates: dict[str, str], clipboard=None) -> GuidedSession:
    """A guided session over invented people. Touches nothing real.

    ``templates`` arrives from the caller for the same reason it does in the
    real path: reading them here would put the filesystem, and the output
    layout, inside the window's own package.
    """

    return GuidedSession(
        targets=build_reply_candidates(
            OWNER_CHANNEL, OWNER_HANDLE, REPLIES, OWNER_COMMENT["comment_id"]
        ),
        threads={
            OWNER_COMMENT["comment_id"]: OwnerThread(
                comment=OWNER_COMMENT, replies=list(REPLIES)
            )
        },
        owner_channel_id=OWNER_CHANNEL,
        video=dict(VIDEO),
        transcript_text="",
        templates=dict(templates),
        # In memory on purpose: a preview that wrote into output/ would leave
        # run directories that look like work the operator did.
        artifacts=MemoryArtifactStore(),
        clipboard=clipboard,
    )
