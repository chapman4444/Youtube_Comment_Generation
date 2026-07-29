"""Shared harness machinery.

Separate from conftest.py so the guards' negative proofs can import and drive
the same code the fixtures use. A proof that exercised a reimplementation
would prove nothing about the guard that actually runs.
"""

from __future__ import annotations

import os
import pathlib
import socket

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Captured before any fixture patches them, so a test can assert that a guard
# genuinely stepped aside rather than merely that some callable exists.
REAL_SOCKET = socket.socket
REAL_CREATE_CONNECTION = socket.create_connection


class HarnessViolation(RuntimeError):
    """A test tried to do something the harness forbids outright."""


def protected_state_paths() -> list[pathlib.Path]:
    """Files no test may alter, whatever else it does.

    posted_history.json is the operator's only real measurement data. It is
    deliberately not gitignored in the legacy project and it cannot be
    regenerated if a test truncates it.
    """

    override = os.environ.get("LLM_YT_PROTECTED_STATE", "")
    if override:
        return [pathlib.Path(part) for part in override.split(os.pathsep) if part]

    # The legacy application is still the behavioural reference and still holds
    # the live history, so it is guarded from here too: the new suite must not
    # be the thing that destroys it.
    return [
        REPO_ROOT / "posted_history.json",
        REPO_ROOT.parent / "Comment_Generation_Claude02" / "posted_history.json",
    ]


def snapshot_protected_state() -> dict[pathlib.Path, bytes | None]:
    return {
        path: (path.read_bytes() if path.exists() else None)
        for path in protected_state_paths()
    }


def compare_protected_state(
    before: dict[pathlib.Path, bytes | None],
    after: dict[pathlib.Path, bytes | None],
) -> list[str]:
    """Return one message per file that changed. Empty means untouched.

    Split out of the fixture so the negative proof can drive it against a
    temporary file. Proving the guard by actually corrupting the production
    history would be the accident the guard exists to prevent.
    """

    changed = []
    for path, original in before.items():
        current = after.get(path)
        if current == original:
            continue
        if original is None:
            changed.append(f"a test created protected state at {path}")
        elif current is None:
            changed.append(f"a test deleted protected state at {path}")
        else:
            changed.append(
                f"a test wrote to protected state at {path} "
                f"({len(original):,} bytes -> {len(current):,} bytes)"
            )
    return changed
