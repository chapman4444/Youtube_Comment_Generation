"""Console-free GUI startup with visible initialization failures."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Callable, Sequence


def startup_log_path() -> Path:
    base = Path(
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("TEMP")
        or Path.cwd()
    )
    return base / "YouTubeCommentGeneration" / "gui_startup.log"


def write_startup_log(text: str) -> Path:
    path = startup_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text[-65_536:], encoding="utf-8", newline="\n")
    return path


def show_error(message: str) -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showerror("YouTube packet builder", message, parent=root)
    finally:
        root.destroy()


def run(
    argv: Sequence[str] | None = None,
    *,
    entrypoint: Callable[[Sequence[str] | None], int] | None = None,
    notifier: Callable[[str], None] = show_error,
) -> int:
    if entrypoint is None:
        from ..cli.main import main

        entrypoint = main

    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        result = int(entrypoint(arguments))
    except BaseException:
        detail = traceback.format_exc()
        try:
            log = write_startup_log(detail)
            suffix = f"\n\nDetails were saved to:\n{log}"
        except OSError:
            suffix = ""
        notifier(
            "The window could not start because of an unexpected error."
            f"{suffix}"
        )
        return 1

    if result == 3:
        notifier(
            "The window could not start because its configuration is "
            "incomplete. Run doctor.bat for the exact problem."
        )
    elif result == 5:
        notifier(
            "No transcript was available. Reopen the window and choose how "
            "missing transcripts should be handled in Advanced."
        )
    elif result:
        notifier(
            f"The window closed during startup with error code {result}. "
            "Run doctor.bat for details."
        )
    return result


if __name__ == "__main__":
    raise SystemExit(run())
