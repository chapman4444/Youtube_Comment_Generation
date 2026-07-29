"""Time.

A port because "7 days back" is a rule the domain has to compute and a test
has to pin. The legacy version called datetime.now() inside the parser, which
made the rule untestable without freezing time globally.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class ClockPort(Protocol):
    def now(self) -> datetime:
        """The current moment, always timezone-aware and always UTC.

        Naive datetimes are barred at the port rather than defended against
        everywhere downstream: a naive value compared against an aware one
        raises, and that comparison is exactly what the reply cutoff does.
        """
        ...
