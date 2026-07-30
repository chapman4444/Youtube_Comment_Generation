"""Where a run's output files go.

The staging-and-commit shape is not incidental. A run writes several files
that only make sense together — the packet, the report, the CSV, the replies
— and a half-written set is worse than none, because the operator cannot tell
which half is stale. So a run stages everything and publishes a verifiable
completion record only after the set is ready.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ArtifactStore(Protocol):
    def stage(self, name: str, content: str) -> None:
        """Hold a file for this run without publishing it."""
        ...

    def commit(self) -> tuple[str, ...]:
        """Publish the staged set and its completion record.

        A reader must not treat the set as completed until its completion
        record exists and validates. On a caught failure, restore the previous
        output set or preserve and report the recovery backup.
        """
        ...

    def rollback(self) -> None:
        """Discard everything staged, leaving the previous set untouched."""
        ...

    def read(self, name: str) -> str:
        """Read a previously committed file, or raise if it is absent."""
        ...

    def committed_names(self) -> tuple[str, ...]:
        """Names currently published for this run."""
        ...
