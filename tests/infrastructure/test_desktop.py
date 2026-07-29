"""Handing a file to the desktop.

The window's "Open replies" button was wired to a callable that did nothing.
It is the primary action in every phase a run can end in, so the last thing
the operator did in a finished run was press a button with no effect and no
explanation.

No test here may actually open anything. tests/conftest.py refuses
os.startfile, subprocess.Popen and webbrowser.open for every test in the
suite; if one of those guards fires, this module is wrong, not the guard.
"""

from __future__ import annotations

import subprocess

import pytest

from llm_youtube_comment_generation.infrastructure import desktop


@pytest.fixture
def review(tmp_path):
    path = tmp_path / "replies_to_review.md"
    path.write_text("# drafts\n", encoding="utf-8")
    return path


def test_a_missing_file_is_explained_rather_than_opened(tmp_path):
    """Pressing it before the first reply is accepted is not an error."""

    message = desktop.open_path(tmp_path / "nothing.md")

    assert "does not exist" in message
    assert "written when the first one is accepted" in message.lower()


def test_the_editor_setting_is_finally_read(review, monkeypatch):
    """It was in the configuration from the first day and nothing used it."""

    launched = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **k: launched.append(argv))

    message = desktop.open_path(review, editor="notepad.exe")

    assert message == ""
    assert launched == [["notepad.exe", str(review)]]


def test_the_editor_is_not_waited_for(review, monkeypatch):
    """subprocess.run waits for the editor to exit, which would freeze the Tk
    event loop until the operator closed their text editor."""

    def refuse(*args, **kwargs):
        raise AssertionError("run() blocks until the editor is closed")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **k: None)

    assert desktop.open_path(review, editor="notepad.exe") == ""


def test_a_desktop_that_will_not_start_never_raises(review, monkeypatch):
    """By this point the replies are on disk. An exception unwinding the last
    step of a saved run looks like the run failed."""

    def refuse(*args, **kwargs):
        raise OSError("no shell association")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(desktop.webbrowser, "open", refuse)
    monkeypatch.setattr(desktop.os, "startfile", refuse, raising=False)

    message = desktop.open_path(review)

    assert "written and safe" in message
    assert str(review) in message


def test_a_browser_is_tried_before_giving_up(review, monkeypatch):
    opened = []

    def refuse(*args, **kwargs):
        raise OSError("no shell association")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(desktop.os, "startfile", refuse, raising=False)
    monkeypatch.setattr(desktop.webbrowser, "open",
                        lambda uri: opened.append(uri) or True)

    assert desktop.open_path(review) == ""
    assert opened and opened[0].startswith("file:")
