"""Taking the video from the clipboard when none was named.

Copying a URL from the browser is how the operator reaches a video, so
pasting it back into a terminal is a step the tool can remove. What it must
not do is start a run on a video he did not choose: the tool puts its own
packet on the clipboard when a run finishes, and a packet quotes the video
description, links and all.
"""

from __future__ import annotations

import io

import pytest

from fakes import FakeClipboard, FakeEventSink, FakeTranscriptPort, FakeYouTubePort
from llm_youtube_comment_generation.domain.ids import find_video_reference
from llm_youtube_comment_generation.interfaces.cli.main import main

VIDEO = "gC-J7zwYMAM"


def comment(index):
    return {
        "comment_id": f"c{index}", "author": f"@u{index}",
        "author_channel_id": "UC" + str(index).ljust(22, "z"),
        "text": "a comment body worth reading", "like_count": index,
        "total_reply_count": 0, "published_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
    }


def run(argv, tmp_path, held):
    """Run with `held` sitting on the clipboard."""

    out, err = io.StringIO(), io.StringIO()
    clipboard = FakeClipboard(held)
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
        build_ports=build, stdout=out, stderr=err, clipboard=clipboard,
        environment={"YOUTUBE_API_KEY": "test-key"},
    )
    return code, out.getvalue(), err.getvalue()


# -- what counts as a video reference --------------------------------------


@pytest.mark.parametrize("held", [
    "https://www.youtube.com/watch?v=gC-J7zwYMAM",
    "https://youtu.be/gC-J7zwYMAM?si=trackingnonsense",
    "https://m.youtube.com/watch?v=gC-J7zwYMAM&t=42s",
    "youtube.com/shorts/gC-J7zwYMAM",
    "  gC-J7zwYMAM  ",
    "watch this https://youtu.be/gC-J7zwYMAM it is worth your time",
])
def test_the_shapes_a_clipboard_actually_holds(held):
    assert find_video_reference(held) == VIDEO


@pytest.mark.parametrize("held", [
    "",
    "   ",
    "nothing to see here",
    "https://example.com/watch?v=gC-J7zwYMAM",
    "https://www.youtube.com/@somechannel",
    "https://www.youtube.com/playlist?list=PL1234567890",
])
def test_text_with_no_video_in_it_returns_nothing(held):
    assert find_video_reference(held) == ""


def test_a_bare_id_is_only_taken_when_it_is_the_whole_clipboard():
    """Eleven characters of [A-Za-z0-9_-] is also an ordinary English word.

    Scanning prose for one would start a run at "Republicans". Nothing can
    tell that word from a real ID, so the only safe rule is to require the
    whole clipboard: alone it is a plausible ID and the API settles it, but
    inside a sentence it is a word and is left alone.
    """

    assert find_video_reference("the Republicans lost that seat") == ""
    assert find_video_reference("Republicans") == "Republicans"


def test_a_channel_link_does_not_stop_the_search():
    """The first YouTube link is not always the video."""

    held = ("https://www.youtube.com/@somechannel and the video is "
            "https://www.youtube.com/watch?v=gC-J7zwYMAM")

    assert find_video_reference(held) == VIDEO


# -- at the command line ---------------------------------------------------


def test_a_url_on_the_clipboard_is_enough_to_build(tmp_path):
    code, out, _ = run(
        ["comment", "build"], tmp_path,
        "https://www.youtube.com/watch?v=gC-J7zwYMAM",
    )

    assert code == 0
    assert "Packet written" in out


def test_what_was_read_is_announced_before_anything_is_fetched(tmp_path):
    """A wrong video spends quota and writes a directory under its name."""

    _, out, _ = run(["comment", "build"], tmp_path,
                    "https://youtu.be/gC-J7zwYMAM")

    assert f"Read the video from your clipboard: {VIDEO}" in out
    assert out.index("clipboard") < out.index("Packet written")


def test_a_named_video_never_reads_the_clipboard(tmp_path):
    """The argument is the operator's instruction; nothing may override it."""

    code, out, _ = run([
        "comment", "build", VIDEO,
    ], tmp_path, "https://www.youtube.com/watch?v=OTHERvideo1")

    assert code == 0
    assert "Read the video from your clipboard" not in out


def test_a_packet_on_the_clipboard_is_refused(tmp_path):
    """The tool's own output must not become its next input.

    A finished run leaves a packet on the clipboard, and the packet quotes
    the video description. Reading it back would start a run on whatever
    link that description happened to contain.
    """

    packet = (
        "# GLOBAL YOUTUBE COMMENT WORKFLOW\n\n"
        "### Hardened final\n\n"
        "## BEGIN UNTRUSTED SOURCE MATERIAL\n"
        "subscribe at https://www.youtube.com/watch?v=gC-J7zwYMAM\n"
        "## END UNTRUSTED SOURCE MATERIAL\n"
    )

    code, out, err = run(["comment", "build"], tmp_path, packet)

    assert code != 0
    assert "holds a packet" in err
    assert "Packet written" not in out


def test_an_empty_clipboard_says_what_to_do(tmp_path):
    code, _, err = run(["comment", "build"], tmp_path, "")

    assert code != 0
    assert "no YouTube link was found" in err
    assert "command line" in err
