"""Staged, atomic artifact commit on a real filesystem.

A run writes several files that only make sense together. A half-written set
is worse than none, because the operator cannot tell which half is stale — so
everything is staged beside the destination and moved into place at the end,
and a failure restores what was there before.

The run root is collision-safe: a second run of the same video on the same
day does not silently overwrite the first.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from ..domain.errors import ConfigurationError

# Only these are ours to replace. A directory holding anything else is the
# operator's, and refusing to touch it is cheaper than explaining where his
# files went.
OWNED_SUFFIXES = (".md", ".json", ".txt", ".csv")


def atomic_write(path: Path, text: str) -> None:
    """Write via a temporary file in the same directory, then replace.

    Same directory because os.replace is only atomic within a filesystem, and
    the system temp directory is frequently a different one.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".partial"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        # No half-written file survives a failure, including a KeyboardInterrupt.
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def unique_run_root(base: Path, video_id: str, stamp: str) -> Path:
    """A directory for this run that cannot collide with another.

    Two runs of the same video in the same second get distinct roots rather
    than one overwriting the other, because the second run is usually the one
    made after noticing something wrong with the first.
    """

    candidate = base / f"{video_id}_{stamp}"
    if not candidate.exists():
        return candidate
    for suffix in range(2, 1000):
        alternative = base / f"{video_id}_{stamp}_{suffix}"
        if not alternative.exists():
            return alternative
    raise ConfigurationError(f"Could not find a free run directory under {base}")


class FilesystemArtifactStore:
    """Implements ArtifactStore against a directory."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._staged: dict[str, str] = {}
        self._committed: list[str] = []

    @property
    def root(self) -> Path:
        return self._root

    def stage(self, name: str, content: str) -> None:
        if Path(name).name != name:
            raise ConfigurationError(f"artifact names must be plain: {name!r}")
        self._staged[name] = content

    def commit(self) -> tuple[str, ...]:
        if not self._staged:
            return ()

        self._refuse_foreign_directory()
        backup = self._back_up_existing()
        written: list[Path] = []
        try:
            for name, content in sorted(self._staged.items()):
                target = self._root / name
                atomic_write(target, content)
                written.append(target)
        except BaseException:
            # Undo this attempt, then restore what was there before it.
            for path in written:
                try:
                    path.unlink()
                except OSError:
                    pass
            self._restore(backup)
            raise
        finally:
            if backup and backup.exists():
                shutil.rmtree(backup, ignore_errors=True)

        published = tuple(sorted(self._staged))
        self._committed = list(published)
        self._staged.clear()
        return published

    def rollback(self) -> None:
        self._staged.clear()

    def read(self, name: str) -> str:
        return (self._root / name).read_text(encoding="utf-8")

    def committed_names(self) -> tuple[str, ...]:
        return tuple(self._committed)

    # -- internals -------------------------------------------------------

    def _refuse_foreign_directory(self) -> None:
        if not self._root.exists():
            return
        foreign = [
            entry.name for entry in self._root.iterdir()
            if entry.is_file() and entry.suffix not in OWNED_SUFFIXES
        ]
        if foreign:
            raise ConfigurationError(
                f"{self._root} holds files this tool did not write "
                f"({', '.join(sorted(foreign)[:5])}). Choose an empty "
                "directory rather than risk overwriting them."
            )

    def _back_up_existing(self) -> Path | None:
        if not self._root.exists():
            return None
        existing = [entry for entry in self._root.iterdir()
                    if entry.is_file() and entry.name in self._staged]
        if not existing:
            return None
        backup = Path(tempfile.mkdtemp(dir=str(self._root.parent),
                                       prefix=".rollback."))
        for entry in existing:
            shutil.copy2(entry, backup / entry.name)
        return backup

    def _restore(self, backup: Path | None) -> None:
        if backup is None or not backup.exists():
            return
        for entry in backup.iterdir():
            shutil.copy2(entry, self._root / entry.name)
