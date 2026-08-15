"""Thread assembly and the candidate queue.

The answered-state rules themselves are ported domain, covered in
tests/domain/test_candidates.py. These tests cover the assembly around them:
identity resolution, thread building, and the honesty of an empty queue.
"""

from __future__ import annotations

import pytest

from fakes import FakeClock, FakeEventSink, FakeYouTubePort
from llm_youtube_comment_generation.application.scan_threads import (
    ScanMyThreadsCommand,
    handle,
    select_target,
)
from llm_youtube_comment_generation.domain.errors import ConfigurationError
from llm_youtube_comment_generation.domain.statuses import (
    CandidateStatus,
    RetrievalStatus,
    WarningCode,
)

VIDEO = "gC-J7zwYMAM"
OWNER = "UC" + "o" * 22


def message(cid, author, text, when, *, channel=None, likes=0, replies=0):
    return {
        "comment_id": cid,
        "author": author,
        "author_channel_id": channel or ("UC" + author.lstrip("@").ljust(22, "z"))[:24],
        "text": text,
        "like_count": likes,
        "total_reply_count": replies,
        "published_at": when,
        "updated_at": when,
    }


def build_port(**kwargs):
    comments = kwargs.pop("comments", None)
    if comments is None:
        comments = [
            message("mine", "@owner", "my top level comment",
                    "2026-07-01T00:00:00Z", channel=OWNER, replies=3),
            message("theirs", "@stranger", "somebody else's comment",
                    "2026-07-01T00:00:00Z"),
        ]
    replies = kwargs.pop("replies", None)
    if replies is None:
        replies = {"mine": [
            message("r1", "@alice", "actually you are wrong about this",
                    "2026-07-02T00:00:00Z", likes=9),
            message("r2", "@owner", "@alice no I am not",
                    "2026-07-03T00:00:00Z", channel=OWNER),
            message("r3", "@alice", "you did not address the second half",
                    "2026-07-04T00:00:00Z"),
            message("r4", "@bob", "a separate question for you",
                    "2026-07-02T12:00:00Z"),
        ]}
    return FakeYouTubePort(
        videos={VIDEO: {"video_id": VIDEO}},
        comments=comments,
        replies=replies,
        handles={"@owner": OWNER},
        **kwargs,
    )


def scan(port=None, **command_kwargs):
    command_kwargs.setdefault("channel_id", OWNER)
    return handle(
        ScanMyThreadsCommand(VIDEO, **command_kwargs),
        youtube=port or build_port(),
        events=FakeEventSink(),
        clock=FakeClock(),
    )


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def test_a_scan_needs_to_know_who_you_are():
    """A scan with no identity treats every reply as somebody else's and
    reports an empty queue, which looks exactly like having nothing to do."""

    with pytest.raises(ConfigurationError, match="who you are"):
        ScanMyThreadsCommand(VIDEO)


def test_a_handle_is_resolved_to_a_channel_id():
    result = scan(channel_id="", handle="owner")

    assert result.value.owner_channel_id == OWNER


def test_a_malformed_channel_id_is_refused():
    with pytest.raises(ConfigurationError, match="Invalid channel ID"):
        scan(channel_id="not-a-channel")


def test_an_unknown_handle_refuses_rather_than_scanning_nothing():
    with pytest.raises(ConfigurationError, match="No channel was found"):
        scan(channel_id="", handle="nobody")


# --------------------------------------------------------------------------
# Thread assembly
# --------------------------------------------------------------------------


def test_only_the_operators_own_comments_become_threads():
    result = scan()

    assert [t.comment_id for t in result.value.threads] == ["mine"]


def test_the_queue_holds_the_people_who_addressed_you():
    result = scan()
    queue = {c.author: c for c in result.value.candidates}

    assert set(queue) == {"@alice", "@bob"}
    assert queue["@alice"].status is CandidateStatus.RETURNED_AFTER_ANSWER
    assert queue["@bob"].status is CandidateStatus.NEVER_ANSWERED


def test_every_candidate_explains_itself():
    """For a human wondering why somebody is or is not in their queue."""

    result = scan()

    for candidate in result.value.candidates:
        assert candidate.reason
        assert not candidate.reason.endswith(".")


def test_a_thread_carries_its_own_id_so_answers_do_not_leak_between_threads():
    result = scan()

    assert all(c.thread_id == "mine" for c in result.value.candidates)


def test_finding_none_of_your_comments_says_so_rather_than_reporting_nothing():
    """Silence here reads as "you have no threads", which is a different and
    much more misleading claim than "I did not find them"."""

    port = build_port(comments=[
        message("theirs", "@stranger", "not yours", "2026-07-01T00:00:00Z"),
    ], replies={})

    result = scan(port)

    assert result.value.threads == []
    assert any(w.code is WarningCode.RETRIEVAL_INCOMPLETE
               for w in result.warnings)
    assert any("Raise --max-comments" in w.message for w in result.warnings)


# --------------------------------------------------------------------------
# Honesty
# --------------------------------------------------------------------------


def test_a_truncated_thread_is_reported_and_blocks_a_claim_of_absence():
    """An empty queue implies "nobody is waiting". Only a complete scan
    earns that."""

    port = build_port(comments=[
        message("mine", "@owner", "mine", "2026-07-01T00:00:00Z",
                channel=OWNER, replies=178),
    ])

    result = scan(port)
    retrieval = result.value.retrieval

    assert retrieval.status is RetrievalStatus.REPLY_THREAD_TRUNCATED
    assert retrieval.may_conclude_absence is False
    assert any("reported 178" in note for note in retrieval.notes)
    assert any("may be missing people" in w.message for w in result.warnings)


def test_a_complete_scan_makes_no_such_warning():
    result = scan()

    assert result.value.retrieval.may_conclude_absence is True
    assert not any("may be missing people" in w.message for w in result.warnings)


def test_the_since_cutoff_marks_what_is_new_without_discarding_context():
    """Older replies remain in the thread; only "new" is marked.

    The cutoff is inclusive, so r2 — posted at exactly 2026-07-03T00:00:00Z —
    counts as new. It is the owner's own reply, and it is the audience view
    rather than this list that excludes those: "new" and "new from somebody
    else" are separate questions and the thread answers both.
    """

    result = scan(since="2026-07-03")
    thread = result.value.threads[0]

    assert len(thread.replies) == 4
    assert [r["comment_id"] for r in thread.new_replies] == ["r2", "r3"]
    assert [r["comment_id"] for r in thread.new_audience_replies(OWNER)] == ["r3"]
    assert [r["comment_id"] for r in thread.new_direct_replies(OWNER)] == ["r3"]


def test_quota_is_reported():
    result = scan()

    assert result.value.api_operations_used > 0
    assert (
        result.metrics["api_operations"]
        == result.value.api_operations_used
    )


# --------------------------------------------------------------------------
# Choosing a target
# --------------------------------------------------------------------------


def test_a_target_can_be_chosen_by_comment_id():
    result = scan()

    candidate = select_target(result.value, comment_id="r4")

    assert candidate.author == "@bob"


def test_a_target_can_be_chosen_by_handle():
    result = scan()

    assert select_target(result.value, handle="alice").author == "@alice"
    assert select_target(result.value, handle="@alice").author == "@alice"


def test_any_retrieved_response_id_selects_its_thread():
    """A candidate holds one representative message per person, but the
    packet answers the whole thread — so a non-representative response id,
    the owner's own reply id, or the owner comment id all select it."""

    result = scan()

    for identifier in ("r3", "r2", "mine"):
        candidate = select_target(result.value, comment_id=identifier)
        assert candidate.thread_id == "mine", identifier


def test_an_unknown_target_refuses():
    result = scan()

    with pytest.raises(ConfigurationError, match="Nobody called"):
        select_target(result.value, handle="@nobody")

    with pytest.raises(ConfigurationError, match="No retrieved comment"):
        select_target(result.value, comment_id="does-not-exist")


def test_choosing_nothing_refuses():
    result = scan()

    with pytest.raises(ConfigurationError, match="--comment-id or --handle"):
        select_target(result.value)


def test_an_ambiguous_handle_refuses_rather_than_choosing():
    """Two accounts sharing a display name is a thing that happens, and
    answering the wrong one is not recoverable once it is posted."""

    port = build_port(replies={"mine": [
        message("r1", "@same", "first person", "2026-07-02T00:00:00Z",
                channel="UC" + "a" * 22),
        message("r2", "@same", "different person", "2026-07-02T01:00:00Z",
                channel="UC" + "b" * 22),
    ]})

    result = scan(port)

    with pytest.raises(ConfigurationError, match="matches 2 people"):
        select_target(result.value, handle="@same")


def test_the_ambiguity_refusal_names_the_ids_to_choose_between():
    """A refusal that does not say how to proceed is a dead end."""

    port = build_port(replies={"mine": [
        message("r1", "@same", "one", "2026-07-02T00:00:00Z",
                channel="UC" + "a" * 22),
        message("r2", "@same", "two", "2026-07-02T01:00:00Z",
                channel="UC" + "b" * 22),
    ]})
    result = scan(port)

    with pytest.raises(ConfigurationError) as caught:
        select_target(result.value, handle="@same")

    assert "r1" in str(caught.value) and "r2" in str(caught.value)
