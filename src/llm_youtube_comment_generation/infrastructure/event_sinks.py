"""Where progress events go.

Three sinks, one interface. The terminal one prints prose, the JSONL one
emits machine-readable lines for a caller driving this from a script, and the
null one discards. None of them may raise: a closed pipe must not take down
the run that was reporting to it.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from ..ports.events import EventKind, ProgressEvent


class NullEventSink:
    def emit(self, event: ProgressEvent) -> None:
        return None


class TextEventSink:
    """Human-readable progress, for a terminal.

    This is the part the operator watches to know the run is alive. The
    legacy application lost it once and the regression was immediately
    noticeable: a long retrieval with no output is indistinguishable from a
    hang.
    """

    def __init__(self, stream: TextIO | None = None, verbose: bool = False) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._verbose = verbose

    def emit(self, event: ProgressEvent) -> None:
        try:
            line = self._render(event)
            if line:
                print(line, file=self._stream, flush=True)
        except Exception:                   # noqa: BLE001 - a sink never raises
            return None

    def _render(self, event: ProgressEvent) -> str:
        if event.kind is EventKind.PROGRESS and not self._verbose:
            return ""
        marker = {
            EventKind.STARTED: "->",
            EventKind.STEP: "  ",
            EventKind.PROGRESS: "  ",
            EventKind.WARNING: "!!",
            EventKind.FINISHED: "ok",
            EventKind.CANCELLED: "--",
            EventKind.FAILED: "xx",
        }.get(event.kind, "  ")

        text = event.message or event.step or event.kind.value
        fraction = event.fraction
        if fraction is not None:
            text = f"{text}  {event.current:,}/{event.total:,} ({fraction:.0%})"
        elif event.current is not None:
            # Unknown total is a real answer; do not invent a denominator.
            text = f"{text}  {event.current:,}"
        return f"{marker} {text}"


class JsonlEventSink:
    """One JSON object per line, for a caller driving this from a script."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    def emit(self, event: ProgressEvent) -> None:
        try:
            payload: dict[str, Any] = {
                "kind": event.kind.value,
                "step": event.step,
                "message": event.message,
            }
            if event.current is not None:
                payload["current"] = event.current
            if event.total is not None:
                payload["total"] = event.total
            if event.data:
                payload["data"] = event.data
            print(json.dumps(payload, ensure_ascii=False),
                  file=self._stream, flush=True)
        except Exception:                   # noqa: BLE001 - a sink never raises
            return None


def make_event_sink(mode: str, stream: TextIO | None = None, verbose: bool = False):
    """Resolve --progress auto|jsonl|none into a sink."""

    if mode == "none":
        return NullEventSink()
    if mode == "jsonl":
        return JsonlEventSink(stream)
    return TextEventSink(stream, verbose=verbose)
