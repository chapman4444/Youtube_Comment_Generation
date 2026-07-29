"""Putting the finished packet on the clipboard.

The workflow is build, then paste. Making the operator find the file and
select all of it every time is a step the tool can remove — but replacing
the clipboard is a real side effect on whatever he had there, so it is
announced every time and can be turned off.
"""

from __future__ import annotations

import io

from fakes import FakeClipboard, FakeEventSink, FakeTranscriptPort, FakeYouTubePort
from llm_youtube_comment_generation.interfaces.cli.main import (
    copy_to_clipboard,
    main,
)

VIDEO = "gC-J7zwYMAM"


def comment(index):
    return {
        "comment_id": f"c{index}", "author": f"@u{index}",
        "author_channel_id": "UC" + str(index).ljust(22, "z"),
        "text": "a comment body worth reading", "like_count": index,
        "total_reply_count": 0, "published_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
    }


def run(argv, tmp_path, clipboard=None):
    out, err = io.StringIO(), io.StringIO()
    clipboard = clipboard if clipboard is not None else FakeClipboard()
    youtube = FakeYouTubePort(
        videos={VIDEO: {"video_id": VIDEO, "title": "A video",
                        "description": "d", "comment_count": 4}},
        comments=[comment(i) for i in range(4)],
    )

    def build(configuration, api_key, events):
        return {"youtube": youtube, "transcripts": FakeTranscriptPort(),
                "events": FakeEventSink(), "clipboard": clipboard}

    code = main(
        argv + ["--output-dir", str(tmp_path / "runs")],
        build_ports=build, stdout=out, stderr=err,
        environment={"YOUTUBE_API_KEY": "test-key"},
    )
    return code, out.getvalue(), clipboard


def test_a_built_packet_lands_on_the_clipboard(tmp_path):
    code, out, clipboard = run(["comment", "build", VIDEO], tmp_path)

    assert code == 0
    assert clipboard.read().startswith("# GLOBAL YOUTUBE COMMENT WORKFLOW")
    assert "## BEGIN UNTRUSTED SOURCE MATERIAL" in clipboard.read()


def test_the_copy_is_announced_rather_than_silent(tmp_path):
    """A tool that changes the clipboard without a word is one you stop
    trusting with anything else."""

    _, out, clipboard = run(["comment", "build", VIDEO], tmp_path)

    assert "on your clipboard" in out
    assert f"{len(clipboard.read()):,} characters" in out


def test_the_clipboard_holds_exactly_what_was_written_to_the_file(tmp_path):
    _, out, clipboard = run(["comment", "build", VIDEO], tmp_path)

    directory = next((tmp_path / "runs").iterdir())
    written = (directory / "packet.md").read_text(encoding="utf-8")

    assert clipboard.read() == written


def test_no_copy_leaves_the_clipboard_alone(tmp_path):
    """Whatever the operator had there is his, not ours."""

    clipboard = FakeClipboard("something the operator was keeping")

    code, out, clipboard = run(
        ["comment", "build", VIDEO, "--no-copy"], tmp_path, clipboard
    )

    assert code == 0
    assert clipboard.read() == "something the operator was keeping"
    assert clipboard.writes == []
    assert "clipboard" not in out


def test_a_dry_run_never_touches_the_clipboard(tmp_path):
    """It sends no request; it should change nothing either."""

    clipboard = FakeClipboard("untouched")

    code, _, clipboard = run(
        ["comment", "build", VIDEO, "--dry-run"], tmp_path, clipboard
    )

    assert code == 0
    assert clipboard.read() == "untouched"


def test_a_clipboard_that_refuses_is_reported_not_ignored():
    """Another application can hold the clipboard.

    Saying nothing would leave the operator about to paste whatever was
    there before, believing it was the packet.
    """

    class RefusingClipboard:
        def read(self) -> str:
            return "not the packet"

        def write(self, text: str) -> None:
            pass                            # silently drops it, as Windows can

    out = io.StringIO()
    copied = copy_to_clipboard({"clipboard": RefusingClipboard()},
                               "the packet", out)

    assert copied is False
    assert "could not be set" in out.getvalue()
    assert "by hand" in out.getvalue()


def test_no_clipboard_port_is_not_an_error():
    out = io.StringIO()

    assert copy_to_clipboard({}, "the packet", out) is False
    assert out.getvalue() == ""
