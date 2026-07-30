"""Private desktop settings and engagement-history locations."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from ...infrastructure.sqlite_history import SqliteHistoryStore
from ...infrastructure.user_state import default_state_directory
from ..gui.options import PacketOptionsModel

LOGGER = logging.getLogger("ytcomment")


def private_state_directory(configuration) -> Path:
    configured = str(configuration.get("state_directory", "") or "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else default_state_directory()
    )


def legacy_state_path(configuration, filename: str) -> Path:
    return (
        Path(configuration.get("output_directory", "output")).expanduser().parent
        / filename
    )


def window_settings_path(configuration) -> Path:
    return private_state_directory(configuration) / "window_settings.json"


def load_window_settings(
    path: Path,
    *,
    legacy: Path | None = None,
) -> dict:
    try:
        source = path
        if not source.is_file() and legacy is not None and legacy.is_file():
            source = legacy
        payload = json.loads(source.read_text(encoding="utf-8"))
        if source != path and isinstance(payload, dict):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def save_window_settings(path: Path, options) -> None:
    """Remember settings without making window shutdown fallible."""

    if not isinstance(options, PacketOptionsModel):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(options.to_settings(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as failure:
        LOGGER.warning("could not save window settings: %s", failure)


def history_store(configuration) -> SqliteHistoryStore:
    path = private_state_directory(configuration) / "engagement_history.sqlite3"
    legacy = legacy_state_path(configuration, "engagement_history.sqlite3")
    if not path.exists() and legacy.is_file() and legacy != path:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy, path)
        except OSError:
            # The original stays untouched; opening the target later reports
            # the ordinary visible storage error.
            pass
    return SqliteHistoryStore(path)
