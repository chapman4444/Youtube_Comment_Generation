"""Phase 2's acceptance criterion, stated as a test.

"A use case can be written against fakes with no I/O." This composes every
port into one read-only flow and runs it. It is not the real use case — that
is Phase 3 — it is proof that the seams hold.

The "no I/O" half needs no assertion of its own. The harness forbids sockets,
subprocesses and desktop launches by default and fails any test that reaches
for them, so this test passing IS the proof: if composing the ports touched
the network, it would error rather than pass.
"""

from __future__ import annotations

from fakes import (
    FakeArtifactStore,
    FakeClipboard,
    FakeClock,
    FakeEventSink,
    FakeHistoryStore,
    FakeSettingsStore,
    FakeTranscriptPort,
    FakeYouTubePort,
)
from llm_youtube_comment_generation.domain.candidates import (
    candidates_across_threads,
)
from llm_youtube_comment_generation.domain.comments import merge_comments
from llm_youtube_comment_generation.domain.section_profile import (
    length_rule_for,
    measure_comment_register,
)
from llm_youtube_comment_generation.domain.statuses import (
    OperationResult,
    OperationStatus,
    RetrievalStatus,
    TranscriptAvailability,
    WarningCode,
)
from llm_youtube_comment_generation.domain.threads import OwnerThread, parse_since
from llm_youtube_comment_generation.ports.events import EventKind, ProgressEvent

OWNER = "UC" + "o" * 22
VIDEO = "gC-J7zwYMAM"


def build_ports(**overrides):
    comments = [
        {"comment_id": "c1", "author": "@owner", "author_channel_id": OWNER,
         "text": "my top level comment", "like_count": 40,
         "total_reply_count": 3, "published_at": "2026-07-01T00:00:00Z"},
        {"comment_id": "c2", "author": "@stranger",
         "author_channel_id": "UC" + "s" * 22, "text": "someone else entirely",
         "like_count": 5, "total_reply_count": 0,
         "published_at": "2026-07-02T00:00:00Z"},
    ]
    replies = {"c1": [
        {"comment_id": "r1", "author": "@alice",
         "author_channel_id": "UC" + "a" * 22,
         "text": "actually the source says otherwise, and here is why",
         "like_count": 12, "published_at": "2026-07-03T00:00:00Z"},
        {"comment_id": "r2", "author": "@owner", "author_channel_id": OWNER,
         "text": "@alice no, read it again", "like_count": 0,
         "published_at": "2026-07-04T00:00:00Z"},
        {"comment_id": "r3", "author": "@alice",
         "author_channel_id": "UC" + "a" * 22,
         "text": "you did not address the second half of it",
         "like_count": 3, "published_at": "2026-07-05T00:00:00Z"},
    ]}
    ports = {
        "youtube": FakeYouTubePort(
            videos={VIDEO: {"video_id": VIDEO, "title": "A video",
                            "channel_id": "UC" + "z" * 22}},
            comments=comments,
            replies=replies,
            handles={"@owner": OWNER},
        ),
        "transcripts": FakeTranscriptPort(),
        "clock": FakeClock(),
        "clipboard": FakeClipboard(),
        "artifacts": FakeArtifactStore(),
        "history": FakeHistoryStore(),
        "settings": FakeSettingsStore(),
        "events": FakeEventSink(),
    }
    ports.update(overrides)
    return ports


def find_outstanding(ports) -> OperationResult:
    """A read-only use case: who under my comment is still owed a reply.

    Written the way Phase 3 onward will write them — every dependency is a
    port, every branch on external state is a typed status, and the return is
    an OperationResult carrying warnings that are not errors.
    """

    youtube, events = ports["youtube"], ports["events"]
    result = OperationResult()

    events.emit(ProgressEvent(EventKind.STARTED, step="inspect"))
    owner_channel = youtube.channel_id_for_handle("@owner")
    youtube.video(VIDEO)

    pages = [youtube.comment_threads(VIDEO, order=order, maximum=100)
             for order in ("relevance", "time")]
    for page in pages:
        if not page.outcome.is_complete:
            result.warn(
                WarningCode.RETRIEVAL_INCOMPLETE,
                f"retrieved {page.outcome.retrieved:,} of "
                f"{page.outcome.reported_total:,}",
            )
    comments = merge_comments([page.comments for page in pages])

    transcript = ports["transcripts"].fetch(VIDEO)
    if not transcript.available:
        result.warn(WarningCode.TRANSCRIPT_UNAVAILABLE, transcript.detail)

    mine = [c for c in comments if c.get("author_channel_id") == owner_channel]
    threads = []
    for comment in mine:
        page = youtube.replies(comment["comment_id"], maximum=100)
        if not page.outcome.is_complete:
            result.warn(WarningCode.RETRIEVAL_INCOMPLETE, "thread truncated")
        threads.append(OwnerThread(
            comment=comment,
            replies=page.comments,
            reported_reply_count=comment.get("total_reply_count", 0),
        ))

    candidates = candidates_across_threads(owner_channel, threads)
    register = measure_comment_register(comments)

    events.emit(ProgressEvent(
        EventKind.FINISHED, step="inspect",
        current=len(candidates), total=len(candidates),
    ))

    result.value = {
        "candidates": candidates,
        "outstanding": [c for c in candidates if c.outstanding],
        "length_rule": length_rule_for(register),
        "requests_used": youtube.requests_used,
        "cutoff": parse_since("7", now=ports["clock"].now()),
    }
    result.metrics = {
        "comments": len(comments),
        "requests": youtube.requests_used,
    }
    return result


def test_a_use_case_runs_end_to_end_on_fakes_alone():
    """Phase 2 acceptance. No network, no filesystem, no display."""

    result = find_outstanding(build_ports())

    assert result.ok
    assert result.status is OperationStatus.SUCCEEDED
    assert result.warnings == []

    outstanding = result.value["outstanding"]
    assert [c.author for c in outstanding] == ["@alice"]
    assert outstanding[0].replied_again is True
    assert result.value["cutoff"] == "2026-07-20T12:00:00Z"
    assert result.metrics["comments"] == 2


def test_the_use_case_reports_incomplete_retrieval_as_a_warning_not_a_failure():
    """Warnings are not errors.

    A truncated scan still produces a useful answer; it just must not be
    presented as a complete one.
    """

    ports = build_ports()
    ports["youtube"].comments.extend(
        {"comment_id": f"filler{i}", "author": "@x",
         "author_channel_id": "UC" + "x" * 22, "text": "f",
         "like_count": 0, "total_reply_count": 0,
         "published_at": "2026-07-01T00:00:00Z"}
        for i in range(200)
    )

    result = find_outstanding(ports)

    assert result.ok is True
    assert result.status is OperationStatus.SUCCEEDED_WITH_WARNINGS
    assert any(w.code is WarningCode.RETRIEVAL_INCOMPLETE for w in result.warnings)


def test_a_missing_transcript_warns_and_the_run_still_succeeds():
    ports = build_ports(
        transcripts=FakeTranscriptPort(
            availability=TranscriptAvailability.NOT_PUBLISHED
        )
    )

    result = find_outstanding(ports)

    assert result.ok is True
    assert [w.code for w in result.warnings] == [WarningCode.TRANSCRIPT_UNAVAILABLE]
    assert result.value["outstanding"]


def test_the_use_case_reports_the_quota_it_spent():
    """Quota is finite; a use case that cannot say what it cost is unusable."""

    result = find_outstanding(build_ports())

    # handle + video + two orderings + one reply thread
    assert result.value["requests_used"] == 5
    assert result.metrics["requests"] == 5


def test_the_events_describe_the_run_in_facts():
    ports = build_ports()
    find_outstanding(ports)

    assert ports["events"].kinds() == [EventKind.STARTED, EventKind.FINISHED]
    assert ports["events"].steps() == ["inspect", "inspect"]
    assert ports["events"].events[-1].fraction == 1.0


def test_nothing_in_the_use_case_touched_the_clipboard_or_the_history():
    """A read-only use case must be observably read-only.

    The harness already forbids the network and the desktop; this covers the
    two stateful ports it does not, so "read-only" is asserted rather than
    assumed from the absence of a failure.
    """

    ports = build_ports()
    find_outstanding(ports)

    assert ports["clipboard"].writes == []
    assert ports["history"].load() == []
    assert ports["artifacts"].committed_names() == ()
    assert ports["artifacts"].staged_names() == ()


def test_the_same_fakes_give_the_same_answer_twice():
    """Determinism is what makes these usable for the phases that follow."""

    first = find_outstanding(build_ports())
    second = find_outstanding(build_ports())

    assert [c.author for c in first.value["outstanding"]] == \
           [c.author for c in second.value["outstanding"]]
    assert first.value["length_rule"] == second.value["length_rule"]
    assert first.metrics == second.metrics
