"""A guided run, driven end to end against fakes.

The state machine's own rules are covered in tests/domain/test_workflow.py.
These cover the session that uses it: that work is saved as it happens, that
the packet cannot be its own answer, and that an interruption keeps what was
already accepted.

One packet now answers every response in one owner thread, so the unit the
session walks is the thread. The fixture gives three threads with one
responder each — the walk, skip and interruption mechanics keep their old
meaning — and the batch behaviour has its own section below with a
multi-responder thread.
"""

from __future__ import annotations

import pytest

from fakes import FakeArtifactStore, FakeClipboard, FakeEventSink
from llm_youtube_comment_generation.application.guided_session import (
    REVIEW_FILENAME,
    GuidedSession,
    whole_thread_selection,
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


def sheet_for(session, make=None):
    """A well-formed Copy/Paste Replies sheet for the current packet."""

    make = make or (
        lambda target: f"reply to {target.author_display_name}"
    )
    total = len(session.current_targets)
    lines = ["# Copy/Paste Replies", "", "## Direct replies to your comment",
             ""]
    for target in session.current_targets:
        lines.extend([
            f"### Response {target.response_number} of {total}: "
            f"{target.author_display_name}",
            "",
            f"**Post beneath comment ID:** {target.comment_id}",
            "",
            f"**Relationship:** {target.relationship.title()}",
            "",
            "```text",
            make(target),
            "```",
            "",
        ])
    return "\n".join(lines)


def _one_thread(tid, author, text, likes=0):
    replies = [message(f"{tid}-r1", author, text, "2026-07-02T00:00:00Z",
                       likes=likes)]
    thread = OwnerThread(
        comment=message(tid, "@owner", f"my comment on {tid}",
                        "2026-07-01T00:00:00Z", channel=OWNER),
        replies=replies,
    )
    return thread, build_reply_candidates(OWNER, "@owner", replies, tid)


def _session(threads_and_candidates):
    threads = {}
    candidates = []
    for thread, found in threads_and_candidates:
        threads[thread.comment_id] = thread
        candidates.extend(found)
    return GuidedSession(
        targets=candidates,
        threads=threads,
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


@pytest.fixture
def session():
    return _session([
        _one_thread("t1", "@alice", "actually you are wrong", likes=9),
        _one_thread("t2", "@bob", "a separate question"),
        _one_thread("t3", "@carol", "and one more thing"),
    ])


@pytest.fixture
def batch_session():
    """One thread, three responders: one packet, three targets."""

    replies = [
        message("r1", "@alice", "actually you are wrong",
                "2026-07-02T00:00:00Z", likes=9),
        message("r2", "@bob", "@alice she has a point",
                "2026-07-02T01:00:00Z"),
        message("r3", "@carol", "and one more thing", "2026-07-02T02:00:00Z"),
    ]
    thread = OwnerThread(
        comment=message("mine", "@owner", "my comment", "2026-07-01T00:00:00Z",
                        channel=OWNER),
        replies=replies,
    )
    return _session([
        (thread, build_reply_candidates(OWNER, "@owner", replies, "mine")),
    ])


# --------------------------------------------------------------------------
# Whole-thread selection
# --------------------------------------------------------------------------


class _Candidate:
    def __init__(self, author, thread_id):
        self.author = author
        self.thread_id = thread_id


def test_selection_keeps_whole_threads_under_a_limit():
    """A limit that splits a thread's candidates would still answer the
    dropped people, because one packet answers the thread."""

    candidates = [
        _Candidate("@alice", "t1"),
        _Candidate("@carol", "t2"),
        _Candidate("@bob", "t1"),
    ]

    selected = whole_thread_selection(candidates, 1)

    assert [c.author for c in selected] == ["@alice", "@bob"]


def test_named_thread_selection_is_the_one_shared_rule():
    """The window used to re-code this with its own filter order; now the
    CLI and the GUI both call this, so they cannot drift: naming anybody
    keeps their whole thread."""

    from llm_youtube_comment_generation.application.guided_session import (
        named_thread_selection,
    )
    from llm_youtube_comment_generation.domain.candidates import (
        ReplyCandidate,
    )

    people = [
        ReplyCandidate(author="@alice", thread_id="t1"),
        ReplyCandidate(author="@bob", thread_id="t1"),
        ReplyCandidate(author="@carol", thread_id="t2"),
    ]

    kept = named_thread_selection(people, "@alice")

    assert [c.author for c in kept] == ["@alice", "@bob"]
    assert named_thread_selection(people, "") == people


def test_previous_person_steps_the_session_back_and_rebuilds(session):
    """Back is a session move or it is a lie: the rail used to step back
    alone, leaving the next thread's packet on the clipboard under the
    previous thread's name."""

    session.start()
    first = session.next_person()
    first_packet = session.current_packet
    session.skip_person()
    second = session.next_person()
    assert second.author != first.author

    again = session.previous_person()

    assert again.author == first.author
    assert session.current_packet == first_packet
    assert session.previous_person() is None      # already at the first


def test_reply_to_accepts_a_list_or_a_pasted_triage_answer():
    """The legacy --reply-to. Both shapes are what the operator has to
    hand: handles he typed, or the triage answer on his clipboard."""

    from llm_youtube_comment_generation.application.guided_session import (
        named_selection,
    )
    from llm_youtube_comment_generation.domain.candidates import (
        ReplyCandidate,
    )

    people = [
        ReplyCandidate(author="@alice", thread_id="t1"),
        ReplyCandidate(author="@bob", thread_id="t2"),
        ReplyCandidate(author="@carol", thread_id="t3"),
    ]

    typed = named_selection(people, "@alice, @carol")
    assert [c.author for c in typed] == ["@alice", "@carol"]

    pasted = named_selection(people, (
        "@bob | 1 | asks for a source\n"
        "@alice | 2 | substantive challenge\n"
        "SKIP: @carol"
    ))
    assert [c.author for c in pasted] == ["@alice", "@bob"]
    assert named_selection(people, "") == people


def test_reply_to_naming_nobody_present_refuses():
    """An emptied queue reads as "nobody is waiting", which is the one
    thing it must never say by accident."""

    from llm_youtube_comment_generation.application.guided_session import (
        named_selection,
    )
    from llm_youtube_comment_generation.domain.candidates import (
        ReplyCandidate,
    )
    from llm_youtube_comment_generation.domain.errors import (
        ConfigurationError,
    )

    people = [ReplyCandidate(author="@alice", thread_id="t1")]

    with pytest.raises(ConfigurationError, match="None of the"):
        named_selection(people, "@nobody")
    with pytest.raises(ConfigurationError, match="No handles were found"):
        named_selection(people, "just prose")


def test_an_all_skip_triage_answer_refuses_with_the_truth():
    """The live strand of 2026-08-15: GPT answered "SKIP: @TotalAFOL,
    @TotalAFOL" and the refusal said "No handles were found... paste the
    triage answer" — accusing the operator of a bad paste when the model
    had delivered a verdict. The refusal must say what happened and name
    a way forward."""

    from llm_youtube_comment_generation.application.guided_session import (
        named_selection,
    )
    from llm_youtube_comment_generation.domain.candidates import (
        ReplyCandidate,
    )
    from llm_youtube_comment_generation.domain.errors import (
        ConfigurationError,
    )

    people = [ReplyCandidate(author="@TotalAFOL", thread_id="t1")]

    with pytest.raises(ConfigurationError, match="picked nobody") as caught:
        named_selection(people, "SKIP: @TotalAFOL, @TotalAFOL")

    assert "No handles were found" not in str(caught.value)
    assert "without triage" in str(caught.value)


def test_top_repliers_keeps_the_most_liked_in_scan_order():
    """The legacy --top-repliers: rank by what the room liked, then hand
    the queue back in its own order rather than re-ranking it."""

    from llm_youtube_comment_generation.application.guided_session import (
        top_replier_selection,
    )
    from llm_youtube_comment_generation.domain.candidates import (
        ReplyCandidate,
    )

    people = [
        ReplyCandidate(author="@quiet", reply={"like_count": 1},
                       thread_id="t1"),
        ReplyCandidate(author="@loud", reply={"like_count": 40},
                       thread_id="t2"),
        ReplyCandidate(author="@middle", reply={"like_count": 9},
                       thread_id="t3"),
    ]

    kept = top_replier_selection(people, 2)

    assert [c.author for c in kept] == ["@loud", "@middle"]
    assert top_replier_selection(people, 0) == people


def test_per_thread_adds_threads_with_no_outstanding_person():
    """The legacy per-comment option: a thread whose replies were all
    answered still disappears from the queue, and with it the chance to
    answer whoever posted there since."""

    from llm_youtube_comment_generation.application.guided_session import (
        every_thread_selection,
    )
    from llm_youtube_comment_generation.domain.candidates import (
        ReplyCandidate,
    )

    answered_thread = OwnerThread(
        comment=message("t2", "@owner", "my other comment",
                        "2026-07-01T00:00:00Z", channel=OWNER),
        replies=[message("x1", "@dave", "already answered",
                         "2026-07-02T00:00:00Z")],
    )
    silent_thread = OwnerThread(
        comment=message("t3", "@owner", "nobody replied here",
                        "2026-07-01T00:00:00Z", channel=OWNER),
    )
    waiting = [ReplyCandidate(author="@alice", reply={"comment_id": "r1"},
                              thread_id="t1")]

    widened = every_thread_selection(
        waiting, [answered_thread, silent_thread])

    assert [c.thread_id for c in widened] == ["t1", "t2"]
    assert widened[1].author == "@dave"


def test_selection_without_a_limit_keeps_everyone_in_order():
    candidates = [
        _Candidate("@alice", "t1"),
        _Candidate("@bob", "t2"),
    ]

    assert whole_thread_selection(candidates) == candidates


# --------------------------------------------------------------------------
# A whole run
# --------------------------------------------------------------------------


def test_a_whole_run_walks_every_thread_and_writes_the_file(session):
    session.start()

    while session.next_person() is not None:
        session.copy_packet()
        session.submit(sheet_for(session))

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
    session.submit(sheet_for(session))

    assert history.entries == []
    assert session.record_posted(0) == 1

    recorded = history.entries[0]
    assert recorded["workflow"] == "reply"
    assert recorded["target_comment_id"] == "t1-r1"
    assert recorded["thread_id"] == "t1"
    assert recorded["operator_channel_id"] == OWNER
    assert session.accepted[0].posted_recorded
    assert "posting recorded: yes" in session.artifacts.read(REVIEW_FILENAME)


def test_history_records_one_row_per_manually_posted_reply(batch_session):
    """Three replies accepted from one sheet; each posting is its own
    confirmation and its own history row."""

    history = RecordingHistory()
    batch_session.history = history
    batch_session.start()
    batch_session.next_person()
    batch_session.submit(sheet_for(batch_session))

    assert len(batch_session.accepted) == 3
    assert batch_session.record_posted(0) == 1
    assert batch_session.record_posted(1) == 1
    assert batch_session.record_posted(1) == 0        # already recorded

    assert [row["target_comment_id"] for row in history.entries] \
        == ["r1", "r2"]


def test_every_accepted_sheet_is_saved_before_the_next_thread_starts(session):
    """Not at the end. A run that saves at the end loses everything to the
    first interruption."""

    session.start()
    session.next_person()
    session.submit(sheet_for(session, lambda t: "the first reply"))

    saved = session.artifacts.read(REVIEW_FILENAME)

    assert "the first reply" in saved
    assert len(session.accepted) == 1


def test_an_interrupted_run_keeps_what_was_already_accepted(session):
    session.start()
    session.next_person()
    session.submit(sheet_for(session, lambda t: "first reply"))
    session.next_person()

    session.cancel()

    assert session.state.phase is Phase.CANCELLED
    assert "first reply" in session.artifacts.read(REVIEW_FILENAME)


def test_the_real_set_survives_a_skip_in_the_middle(session):
    session.start()

    first = session.next_person()
    session.submit(sheet_for(session))

    middle = session.next_person()
    session.skip_person()

    last = session.next_person()
    session.submit(sheet_for(session))
    session.finish()

    review = session.artifacts.read(REVIEW_FILENAME)

    assert len({first.author, middle.author, last.author}) == 3
    assert len(session.accepted) == 2
    assert session.skipped == [middle.author]
    assert "## Skipped" in review
    assert middle.author in review.split("## Skipped")[1]


def test_skipping_every_thread_still_finishes(session):
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
# One packet per owner thread
# --------------------------------------------------------------------------


def test_a_mixed_run_walks_two_threads_and_keeps_every_draft(batch_session):
    """The review's integration fixture: two responses in thread A plus one
    in thread B mean exactly two packets, a skip that lands in the session's
    ledger, and no stale state at exhaustion."""

    extra_replies = [
        message("s1", "@dave", "a question on the other video comment",
                "2026-07-02T00:00:00Z"),
    ]
    extra = OwnerThread(
        comment=message("second", "@owner", "my other comment",
                        "2026-07-01T00:00:00Z", channel=OWNER),
        replies=extra_replies,
    )
    batch_session.threads["second"] = extra
    batch_session.targets.extend(
        build_reply_candidates(OWNER, "@owner", extra_replies, "second"))

    batch_session.start()
    assert batch_session.thread_queue() == ["mine", "second"]

    batch_session.next_person()
    assert len(batch_session.current_targets) == 3
    batch_session.submit(sheet_for(batch_session))

    batch_session.next_person()
    assert [t.comment_id for t in batch_session.current_targets] == ["s1"]
    batch_session.skip_person()

    assert batch_session.next_person() is None
    batch_session.finish()

    assert len(batch_session.accepted) == 3        # thread A only
    assert batch_session.skipped                   # thread B is on record
    review = batch_session.artifacts.read(REVIEW_FILENAME)
    assert "## Skipped" in review


def test_several_candidates_in_one_thread_get_one_packet(batch_session):
    """Three candidates point at the same thread. Building a packet per
    candidate would ask the model the same question three times and hand the
    operator three conflicting sheets."""

    batch_session.start()

    assert batch_session.thread_queue() == ["mine"]
    assert batch_session.state.total_targets == 1

    batch_session.next_person()
    assert len(batch_session.current_targets) == 3

    assert batch_session.next_person() is None


def test_one_sheet_accepts_every_target_separately(batch_session):
    batch_session.start()
    batch_session.next_person()

    result = batch_session.submit(sheet_for(batch_session))

    assert result.status is OperationStatus.SUCCEEDED
    assert [d.comment_id for d in batch_session.accepted] == ["r1", "r2", "r3"]
    assert [d.author for d in batch_session.accepted] \
        == ["@alice", "@bob", "@carol"]
    assert {d.thread_id for d in batch_session.accepted} == {"mine"}
    assert [d.status for d in batch_session.accepted] \
        == ["direct", "nested", "direct"]
    assert batch_session.accepted[0].draft == "reply to @alice"


def test_a_guided_packet_discloses_the_scans_retrieval_outcome(batch_session):
    """Guided and direct CLI builds must make the same completeness claim;
    the second review caught guided packets substituting the default."""

    from llm_youtube_comment_generation.domain.statuses import (
        RetrievalOutcome,
        RetrievalStatus,
    )

    batch_session.retrieval = RetrievalOutcome(
        status=RetrievalStatus.TOP_LEVEL_TRUNCATED,
        notes=("the newest replies were not reached",),
    )
    batch_session.start()
    batch_session.next_person()

    assert "- status: top_level_truncated" in batch_session.current_packet
    assert "the newest replies were not reached" in \
        batch_session.current_packet


def test_their_text_is_each_targets_own_response(batch_session):
    batch_session.start()
    batch_session.next_person()
    batch_session.submit(sheet_for(batch_session))

    assert batch_session.accepted[0].their_text == "actually you are wrong"
    assert batch_session.accepted[1].their_text == "@alice she has a point"


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


def test_packet_detection_runs_before_parsing(session):
    """The packet describes the sheet format in its own instructions, so
    parsing it would find sheet-shaped text: an answer that looks like an
    answer, about to be posted under the operator's own name."""

    session.start()
    session.next_person()
    packet = session.copy_packet()

    assert "# Copy/Paste Replies" in packet
    result = session.submit(packet)

    assert result.status is OperationStatus.REFUSED
    assert "the packet, not an answer" in session.state.last_error


def test_an_answer_that_is_not_a_sheet_is_refused(session):
    session.start()
    session.next_person()

    result = session.submit("Here are some thoughts but no sheet at all.")

    assert result.status is OperationStatus.REFUSED
    assert "Post beneath comment ID" in session.state.last_error
    assert session.accepted == []


def test_a_sheet_missing_a_target_is_refused_whole(batch_session):
    """Accepting the parseable half would post some people's replies while
    silently dropping the rest, and the dropped ones would look answered."""

    batch_session.start()
    batch_session.next_person()
    partial = sheet_for(batch_session)
    partial = partial[:partial.index("**Post beneath comment ID:** r3")]

    result = batch_session.submit(partial)

    assert result.status is OperationStatus.REFUSED
    assert "r3" in batch_session.state.last_error
    assert batch_session.accepted == []


def test_a_sheet_with_an_unknown_target_is_refused(batch_session):
    batch_session.start()
    batch_session.next_person()
    forged = sheet_for(batch_session).replace(
        "**Post beneath comment ID:** r2",
        "**Post beneath comment ID:** r999",
    )

    result = batch_session.submit(forged)

    assert result.status is OperationStatus.REFUSED
    assert "r999" in batch_session.state.last_error
    assert batch_session.accepted == []


def test_metadata_outside_the_code_blocks_never_becomes_a_draft(batch_session):
    batch_session.start()
    batch_session.next_person()
    batch_session.submit(sheet_for(batch_session))

    for draft in batch_session.accepted:
        assert "Post beneath" not in draft.draft
        assert "Relationship" not in draft.draft
        assert "###" not in draft.draft


def test_a_refusal_keeps_the_same_thread_so_it_can_be_pasted_again(session):
    session.start()
    person = session.next_person()

    session.submit("unreadable")
    assert session.current is person

    session.submit(sheet_for(session, lambda t: "the real reply"))

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
    session.submit(sheet_for(
        session, lambda t: "The finished reply, exactly as written."))
    session.finish()

    review = session.artifacts.read(REVIEW_FILENAME)

    assert "The finished reply, exactly as written." in review
    assert "**Your reply:**" in review


def test_the_review_file_shows_what_they_said_for_context(session):
    session.start()
    session.next_person()
    session.submit(sheet_for(session))
    session.finish()

    review = session.artifacts.read(REVIEW_FILENAME)

    assert "actually you are wrong" in review
    assert "**They said:**" in review


def test_the_review_file_says_nothing_was_posted(session):
    """This tool never posts. The file must not imply otherwise."""

    session.start()
    session.next_person()
    session.submit(sheet_for(session))
    session.finish()

    assert "Nothing here has been posted" in \
        session.artifacts.read(REVIEW_FILENAME)


def test_the_session_is_the_only_writer_of_the_review_file(session):
    """One writer means the file cannot be half-written by two paths that
    disagree about its shape."""

    session.start()
    session.next_person()
    session.submit(sheet_for(session))
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


# --------------------------------------------------------------------------
# Debug build
# --------------------------------------------------------------------------


def test_a_debug_reply_session_renders_a_complete_bundle():
    """The Debug build checkbox in reply mode. The window always asked the
    session for these fields and until 2026-08-15 they did not exist, so
    the checkbox was live and did nothing — the shipped-disabled-control
    rule broken quietly."""

    session = _session([
        _one_thread("t1", "@alice", "actually you are wrong", likes=9),
    ])
    session.debug_build = True
    session.debug_settings = {"mode": "reply", "dials": {}}

    assert session.debug_bundle() != ""    # settings render before any paste

    session.start()
    session.next_person()
    session.copy_packet()
    session.submit(sheet_for(session))

    bundle = session.debug_bundle()
    assert "Safe build settings" in bundle
    assert '"mode": "reply"' in bundle
    assert "# Copy/Paste Replies" in bundle          # the exact response
    assert "reply to @alice" in bundle               # the saved draft
    assert "Accepted." in bundle


def test_a_refused_debug_paste_is_kept_with_its_reason():
    """The refused response is the one a bug report needs most."""

    session = _session([
        _one_thread("t1", "@alice", "actually you are wrong"),
    ])
    session.debug_build = True
    session.start()
    session.next_person()
    session.copy_packet()

    result = session.submit("not a sheet at all")

    assert result.status is OperationStatus.REFUSED
    bundle = session.debug_bundle()
    assert "not a sheet at all" in bundle
    assert "Accepted." not in bundle


def test_without_the_checkbox_the_bundle_is_empty_and_nothing_is_kept():
    session = _session([
        _one_thread("t1", "@alice", "actually you are wrong"),
    ])
    session.start()
    session.next_person()
    session.copy_packet()
    session.submit(sheet_for(session))

    assert session.debug_bundle() == ""
    assert session.debug_response == ""
