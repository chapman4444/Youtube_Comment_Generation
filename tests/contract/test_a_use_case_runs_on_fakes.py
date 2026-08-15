"""The shipped use cases run end-to-end on fakes, with no I/O.

This file started life as Phase 2's acceptance test, with a toy use case
defined inside the test because the real ones did not exist yet. The real
ones landed and the toy stayed, so seven green tests were asserting nothing
about shipped code while counting toward the pass tally — the harsh-critic
review's stale-use-case finding. What runs here now is the application
layer itself: ``scan_threads.handle`` (who under my comment is owed a
reply) and ``inspect_video.handle`` (retrieve a video and report honestly),
composed over the same fakes.

The "no I/O" half needs no assertion of its own. The harness forbids
sockets, subprocesses and desktop launches by default and fails any test
that reaches for them, so these passing IS the proof: if a handler touched
the network, it would error rather than pass.
"""

from __future__ import annotations

from fakes import (
    FakeClock,
    FakeEventSink,
    FakeTranscriptPort,
    FakeYouTubePort,
)
from llm_youtube_comment_generation.application.commands import (
    InspectVideoCommand,
)
from llm_youtube_comment_generation.application.inspect_video import (
    handle as inspect_video,
)
from llm_youtube_comment_generation.application.scan_threads import (
    ScanMyThreadsCommand,
    handle as scan_threads,
)
from llm_youtube_comment_generation.domain.statuses import (
    OperationStatus,
    TranscriptAvailability,
    WarningCode,
)
from llm_youtube_comment_generation.ports.events import EventKind

OWNER = "UC" + "o" * 22
VIDEO = "gC-J7zwYMAM"


def build_youtube(**overrides):
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
    options = {
        "videos": {VIDEO: {"video_id": VIDEO, "title": "A video",
                           "channel_id": "UC" + "z" * 22}},
        "comments": comments,
        "replies": replies,
        "handles": {"@owner": OWNER},
    }
    options.update(overrides)
    return FakeYouTubePort(**options)


def scan(youtube=None, **command_overrides):
    options = {"video": VIDEO, "handle": "@owner"}
    options.update(command_overrides)
    return scan_threads(
        ScanMyThreadsCommand(**options),
        youtube=youtube or build_youtube(),
        events=FakeEventSink(),
        clock=FakeClock(),
    )


def test_the_scan_use_case_runs_end_to_end_on_fakes_alone():
    """No network, no filesystem, no display — and it is the real handler,
    so what this proves is the shipped composition, not a stand-in."""

    result = scan()

    assert result.ok
    assert result.status is OperationStatus.SUCCEEDED
    assert result.warnings == []

    outstanding = [c for c in result.value.candidates if c.outstanding]
    assert [c.author for c in outstanding] == ["@alice"]
    assert outstanding[0].replied_again is True
    assert result.metrics["outstanding"] == 1
    assert result.value.scanned_comments == 2


def test_incomplete_retrieval_is_a_warning_not_a_failure():
    """A truncated scan still produces a useful queue; it just must not be
    presented as proof that nobody else is waiting."""

    youtube = build_youtube()
    youtube.comments.extend(
        {"comment_id": f"filler{i}", "author": "@x",
         "author_channel_id": "UC" + "x" * 22, "text": "f",
         "like_count": 0, "total_reply_count": 0,
         "published_at": "2026-07-01T00:00:00Z"}
        for i in range(200)
    )

    result = scan(youtube=youtube, max_comments=100)

    assert result.ok is True
    assert result.status is OperationStatus.SUCCEEDED_WITH_WARNINGS
    assert any(w.code is WarningCode.RETRIEVAL_INCOMPLETE
               for w in result.warnings)
    assert not result.value.retrieval.may_conclude_absence


def test_the_since_cutoff_is_measured_by_the_clock_port():
    """--since 7 with a frozen clock at 2026-07-27 puts the cutoff at
    2026-07-20, which is after every reply in the fixture — so none are
    new, while a 60-day window catches all three."""

    week = scan(since="7")
    assert week.value.threads[0].new_replies == []

    two_months = scan(since="60")
    assert len(two_months.value.threads[0].new_replies) == 3


def test_the_use_case_reports_the_quota_it_spent():
    """Quota is finite; a use case that cannot say what it cost is
    unusable. One handle lookup, two orderings, one reply thread."""

    result = scan()

    assert result.value.api_operations_used == 4
    assert result.metrics["api_operations"] == 4


def test_the_events_describe_the_run_in_facts():
    events = FakeEventSink()
    scan_threads(
        ScanMyThreadsCommand(video=VIDEO, handle="@owner"),
        youtube=build_youtube(), events=events, clock=FakeClock(),
    )

    kinds = events.kinds()
    assert kinds[0] is EventKind.STARTED
    assert kinds[-1] is EventKind.FINISHED
    assert "scan" in events.steps()


def test_a_missing_transcript_warns_and_the_inspection_still_succeeds():
    """The transcript-bearing use case, on the same fakes: an absent
    transcript is an ordinary outcome, not a failed run."""

    result = inspect_video(
        InspectVideoCommand(video=VIDEO),
        youtube=build_youtube(),
        transcripts=FakeTranscriptPort(
            availability=TranscriptAvailability.NOT_PUBLISHED
        ),
        events=FakeEventSink(),
    )

    assert result.ok is True
    assert [w.code for w in result.warnings] == [
        WarningCode.TRANSCRIPT_UNAVAILABLE
    ]
    assert result.value.comments


def test_the_same_fakes_give_the_same_answer_twice():
    """Determinism is what makes these usable as a harness for everything
    built above them."""

    first = scan()
    second = scan()

    assert [c.author for c in first.value.candidates] == \
           [c.author for c in second.value.candidates]
    assert first.metrics == second.metrics
