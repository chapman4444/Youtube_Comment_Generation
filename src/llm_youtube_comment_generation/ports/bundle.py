"""Typed collection of the adapters used by a normal application run."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from .clipboard import ClipboardPort
from .events import EventSink
from .transcripts import TranscriptPort
from .youtube import YouTubePort


@dataclass
class PortBundle(Mapping[str, Any]):
    """Typed attributes with mapping compatibility for existing use cases."""

    youtube: YouTubePort
    transcripts: TranscriptPort
    clipboard: ClipboardPort
    events: EventSink
    extras: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        if key in {"youtube", "transcripts", "clipboard", "events"}:
            return getattr(self, key)
        return self.extras[key]

    def __iter__(self) -> Iterator[str]:
        yield from ("youtube", "transcripts", "clipboard", "events")
        yield from self.extras

    def __len__(self) -> int:
        return 4 + len(self.extras)
