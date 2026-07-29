"""One Tk interpreter for every window test in this directory.

Interpreter creation is the flaky part on this machine — a spurious TclError
roughly once per suite run — so the rule has always been to share one. It was
one per *file* while there was one window; a second window meant a second
file, then a third for its dialog, and three `tk.Tk()` roots in one process
produced exactly what the rule exists to prevent: a suite that passed on the
first run and failed on the second with a dozen TclErrors, which the
two-consecutive-runs gate caught and a single run would not have.

One root for the session, and every test takes a Toplevel from it.
"""

from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture(scope="session")
def tk_root():
    """The only interpreter these tests ever create."""

    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:         # pragma: no cover - already gone
        pass
