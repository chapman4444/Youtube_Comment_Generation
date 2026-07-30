"""Read the file set Git would publish, with a non-Git fallback."""

from __future__ import annotations

import subprocess
from pathlib import Path


def tracked_files(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    discovered = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
    )
    try:
        top_level = Path(discovered.stdout.decode("utf-8").strip()).resolve()
    except (OSError, UnicodeError):
        top_level = Path()
    if discovered.returncode != 0 or top_level != root:
        return _files_below(root)

    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=False,
        capture_output=True,
    )
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
