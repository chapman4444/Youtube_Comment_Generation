"""The real clock."""

from __future__ import annotations

from datetime import datetime, timezone


class SystemClock:
    """Implements ClockPort. Always UTC, always aware."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)
