"""Progress and operational events.

Structured events, not an event-sourced architecture — 08_ANTI_PATTERNS.md
rules that out explicitly. The application needs to say what it is doing, and
three very different consumers need to hear it: a terminal printing lines, a
window driving a progress bar, and a test asserting that a step happened.

The legacy version passed a `say` callable around, which meant progress was
formatted at the call site and a test could only assert on English. An event
carries the facts and each consumer decides how to render them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class EventKind(str, Enum):
    STARTED = "started"
    STEP = "step"
    PROGRESS = "progress"
    WARNING = "warning"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class ProgressEvent:
    """One thing that happened, in facts rather than prose.

    ``message`` is for humans and must never be parsed. Anything a caller
    needs to branch on belongs in ``kind`` or ``data``.
    """

    kind: EventKind
    step: str = ""
    message: str = ""
    current: int | None = None
    total: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def fraction(self) -> float | None:
        """Completed share, or None when the total is unknown.

        Unknown is a real answer. A progress bar that invents a denominator
        so it can show a percentage is lying about how much is left.
        """

        if not self.total or self.current is None:
            return None
        return max(0.0, min(1.0, self.current / self.total))


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event: ProgressEvent) -> None:
        """Record or display one event.

        Must not raise. A sink that fails — a closed pipe, a destroyed
        window — must not take down the run that was reporting to it.
        """
        ...
