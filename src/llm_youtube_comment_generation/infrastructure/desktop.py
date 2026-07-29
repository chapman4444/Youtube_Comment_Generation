"""Opening a file in whatever the operator reads files with.

This is the only place in the application that hands something to the desktop,
and it exists because the window's "Open replies" button was wired to a
callable that did nothing. The button was enabled, it was the primary action in
four separate phases, and pressing it at the end of a finished run produced no
window, no error and no log line.

Three rules, each of which the legacy application broke at least once.

**It never raises.** By the time this is called the replies are already on
disk. A file manager that will not start is an inconvenience; an exception
that unwinds the last step of a saved run looks like the run failed. Every
failure comes back as a sentence for the operator to read instead.

**It never blocks.** ``subprocess.run`` on an editor waits for the editor to
close, which would freeze the Tk event loop until the operator quit their
text editor. ``Popen`` and return.

**It says what it did.** An empty return means the file was handed to the
desktop, which is not the same as a window having appeared — nothing can
promise that. Anything else is the reason it did not get that far.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def open_path(path: str | Path, *, editor: str = "") -> str:
    """Hand a file to the desktop. Returns "" on success, else the reason.

    ``editor`` is the operator's ``editor`` setting. It was in the
    configuration from the first day and nothing read it, so setting it did
    nothing at all.
    """

    target = Path(path).expanduser()
    if not target.exists():
        return (
            f"Nothing to open: {target} does not exist. Replies are written "
            "when the first one is accepted."
        )

    try:
        if editor:
            # Popen, not run: run() waits for the editor to exit, which would
            # freeze the window until the operator closed their editor.
            subprocess.Popen([editor, str(target)])
            return ""
        if hasattr(os, "startfile"):        # Windows
            os.startfile(str(target))       # noqa: S606 - the operator's own file
            return ""
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(target)])
        return ""
    except (OSError, ValueError) as failure:
        LOGGER.warning("could not open %s: %s", target, failure)

    # Last resort. A browser renders markdown as text, which is worse than an
    # editor and much better than nothing.
    try:
        if webbrowser.open(target.as_uri()):
            return ""
    except (OSError, ValueError) as failure:
        LOGGER.warning("could not open %s in a browser: %s", target, failure)

    return (
        f"Could not open {target}. It is written and safe; open it yourself."
    )
