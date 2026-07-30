"""Private application state follows the operating system."""

from __future__ import annotations

from pathlib import Path

from llm_youtube_comment_generation.infrastructure.user_state import (
    APPLICATION_DIRECTORY,
    default_state_directory,
)


def test_windows_state_uses_local_app_data():
    path = default_state_directory({
        "LOCALAPPDATA": "C:/Users/<user>/AppData/Local",
    })

    assert path == Path("C:/Users/<user>/AppData/Local") / \
        APPLICATION_DIRECTORY


def test_xdg_state_is_used_when_local_app_data_is_absent():
    path = default_state_directory({"XDG_STATE_HOME": "/private/state"})

    assert path == Path("/private/state") / APPLICATION_DIRECTORY
