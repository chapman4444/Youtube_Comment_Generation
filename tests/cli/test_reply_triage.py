"""Reply triage at the command line.

The packet lists only people still waiting for an answer. The scan line
above it counts everybody it found. Those are different numbers, and the
run record has to report the one that matches the packet — a stored count
that describes a packet nobody built is worse than no count at all.
"""

from __future__ import annotations

import io
import json

from fakes import FakeClipboard, FakeEventSink, FakeTranscriptPort, FakeYouTubePort
from llm_youtube_comment_generation.interfaces.cli.main import main

VIDEO = "gC-J7zwYMAM"
OWNER = "UC" + "owner".ljust(22, "z")


def message(identifier, author, channel_id, *, replies=0, published="01",
            text=None):
    return {
        "comment_id": identifier,
        "author": author,
        "author_channel_id": channel_id,
        "text": text or f"a message from {author} worth reading",
        "like_count": 1,
        "total_reply_count": replies,
        "published_at": f"2026-07-{published}T00:00:00Z",
        "updated_at": f"2026-07-{published}T00:00:00Z",
    }


def channel_for(handle):
    return "UC" + handle.ljust(22, "z")


def run(argv, tmp_path):
    """One thread answered, one thread still waiting.

    Two candidates are found. Exactly one of them is owed a reply.
    """

    out, err = io.StringIO(), io.StringIO()
    youtube = FakeYouTubePort(
        videos={VIDEO: {"video_id": VIDEO, "title": "A real video",
                        "comment_count": 2}},
        comments=[
            message("c1", "@owner", OWNER, replies=2),
            message("c2", "@owner", OWNER, replies=1),
        ],
        replies={
            "c1": [
                message("r1", "@alice", channel_for("alice"), published="02"),
                # Addressed to alice by name: an answer only counts against
                # the person it actually names.
                message("r2", "@owner", OWNER, published="03",
                        text="@alice that is a fair point, here is why"),
            ],
            "c2": [
                message("r3", "@bob", channel_for("bob"), published="02"),
            ],
        },
    )

    def build(configuration, api_key, events):
        return {"youtube": youtube, "transcripts": FakeTranscriptPort(),
                "events": FakeEventSink(), "clipboard": FakeClipboard()}

    code = main(
        argv + ["--my-channel-id", OWNER,
                "--output-dir", str(tmp_path / "runs")],
        build_ports=build, stdout=out, stderr=err,
        environment={"YOUTUBE_API_KEY": "test-key"},
    )
    return code, out.getvalue(), tmp_path / "runs"


def artifacts(root):
    directory = next(root.iterdir())
    packet = (directory / "reply_triage_packet.md").read_text(encoding="utf-8")
    record = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    return packet, record


def test_the_record_counts_the_people_the_packet_actually_lists(tmp_path):
    """It once stored three for a packet containing one.

    The caller counted the scan while the packet counted the outstanding
    subset. Both numbers were real; only one of them described the file.
    """

    code, _, root = run(["reply", "triage", VIDEO], tmp_path)
    packet, record = artifacts(root)

    assert code == 0
    assert record["candidates_listed"] == packet.count("**[")
    assert record["candidates_listed"] == 1


def test_the_record_keeps_the_larger_counts_without_confusing_them(tmp_path):
    _, _, root = run(["reply", "triage", VIDEO], tmp_path)
    _, record = artifacts(root)

    assert record["candidates_found"] == 2
    assert record["candidates_waiting"] == 1


def test_an_answered_person_is_not_listed_for_triage_again(tmp_path):
    """Ranking somebody already finished with costs a duplicate reply."""

    _, _, root = run(["reply", "triage", VIDEO], tmp_path)
    packet, _ = artifacts(root)

    assert "@bob" in packet
    assert "@alice" not in packet


def test_the_shortfall_is_stated_rather_than_left_to_arithmetic(tmp_path):
    """Printing only "2 people found" reads as "both are in the packet"."""

    _, out, _ = run(["reply", "triage", VIDEO], tmp_path)

    assert "listed" in out
    assert "1 of 2 people found" in out
    assert "1 already answered" in out


def test_an_empty_packet_says_which_kind_of_empty_it_is(tmp_path):
    """"Nobody is waiting" and "the limit emptied it" are opposites.

    Confusing them tells the operator, and the model, that a person owed a
    reply does not exist.
    """

    _, out, root = run(["reply", "triage", VIDEO, "--limit", "0"], tmp_path)
    packet, record = artifacts(root)

    assert record["candidates_listed"] == 0
    assert record["candidates_waiting"] == 1
    assert packet.count("**[") == 0

    assert "--limit held back all 1 people still waiting" in out
    assert "Nobody in this scan is waiting" not in packet
    assert "do not read it as nobody being owed an answer" in packet
