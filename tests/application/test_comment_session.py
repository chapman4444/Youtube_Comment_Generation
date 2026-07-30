"""Comment acceptance and explicit posting-history confirmation."""

from __future__ import annotations

from llm_youtube_comment_generation.application.comment_session import (
    CommentSession,
)
from llm_youtube_comment_generation.infrastructure.memory_artifacts import (
    MemoryArtifactStore,
)

VIDEO = "gC-J7zwYMAM"
ANSWER = "### Hardened final\nA finished comment ready to post."


class RecordingHistory:
    def __init__(self):
        self.entries = []

    def append(self, entries):
        self.entries.extend(dict(entry) for entry in entries)
        return len(entries)


def make_session(history=None):
    return CommentSession(
        packet_text="# packet\n" + "evidence " * 100,
        video={"video_id": VIDEO, "title": "A video"},
        registers=("short_hook",),
        packet_path="output/run/packet.md",
        prompt_version="abc123",
        run_id="run-1",
        artifacts=MemoryArtifactStore(),
        history=history,
    )


def accept(one):
    one.start()
    one.copy_packet()
    one.submit(ANSWER)


def test_accepting_a_draft_saves_it_but_does_not_claim_it_was_posted():
    history = RecordingHistory()
    one = make_session(history)

    accept(one)

    assert one.artifacts.read("comment_drafts.md")
    assert history.entries == []


def test_operator_confirmation_records_the_posting_context():
    history = RecordingHistory()
    one = make_session(history)
    accept(one)

    assert one.record_posted() == 1

    recorded = history.entries[0]
    assert recorded["video_id"] == VIDEO
    assert recorded["workflow"] == "comment"
    assert recorded["draft"] == "A finished comment ready to post."
    assert recorded["run_id"] == "run-1"
    assert recorded["prompt_version"] == "abc123"
    assert one.accepted[-1].posted_recorded
    assert "Posting recorded: yes" in one.artifacts.read("comment_drafts.md")


def test_posting_confirmation_is_not_written_twice():
    history = RecordingHistory()
    one = make_session(history)
    accept(one)

    assert one.record_posted() == 1
    assert one.record_posted() == 0
    assert len(history.entries) == 1
