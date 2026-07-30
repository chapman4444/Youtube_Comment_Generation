"""Private application-state locations that cannot be committed by accident."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

APPLICATION_DIRECTORY = "YouTubeCommentGeneration"


def default_state_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    environment = os.environ if environment is None else environment
    if environment.get("LOCALAPPDATA"):
        return Path(environment["LOCALAPPDATA"]) / APPLICATION_DIRECTORY
    if environment.get("XDG_STATE_HOME"):
        return Path(environment["XDG_STATE_HOME"]) / APPLICATION_DIRECTORY
    if environment.get("APPDATA"):
        return Path(environment["APPDATA"]) / APPLICATION_DIRECTORY
    return Path.home() / ".local" / "state" / APPLICATION_DIRECTORY
