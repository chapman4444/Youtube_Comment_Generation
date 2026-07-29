"""What the application needs from the outside world.

A port describes the need; the adapter absorbs the API. These are written
after the domain deliberately, so their shape follows real use rather than
the shape of the YouTube Data API — the specific drift Phase 2 warns about.

Every port is a ``typing.Protocol``. Nothing here imports an HTTP client, a
filesystem, or a GUI toolkit: a port is an interface, and the moment one of
them needs `requests` to be *defined*, the boundary has already failed.
"""

from .artifacts import ArtifactStore
from .clipboard import ClipboardPort
from .clock import ClockPort
from .events import EventSink, ProgressEvent, EventKind
from .history import HistoryStore
from .settings import SettingsStore
from .transcripts import TranscriptPort
from .youtube import CommentPage, YouTubePort

__all__ = [
    "ArtifactStore",
    "ClipboardPort",
    "ClockPort",
    "CommentPage",
    "EventKind",
    "EventSink",
    "HistoryStore",
    "ProgressEvent",
    "SettingsStore",
    "TranscriptPort",
    "YouTubePort",
]
