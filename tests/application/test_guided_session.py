"""A guided run, driven end to end against fakes.

The state machine's own rules are covered in tests/domain/test_workflow.py.
These cover the session that uses it: that work is saved as it happens, that
the packet cannot be its own answer, and that an interruption keeps what was
already accepted.
"""

from __future__ import annotations

import pytest

from fakes import FakeArtifactStore, FakeClipboard, FakeEventSink
from llm_youtube_comment_generation.application.guided_session import (
    REVIEW_FILENAME,
    GuidedSession,
)
from llm_youtube_comment_generation.domain.candidates import (
    build_reply_candidates,
)
from llm_youtube_comment_generation.domain.statuses import OperationStatus
from llm_youtube_comment_generation.domain.threads import OwnerThread
from llm_youtube_comment_generation.domain.workflow import Phase
from llm_youtube_comment_generation.infrastructure import prompt_resources

OWNER = "UC" + "o" * 22


class RecordingHistory:
    def __init__(self):
        self.entries = []

    def append(self, entries):
        self.entries.extend(dict(entry) for entry in entries)
        return len(entries)


def message(cid, author, text, when, *, channel=None, likes=0):
    return {
        "comment_id": cid,
        "author": author,
        "author_channel_id": channel or ("UC" + author.lstrip("@").ljust(22, "z"))[:24],
        "text": text,
        "like_count": likes,
        "published_at": when,
        "updated_at": when,
    }


def answer(text: str) -> str:
    return (
        "### 1. Flat contradiction\nsomething\n\n"
        "### Harsh critique\nranking\n\n"
        f"### Hardened final\n{text}\n"
    )


@pytest.fixture
def session():
    replies = [
        message("r1", "@alice", "actually you are wrong", "2026-07-02T00:00:00Z",
                likes=9),
        message("r2", "@bob", "a separate question", "2026-07-02T01:00:00Z"),
        message("r3", "@carol", "and one more thing", "2026-07-02T02:00:00Z"),
    ]
    thread = OwnerThread(
        comment=message("mine", "@owner", "my comment", "2026-07-01T00:00:00Z",
                        channel=OWNER),
        replies=replies,
    )
    candidates = build_reply_candidates(OWNER, "@owner", replies, "mine")
    return GuidedSession(
        targets=candidates,
        threads={"mine": thread},
        owner_channel_id=OWNER,
        video={"video_id": "gC-J7zwYMAM", "title": "A video"},
        transcript_text="[00:00:00] words",
        templates={
            "reply_workflow.md": prompt_resources.load("reply_workflow.md").text,
            "reply_final_check.md":
                prompt_resources.load("reply_final_check.md").text,
        },
        artifacts=FakeArtifactStore(),
        clipboard=FakeClipboard(),
        events=FakeEventSink(),
    )


# --------------------------------------------------------------------------
# A whole run
# --------------------------------------------------------------------------


def test_a_whole_run_walks_every_person_and_writes_the_file(session):
    session.start()

    while session.next_person() is not None:
        session.copy_packet()
        session.submit(answer(f"reply to {session.current.author}"))

    session.finish()

    assert session.state.phase is Phase.COMPLETE
    assert len(session.accepted) == 3
    review = session.artifacts.read(REVIEW_FILENAME)
    for author in ("@alice", "@bob", "@carol"):
        assert author in review


def test_reply_history_waits_for_explicit_post_confirmation(session):
    history = RecordingHistory()
    session.history = history
    session.prompt_version = "abc123"
    session.run_id = "run-1"
    session.start()
    session.next_person()
    session.copy_packet()
    session.submit(answer("the reply that was manually posted"))

    assert history.entries == []
    assert session.record_posted() == 1

    recorded = history.entries[0]
    assert recorded["workflow"] == "reply"
    assert recorded["target_comment_id"] == "r1"
    assert recorded["thread_id"] == "mine"
    assert recorded["operator_channel_id"] == OWNER
    assert session.accepted[-1].posted_recorded
    assert "posting recorded: yes" in session.artifacts.read(REVIEW_FILENAME)


def test_every_accepted_draft_is_saved_before_the_next_one_starts(session):
    """Not at the end. A run that saves at the end loses everything to the
    first interruption."""

    session.start()
    session.next_person()
    session.submit(answer("the first reply"))

    saved = session.artifacts.read(REVIEW_FILENAME)

    assert "the first reply" in saved
    assert len(session.accepted) == 1


def test_an_interrupted_run_keeps_what_was_already_accepted(session):
    session.start()
    session.next_person()
    session.submit(answer("first reply"))
    session.next_person()

    session.cancel()

    assert session.state.phase is Phase.CANCELLED
    assert "first reply" in session.artifacts.read(REVIEW_FILENAME)


def test_the_real_set_survives_a_skip_in_the_middle(session):
    session.start()

    first = session.next_person()
    session.submit(answer("answered the first"))

    # The queue is ranked by score, not by the order the replies were
    # written, so the middle person is whoever next_person() actually hands
    # back rather than whoever was second in the fixture.
    middle = session.next_person()
    session.skip_person()

    last = session.next_person()
    session.submit(answer("answered the third"))
    session.finish()

    review = session.artifacts.read(REVIEW_FILENAME)

    assert len({first.author, middle.author, last.author}) == 3
    assert len(session.accepted) == 2
    assert session.skipped == [middle.author]
    assert [d.author for d in session.accepted] == [first.author, last.author]
    assert "## Skipped" in review
    assert middle.author in review.split("## Skipped")[1]


def test_skipping_every_person_still_finishes(session):
    session.start()
    while session.next_person() is not None:
        session.skip_person()
    session.finish()

    assert session.state.phase is Phase.COMPLETE
    assert session.accepted == []
    assert "No replies were accepted" in session.artifacts.read(REVIEW_FILENAME)


def test_the_queue_ends_cleanly_rather_than_running_off_the_end(session):
    session.start()
    for _ in range(3):
        session.next_person()
        session.skip_person()

    assert session.next_person() is None


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


def test_the_packet_is_refused_as_its_own_answer(session):
    """The clipboard holds the packet, and the answer is asked for on the
    same clipboard. A stray copy submits the packet to itself."""

    session.start()
    session.next_person()
    packet = session.copy_packet()

    result = session.submit(packet)

    assert result.status is OperationStatus.REFUSED
    assert session.state.phase is Phase.ANSWER_REJECTED
    assert session.accepted == []


def test_packet_detection_runs_before_extraction(session):
    """The packet contains a literal "### Hardened final" heading.

    Extraction would return a line of prompt text: an answer that looks like
    an answer, about to be posted under the operator's own name.
    """

    session.start()
    session.next_person()
    packet = session.copy_packet()

    assert "### Hardened final" in packet
    result = session.submit(packet)

    assert result.status is OperationStatus.REFUSED
    assert "the packet, not an answer" in session.state.last_error


def test_an_answer_with_no_hardened_final_is_refused(session):
    session.start()
    session.next_person()

    result = session.submit("Here are some thoughts but no section heading.")

    assert result.status is OperationStatus.REFUSED
    assert "Hardened final" in session.state.last_error
    assert session.accepted == []


def test_a_refusal_keeps_the_same_person_so_it_can_be_pasted_again(session):
    session.start()
    person = session.next_person()

    session.submit("unreadable")
    assert session.current is person

    session.submit(answer("the real reply"))

    assert len(session.accepted) == 1
    assert session.accepted[0].author == person.author


def test_a_refusal_does_not_write_anything_to_the_review_file(session):
    session.start()
    session.next_person()

    session.submit("unreadable")

    assert REVIEW_FILENAME not in session.artifacts.committed_names()


# --------------------------------------------------------------------------
# The review file
# --------------------------------------------------------------------------


def test_the_review_file_holds_the_reply_ready_to_paste(session):
    session.start()
    session.next_person()
    session.submit(answer("The finished reply, exactly as written."))
    session.finish()

    review = session.artifacts.read(REVIEW_FILENAME)

    assert "The finished reply, exactly as written." in review
    assert "**Your reply:**" in review


def test_the_review_file_shows_what_they_said_for_context(session):
    session.start()
    session.next_person()
    session.submit(answer("a reply"))
    session.finish()

    review = session.artifacts.read(REVIEW_FILENAME)

    assert "actually you are wrong" in review
    assert "**They said:**" in review


def test_the_review_file_says_nothing_was_posted(session):
    """This tool never posts. The file must not imply otherwise."""

    session.start()
    session.next_person()
    session.submit(answer("a reply"))
    session.finish()

    assert "Nothing here has been posted" in \
        session.artifacts.read(REVIEW_FILENAME)


def test_the_session_is_the_only_writer_of_the_review_file(session):
    """One writer means the file cannot be half-written by two paths that
    disagree about its shape."""

    session.start()
    session.next_person()
    session.submit(answer("a reply"))
    session.finish()

    assert session.artifacts.committed_names() == (REVIEW_FILENAME,)


def test_copying_never_advances_the_run(session):
    session.start()
    person = session.next_person()

    for _ in range(3):
        session.copy_packet()

    assert session.current is person
    assert session.state.phase is Phase.PERSON_PACKET_READY


def test_the_packet_reaches_the_clipboard(session):
    session.start()
    session.next_person()
    session.copy_packet()

    assert session.clipboard.read() == session.current_packet
    assert len(session.clipboard.writes) == 1
