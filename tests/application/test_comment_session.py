"""Comment acceptance and explicit posting-history confirmation."""

from __future__ import annotations

from llm_youtube_comment_generation.application.comment_session import (
    CommentSession,
)
from llm_youtube_comment_generation.infrastructure.memory_artifacts import (
    MemoryArtifactStore,
)

VIDEO = "gC-J7zwYMAM"
VIDEO_LINE = (
    "**Video:** A video "
    "https://www.youtube.com/watch?v=gC-J7zwYMAM"
)
ANSWER = (
    f"{VIDEO_LINE}\n\n"
    "### Hardened final\nA finished comment ready to post."
)


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


def test_a_markdown_link_in_the_video_line_is_refused_before_saving():
    one = make_session()
    one.start()
    nested = (
        "**Video:** A video "
        "[[https://www.youtube.com/watch?v=gC-J7zwYMAM]"
        "(https://www.youtube.com/watch?v=gC-J7zwYMAM)]"
        "(https://www.youtube.com/watch?v=gC-J7zwYMAM)\n\n"
        "### Hardened final\nA comment that must not be saved."
    )

    result = one.submit(nested)

    assert result.status.value == "refused"
    assert "exactly once as plain text" in one.state.last_error
    assert "found 3 copies" in one.state.last_error
    assert one.accepted == []
    assert one.artifacts.committed_names() == ()


def test_the_video_line_must_be_the_first_nonblank_line():
    one = make_session()
    one.start()
    misplaced = (
        "Here is the answer.\n"
        f"{VIDEO_LINE}\n\n"
        "### Hardened final\nA comment that must not be saved."
    )

    result = one.submit(misplaced)

    assert result.status.value == "refused"
    assert "first nonblank line" in one.state.last_error
    assert one.accepted == []


def test_curly_apostrophes_and_emoji_survive_answer_storage():
    one = make_session()
    one.start()
    unicode_draft = "BAM’s response preserved the evidence. 😄"

    one.submit(f"{VIDEO_LINE}\n\n### Hardened final\n{unicode_draft}")

    saved = one.artifacts.read("comment_drafts.md")
    assert unicode_draft in saved


def test_debug_build_saves_the_complete_response_and_shareable_bundle():
    one = make_session()
    one.debug_build = True
    one.debug_settings = {"length": "short", "whisper_policy": "ask"}
    one.run_record = {"video_id": VIDEO, "video_title": "A video"}
    one.start()
    raw_answer = (
        f"{VIDEO_LINE}\n\n### Debug report\n"
        "The evidence is attributed and the variations are distinct.\n\n"
        "### Hardened final\nA finished comment ready to post."
    )

    one.submit(raw_answer)

    assert one.artifacts.read("debug_model_response.md") == raw_answer
    bundle = one.artifacts.read("debug_bundle.md")
    assert "## Safe build settings" in bundle
    assert "## Complete model response" in bundle
    assert raw_answer in bundle


def test_debug_build_preserves_a_rejected_response_and_explains_why():
    one = make_session()
    one.debug_build = True
    one.start()
    missing_report = (
        f"{VIDEO_LINE}\n\n### Hardened final\n"
        "A finished comment ready to post."
    )

    result = one.submit(missing_report)

    assert result.status.value == "refused"
    assert "### Debug report" in one.state.last_error
    assert one.artifacts.read("debug_model_response_rejected.md") == missing_report
    bundle = one.artifacts.read("debug_bundle.md")
    assert "Response status" in bundle
    assert "requires exactly one" in bundle
