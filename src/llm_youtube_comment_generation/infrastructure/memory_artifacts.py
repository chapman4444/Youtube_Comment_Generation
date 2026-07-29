"""An artifact store that publishes nothing to disk.

Same staging-and-commit contract as the filesystem store, held in memory. It
exists for `ytcomment gui --preview`, where the point is to produce everything
a real run produces and persist none of it: a preview that wrote into
`output/` would leave run directories that look like work the operator did.

It is production code rather than a test fake because an interface may not
import from `tests/`, and because "produce it, do not keep it" is a real thing
to want.
"""

from __future__ import annotations


class MemoryArtifactStore:
    """Implements ArtifactStore without touching the filesystem."""

    #: Named so anything reading `.root` for a path gets something honest
    #: rather than a directory that does not exist.
    root = "(nothing is written in preview)"

    def __init__(self) -> None:
        self._staged: dict[str, str] = {}
        self._committed: dict[str, str] = {}

    def stage(self, name: str, content: str) -> None:
        self._staged[name] = content

    def commit(self) -> tuple[str, ...]:
        self._committed.update(self._staged)
        published = tuple(sorted(self._staged))
        self._staged.clear()
        return published

    def rollback(self) -> None:
        self._staged.clear()

    def read(self, name: str) -> str:
        if name not in self._committed:
            raise KeyError(f"{name} has not been committed")
        return self._committed[name]

    def committed_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._committed))
