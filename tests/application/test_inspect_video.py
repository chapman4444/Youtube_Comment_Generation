"""The inspect use case, with the honesty rules a live run exposed.

Every test here was written because a real run against a real video reported
something it could not support.
"""

from __future__ import annotations

from fakes import FakeEventSink, FakeTranscriptPort, FakeYouTubePort
from llm_youtube_comment_generation.application import inspect_video
from llm_youtube_comment_generation.application.commands import InspectVideoCommand
from llm_youtube_comment_generation.application.inspect_video import (
    REPLY_THREAD_LIMIT,
)
from llm_youtube_comment_generation.domain.statuses import (
    RetrievalOutcome,
    RetrievalStatus,
    WarningCode,
)

VIDEO = "gC-J7zwYMAM"


def comment(index, replies=0):
    return {
        "comment_id": f"c{index}",
        "author": f"@u{index}",
        "author_channel_id": "UC" + str(index).ljust(22, "z"),
        "text": "a comment body here",
        "like_count": index,
        "total_reply_count": replies,
        "published_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
    }


def run(comments, *, reported_total=None, include_replies=False, replies=None):
    youtube = FakeYouTubePort(
        videos={VIDEO: {"video_id": VIDEO, "title": "t",
                        "comment_count": reported_total}},
        comments=comments,
        replies=replies or {},
    )
    return inspect_video.handle(
        InspectVideoCommand(VIDEO, max_comments=1000,
                            include_replies=include_replies),
        youtube=youtube,
        transcripts=FakeTranscriptPort(),
        events=FakeEventSink(),
    )


def test_a_clean_run_may_conclude_absence():
    result = run([comment(1), comment(2)], reported_total=2)

    assert result.value.retrieval.may_conclude_absence is True
    assert result.warnings == []


def test_a_complete_scan_with_a_shortfall_may_not_conclude_absence():
    """The exact contradiction a live run produced.

    It reported complete: true and missing: 18 in the same output, and then
    said it could be used to prove a comment absent. Every individual scan
    had finished; that is not the same as having seen everything.
    """

    result = run([comment(1), comment(2)], reported_total=110)
    retrieval = result.value.retrieval

    assert retrieval.status is RetrievalStatus.COMPLETE
    assert retrieval.missing == 108
    assert retrieval.has_shortfall is True
    assert retrieval.may_conclude_absence is False
    assert [w.code for w in result.warnings] == [WarningCode.RETRIEVAL_INCOMPLETE]
    assert "108 fewer" in result.warnings[0].message


def test_an_unknown_reported_total_is_not_treated_as_a_shortfall():
    """None means "YouTube did not say", not "zero"."""

    result = run([comment(1)], reported_total=None)

    assert result.value.retrieval.missing is None
    assert result.value.retrieval.has_shortfall is False
    assert result.value.retrieval.may_conclude_absence is True


def test_the_reply_thread_cap_is_reported_rather_than_applied_silently():
    """A limit the caller cannot see is indistinguishable from an absence."""

    comments = [comment(i, replies=3) for i in range(REPLY_THREAD_LIMIT + 5)]
    replies = {f"c{i}": [comment(100 + i)] for i in range(len(comments))}

    result = run(comments, include_replies=True, replies=replies)
    retrieval = result.value.retrieval

    assert retrieval.status is RetrievalStatus.REPLY_THREAD_TRUNCATED
    assert retrieval.may_conclude_absence is False
    assert any("busiest threads" in note for note in retrieval.notes)


def test_the_cap_is_silent_when_it_does_not_bite():
    """A guard that fires when nothing was skipped trains the reader to
    ignore it."""

    comments = [comment(i, replies=1) for i in range(3)]
    replies = {f"c{i}": [comment(100 + i)] for i in range(3)}

    result = run(comments, include_replies=True, replies=replies)

    assert result.value.retrieval.status is RetrievalStatus.COMPLETE
    assert not any("busiest threads" in n for n in result.value.retrieval.notes)


def test_each_gui_retrieval_limit_controls_its_own_dimension():
    seen_comments = []
    seen_replies = []

    class RecordingYouTube(FakeYouTubePort):
        def comment_threads(self, video_id, *, order="relevance", maximum=100):
            seen_comments.append((order, maximum))
            return super().comment_threads(
                video_id,
                order=order,
                maximum=maximum,
            )

        def replies(self, parent_comment_id, *, maximum=100):
            seen_replies.append((parent_comment_id, maximum))
            return super().replies(parent_comment_id, maximum=maximum)

    comments = [comment(i, replies=1) for i in range(8)]
    youtube = RecordingYouTube(
        videos={VIDEO: {"video_id": VIDEO, "title": "t", "comment_count": 8}},
        comments=comments,
        replies={f"c{i}": [comment(100 + i)] for i in range(8)},
    )

    inspect_video.handle(
        InspectVideoCommand(
            VIDEO,
            max_relevance_comments=3,
            max_recent_comments=5,
            max_reply_threads=2,
            max_replies_per_thread=7,
            include_replies=True,
        ),
        youtube=youtube,
        transcripts=FakeTranscriptPort(),
        events=FakeEventSink(),
    )

    assert seen_comments == [("relevance", 3), ("time", 5)]
    assert len(seen_replies) == 2
    assert all(maximum == 7 for _, maximum in seen_replies)


def test_the_worst_scan_decides_the_reported_status():
    """A run is only as honest as its weakest scan."""

    assert inspect_video.worst([
        RetrievalOutcome(status=RetrievalStatus.COMPLETE),
        RetrievalOutcome(status=RetrievalStatus.PAGE_TOKEN_LOOP),
        RetrievalOutcome(status=RetrievalStatus.COMPLETE),
    ]) is RetrievalStatus.PAGE_TOKEN_LOOP

    assert inspect_video.worst([]) is RetrievalStatus.COMPLETE


def test_a_dry_run_spends_nothing_and_returns_early():
    youtube = FakeYouTubePort(videos={VIDEO: {"video_id": VIDEO}})

    result = inspect_video.handle(
        InspectVideoCommand(VIDEO, dry_run=True),
        youtube=youtube,
        transcripts=FakeTranscriptPort(),
        events=FakeEventSink(),
    )

    assert result.value.dry_run is True
    assert youtube.api_operations_used == 0
    assert result.metrics["api_operations"] == 0
