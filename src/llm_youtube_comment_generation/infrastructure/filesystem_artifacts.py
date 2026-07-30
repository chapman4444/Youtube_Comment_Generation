"""Staged, atomic artifact commit on a real filesystem.

A run writes several files that only make sense together. A half-written set
is worse than none, because the operator cannot tell which half is stale — so
everything is staged beside the destination and moved into place at the end,
and a failure restores what was there before.

New run roots are reserved by atomic directory creation, so independent
processes cannot acquire the same video-and-timestamp destination.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from ..domain.errors import ConfigurationError

# Only these are ours to replace. A directory holding anything else is the
# operator's, and refusing to touch it is cheaper than explaining where his
# files went.
OWNED_SUFFIXES = (".md", ".json", ".txt", ".csv")
COMPLETION_MARKER = ".artifacts-complete.json"


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
    """Atomically reserve a directory for one new run.

    Two runs of the same video in the same second get distinct roots rather
    than one overwriting the other, because the second run is usually the one
    made after noticing something wrong with the first. ``mkdir`` is the
    inter-process ownership boundary; an existence check is not.
    """

    base.mkdir(parents=True, exist_ok=True)
    for suffix in range(1, 1000):
        ending = "" if suffix == 1 else f"_{suffix}"
        candidate = base / f"{video_id}_{stamp}{ending}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
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
        if not self._root.exists():
            return self._commit_new_root()

        backup = self._back_up_existing()
        written: list[Path] = []
        restored = False
        try:
            marker = self._root / COMPLETION_MARKER
            try:
                marker.unlink()
            except FileNotFoundError:
                pass
            for name, content in sorted(self._staged.items()):
                target = self._root / name
                atomic_write(target, content)
                written.append(target)
            atomic_write(marker, self._completion_record())
        except BaseException as commit_error:
            # Undo this attempt, then restore what was there before it.
            for path in written:
                try:
                    path.unlink()
                except OSError:
                    pass
            try:
                self._restore(backup)
                restored = True
            except BaseException as restore_error:
                location = str(backup) if backup else "(no backup was created)"
                raise ConfigurationError(
                    "Artifact publication failed and the previous files could "
                    f"not be restored. The recovery backup was preserved at "
                    f"{location}. Publication error: {commit_error}. "
                    f"Restoration error: {restore_error}."
                ) from restore_error
            raise
        finally:
            if backup and backup.exists() and restored:
                shutil.rmtree(backup, ignore_errors=True)

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

    def _commit_new_root(self) -> tuple[str, ...]:
        self._root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(
            dir=str(self._root.parent),
            prefix=f".{self._root.name}.publishing.",
        ))
        try:
            for name, content in sorted(self._staged.items()):
                atomic_write(staging / name, content)
            atomic_write(staging / COMPLETION_MARKER, self._completion_record())
            os.replace(staging, self._root)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        published = tuple(sorted(self._staged))
        self._committed = list(published)
        self._staged.clear()
        return published

    def _completion_record(self) -> str:
        files = {
            name: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for name, content in sorted(self._staged.items())
        }
        return json.dumps(
            {"version": 1, "files": files},
            indent=2,
            ensure_ascii=False,
        ) + "\n"

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
                    if entry.is_file() and (
                        entry.name in self._staged
                        or entry.name == COMPLETION_MARKER
                    )]
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
