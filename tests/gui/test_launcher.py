from __future__ import annotations

from llm_youtube_comment_generation.interfaces.gui.launcher import run


def test_successful_startup_is_silent():
    messages: list[str] = []

    result = run(
        ["gui", "--preview"],
        entrypoint=lambda argv: 0,
        notifier=messages.append,
    )

    assert result == 0
    assert messages == []


def test_configuration_exit_is_visible():
    messages: list[str] = []

    result = run(
        ["comment", "build", "--window"],
        entrypoint=lambda argv: 3,
        notifier=messages.append,
    )

    assert result == 3
    assert len(messages) == 1
    assert "configuration" in messages[0]


def test_missing_transcript_exit_is_visible():
    messages: list[str] = []

    result = run(
        ["comment", "build", "--window"],
        entrypoint=lambda argv: 5,
        notifier=messages.append,
    )

    assert result == 5
    assert len(messages) == 1
    assert "No transcript" in messages[0]


def test_unexpected_initialization_failure_is_visible(
    tmp_path, monkeypatch,
):
    messages: list[str] = []
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    def fail(argv):
        raise RuntimeError("initialization failed")

    result = run(
        ["gui"],
        entrypoint=fail,
        notifier=messages.append,
    )

    assert result == 1
    assert len(messages) == 1
    assert "unexpected error" in messages[0]
    log = tmp_path / "YouTubeCommentGeneration" / "gui_startup.log"
    assert log.is_file()
    assert "RuntimeError: initialization failed" in log.read_text(
        encoding="utf-8"
    )
