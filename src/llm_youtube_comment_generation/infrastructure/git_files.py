"""Read the file set Git would publish, with a non-Git fallback."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    """Run Git with repository trust scoped to this one subprocess."""

    return subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={root.as_posix()}",
            "-C",
            str(root),
            *arguments,
        ],
        check=False,
        capture_output=True,
    )


def tracked_files(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    discovered = _git(root, "rev-parse", "--show-toplevel")
    try:
        top_level = Path(discovered.stdout.decode("utf-8").strip()).resolve()
    except (OSError, UnicodeError):
        top_level = Path()
    if discovered.returncode != 0 or top_level != root:
        return _files_below(root)

    completed = _git(root, "ls-files", "-z")
    if completed.returncode != 0:
        return _files_below(root)
    return tuple(
        item.decode("utf-8", errors="replace")
        for item in completed.stdout.split(b"\0")
        if item
    )


def _files_below(root: Path) -> tuple[str, ...]:
    return tuple(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    )
