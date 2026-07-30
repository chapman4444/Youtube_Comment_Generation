"""What the window remembers between runs, and where it keeps it.

Untested until now, and the failure mode is silent: a settings file that never
loads looks exactly like a window that forgot, and one that never saves looks
the same. Both would cost the operator every register and dial on every run.

Where it is kept matters as much as whether it works. A settings file carries
a handle and an output path, so it lives beside the output rather than
anywhere a commit could pick it up.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import llm_youtube_comment_generation.interfaces.cli.main  # noqa: F401

CLI = sys.modules["llm_youtube_comment_generation.interfaces.cli.main"]

from llm_youtube_comment_generation.application.configuration import resolve
from llm_youtube_comment_generation.interfaces.gui.options import (
    PacketOptionsModel,
)


def configuration(output_directory):
    return resolve(flags={
        "output_directory": str(output_directory),
        "state_directory": str(Path(output_directory).parent / "private-state"),
    })


# -- where it lives --------------------------------------------------------


def test_the_settings_file_is_not_in_the_repository(tmp_path):
    """It carries a handle and an output path. That is personal data, and
    this repository is meant to be publishable."""

    path = CLI._window_settings_path(configuration(tmp_path / "output"))
    project = Path(CLI.__file__).resolve().parents[4]

    assert project not in path.parents, f"{path} is inside the project"


def test_it_sits_in_the_private_state_directory(tmp_path):
    """It cannot be swept into a project or generated review package."""

    path = CLI._window_settings_path(configuration(tmp_path / "output"))

    assert path.name.endswith(".json")
    assert path.parent == tmp_path / "private-state"


def test_legacy_settings_are_copied_to_private_state_on_first_read(tmp_path):
    legacy = tmp_path / "window_settings.json"
    legacy.write_text('{"my_handle": "@legacy"}', encoding="utf-8")
    private = tmp_path / "private" / "window_settings.json"

    loaded = CLI._load_window_settings(private, legacy=legacy)

    assert loaded["my_handle"] == "@legacy"
    assert json.loads(private.read_text(encoding="utf-8"))["my_handle"] == \
        "@legacy"
    assert legacy.is_file()


# -- reading ---------------------------------------------------------------


def test_no_settings_file_is_not_an_error(tmp_path):
    assert CLI._load_window_settings(tmp_path / "absent.json") == {}


def test_a_malformed_settings_file_does_not_stop_the_window_opening(tmp_path):
    """The worst a bad settings file may cost is that nothing was
    remembered."""

    broken = tmp_path / "settings.json"
    broken.write_text("{not json at all", encoding="utf-8")

    assert CLI._load_window_settings(broken) == {}


def test_what_was_written_is_what_comes_back(tmp_path):
    path = tmp_path / "settings.json"
    original = PacketOptionsModel(
        my_handle="@someone", packet_characters=300_000,
        comment_variations=("short_hook",), dials={"grounding": "summary"},
        languages="en,de",
    )

    CLI._save_window_settings(path, original)
    restored = PacketOptionsModel.from_settings(
        CLI._load_window_settings(path))

    assert restored.to_settings() == original.to_settings()


# -- writing ---------------------------------------------------------------


def test_a_directory_that_does_not_exist_yet_is_made(tmp_path):
    path = tmp_path / "nested" / "deeper" / "settings.json"

    CLI._save_window_settings(path, PacketOptionsModel(my_handle="@someone"))

    assert json.loads(path.read_text(encoding="utf-8"))["my_handle"] == \
        "@someone"


def test_closing_a_window_never_fails_over_a_read_only_directory(tmp_path):
    """Closing a window is not the place to discover a permissions problem,
    and there is nothing useful the operator could do about it there."""

    impossible = tmp_path / "a-file-not-a-directory"
    impossible.write_text("x", encoding="utf-8")

    CLI._save_window_settings(impossible / "settings.json",
                              PacketOptionsModel())


def test_something_that_is_not_an_options_model_is_ignored(tmp_path):
    """The window is asked for its options after it closes; a window that
    died holding nothing must not take the settings file with it."""

    path = tmp_path / "settings.json"
    CLI._save_window_settings(path, PacketOptionsModel(my_handle="@keep"))

    CLI._save_window_settings(path, None)

    assert json.loads(path.read_text(encoding="utf-8"))["my_handle"] == "@keep"


def test_explicit_window_flags_beat_saved_values(tmp_path):
    options = PacketOptionsModel(
        output_directory="saved",
        packet_characters=300_000,
        comment_variations=("short_hook",),
    )
    arguments = CLI.build_parser().parse_args([
        "comment", "build", "--window",
        "--output-dir", str(tmp_path / "typed"),
        "--packet-characters", "310000",
        "--max-comments", "777",
        "--registers", "dry_joke",
        "--length", "long",
    ])

    CLI.apply_window_options(
        options,
        arguments,
        resolve(),
        start_mode="comment",
    )

    assert options.output_directory == str(tmp_path / "typed")
    assert options.packet_characters == 310_000
    assert options.max_top == options.max_recent == 777
    assert options.comment_variations == ("dry_joke",)
    assert options.length == "long"


def test_reply_window_max_comments_maps_to_reply_scan_only():
    options = PacketOptionsModel(max_top=100, reply_scan_comments=3000)
    arguments = CLI.build_parser().parse_args([
        "gui", "--max-comments", "4500", "--my-handle", "@owner",
    ])

    CLI.apply_window_options(
        options,
        arguments,
        resolve(),
        start_mode="reply",
    )

    assert options.reply_scan_comments == 4500
    assert options.max_top == 100


def test_comment_window_can_enable_local_whisper_from_the_command_line():
    options = PacketOptionsModel()
    arguments = CLI.build_parser().parse_args([
        "comment", "build", "--window", "--transcribe",
    ])

    CLI.apply_window_options(
        options,
        arguments,
        resolve(),
        start_mode="comment",
    )

    assert options.transcribe_locally is True
