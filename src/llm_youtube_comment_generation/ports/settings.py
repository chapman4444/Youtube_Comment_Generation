"""Remembered choices between runs.

Settings are tolerant where the command line is strict. A stale register key
in a saved settings file must not stop the application opening — the operator
would have no way to fix it — so unknown entries are dropped with a log line.
The same value typed as an argument is refused outright, because a typed
argument is a request and quietly building something else is worse.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SettingsStore(Protocol):
    def load(self) -> dict[str, Any]:
        """Saved settings, or an empty mapping.

        Never raises. Unreadable settings are worth a log line and a fresh
        start, not a refusal to launch.
        """
        ...

    def save(self, values: dict[str, Any]) -> None:
        """Persist settings.

        Implementations must refuse to write a credential. The API key is
        deliberately not a remembered field: it lives in the environment, and
        a settings file is a thing operators paste into bug reports.
        """
        ...
