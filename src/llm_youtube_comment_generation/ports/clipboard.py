"""The system clipboard.

A port because the guided workflow both writes the packet to the clipboard
and reads the answer back from it, which means a stray copy can feed the
packet to itself. Behind an interface that round trip is testable without a
display, and the fake makes the collision reproducible.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ClipboardPort(Protocol):
    def read(self) -> str:
        """Current clipboard text, or "" when it holds nothing readable."""
        ...

    def write(self, text: str) -> None:
        """Replace the clipboard contents."""
        ...
