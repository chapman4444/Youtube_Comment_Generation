"""A guided reply session, driven from a file.

The GUI drives this for real and is covered separately. This is the headless
path, which is the one the operator reaches when he has no display and the
only one that can be exercised when nobody happens to be owed a reply — which
is the state his channel was in the day this was written.
"""

from __future__ import annotations

import io
import json

import pytest

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
        "text": text or f"a message from {author} worth answering properly",
        "like_count": 2,
        "total_reply_count": replies,
        "published_at": f"2026-07-{published}T00:00:00Z",
        "updated_at": f"2026-07-{published}T00:00:00Z",
    }


@pytest.fixture
def ports():
    """Two people owed a reply, on two of the owner's comments."""

    return FakeYouTubePort(
        videos={VIDEO: {"video_id": VIDEO, "title": "A video",
                        "description": "d", "comment_count": 4}},
        comments=[
            message("c1", "@owner", OWNER, replies=1),
            message("c2", "@owner", OWNER, replies=1),
        ],
        replies={
            "c1": [message("r1", "@alice", "UC" + "alice".ljust(22, "z"),
                           published="02")],
            "c2": [message("r2", "@bob", "UC" + "bob".ljust(22, "z"),
                           published="02")],
        },
    )


def run(argv, tmp_path, youtube, clipboard=None):
    out, err = io.StringIO(), io.StringIO()
    clipboard = clipboard if clipboard is not None else FakeClipboard()

    def build(configuration, api_key, events):
        return {"youtube": youtube, "transcripts": FakeTranscriptPort(),
                "events": FakeEventSink(), "clipboard": clipboard}

    code = main(
        argv + ["--my-channel-id", OWNER,
                "--output-dir", str(tmp_path / "runs")],
        build_ports=build, stdout=out, stderr=err, clipboard=clipboard,
        environment={"YOUTUBE_API_KEY": "test-key"},
    )
    return code, out.getvalue(), err.getvalue()


def answers_file(tmp_path, *blocks):
    path = tmp_path / "answers.md"
    path.write_text("\n---\n".join(blocks), encoding="utf-8")
    return str(path)


def answer(text, cid="r1"):
    """A one-target reply sheet, as the model returns for a one-reply thread.

    No "---" anywhere: the answers file separates blocks with it.
    """

    return (
        "# Copy/Paste Replies\n\n"
        "## Direct replies to your comment\n\n"
        f"**Post beneath comment ID:** {cid}\n\n"
        f"```text\n{text}\n```"
    )


def artifacts(tmp_path):
    directory = next((tmp_path / "runs").iterdir())
    record = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    review = next(directory.glob("*.md"), None)
    return directory, record, review


def test_a_whole_session_runs_from_a_file(tmp_path, ports):
    source = answers_file(
        tmp_path,
        answer("Deloitte audited the entity, which is a claim about the firm.",
               cid="r1"),
        answer("The filing names the firm, not the person you are naming.",
               cid="r2"),
    )

    code, out, _ = run(
        ["reply", "guided", VIDEO, "--answers-from", source], tmp_path, ports)

    assert code == 0
    assert "2 threads to work through, covering 2 people" in out
    assert out.count("accepted and saved") == 2
    assert "2 replies ready to review, 0 skipped" in out


def test_every_accepted_draft_is_recorded_in_the_run(tmp_path, ports):
    """Saved as they are accepted, not at the end. Stopping must not lose
    work already done."""

    source = answers_file(
        tmp_path,
        answer("A first reply worth keeping.", cid="r1"),
        answer("A second reply worth keeping.", cid="r2"),
    )

    run(["reply", "guided", VIDEO, "--answers-from", source], tmp_path, ports)
    _, record, review = artifacts(tmp_path)

    assert record["kind"] == "guided"
    assert record["accepted"] == 2
    assert record["skipped"] == 0
    assert record["targets_offered"] == 2
    assert len(record["drafts"]) == 2
    assert record["artifact_contract_version"] == 3
    assert record["transcript"] == {
        "availability": "available",
        "source": "fake",
        "immediate_source": "fake",
        "original_source": "fake",
        "is_generated": False,
        "language": "English",
        "language_code": "en",
        "entries": 1,
        "detail": "",
        "originating_run": "",
        "attempts": [],
    }
    assert review is not None and review.stat().st_size > 0


def test_reply_build_records_complete_transcript_provenance(tmp_path, ports):
    code, _, _ = run(
        ["reply", "build", VIDEO, "--comment-id", "r1"],
        tmp_path,
        ports,
    )
    _, record, _ = artifacts(tmp_path)

    assert code == 0
    assert record["kind"] == "reply"
    assert record["artifact_contract_version"] == 3
    assert record["transcript"]["immediate_source"] == "fake"
    assert record["transcript"]["original_source"] == "fake"
    assert record["transcript"]["is_generated"] is False
    assert record["transcript"]["entries"] == 1


def test_running_out_of_answers_keeps_what_was_accepted(tmp_path, ports):
    """The file is shorter than the queue. That is a stop, not a failure."""

    source = answers_file(tmp_path, answer("Only one answer supplied here."))

    code, out, _ = run(
        ["reply", "guided", VIDEO, "--answers-from", source], tmp_path, ports)
    _, record, _ = artifacts(tmp_path)

    assert code == 0
    assert "no answer left in the file" in out
    assert record["accepted"] == 1
    assert "1 replies ready to review" in out


def test_the_packet_submitted_as_its_own_answer_is_refused(tmp_path, ports):
    """A stray paste sends the packet back. It contains "### Hardened final"
    in its own instructions, so extraction would return a line of prompt."""

    packet = ("# GLOBAL YOUTUBE REPLY WORKFLOW\n\n"
              "### Hardened final\n\nBuild a sixth text.\n\n"
              "## BEGIN UNTRUSTED SOURCE MATERIAL\nevidence\n"
              "## END UNTRUSTED SOURCE MATERIAL\n")
    source = answers_file(tmp_path, packet, answer("A real reply this time."))

    code, out, _ = run(
        ["reply", "guided", VIDEO, "--answers-from", source], tmp_path, ports)
    _, record, _ = artifacts(tmp_path)

    assert code == 0
    assert "refused:" in out
    assert record["accepted"] < 2


def test_the_limit_caps_how_many_people_are_offered(tmp_path, ports):
    source = answers_file(tmp_path, answer("One reply is enough here."))

    _, out, _ = run(
        ["reply", "guided", VIDEO, "--answers-from", source, "--limit", "1"],
        tmp_path, ports)
    _, record, _ = artifacts(tmp_path)

    assert "1 threads to work through, covering 1 people" in out
    assert record["targets_offered"] == 1


def test_a_missing_answers_file_is_refused_before_any_work(tmp_path, ports):
    code, out, err = run(
        ["reply", "guided", VIDEO, "--answers-from",
         str(tmp_path / "nope.md")], tmp_path, ports)

    assert code != 0
    assert "No answers file" in err
    assert "people to work through" not in out


def test_nobody_waiting_is_stated_rather_than_producing_an_empty_run(tmp_path):
    """The scan found people and none of them is owed anything."""

    answered = FakeYouTubePort(
        videos={VIDEO: {"video_id": VIDEO, "title": "A video",
                        "description": "d", "comment_count": 2}},
        comments=[message("c1", "@owner", OWNER, replies=2)],
        replies={"c1": [
            message("r1", "@alice", "UC" + "alice".ljust(22, "z"),
                    published="02"),
            message("r2", "@owner", OWNER, published="03",
                    text="@alice that is fair, here is why"),
        ]},
    )

    code, out, _ = run(["reply", "guided", VIDEO], tmp_path, answered)

    assert code == 0
    assert "Nobody in this scan is waiting for an answer." in out
