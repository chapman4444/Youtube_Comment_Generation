"""The scoreboard, and the one claim it must never make.

An incomplete scan cannot tell "this reply is not there" from "I did not look
far enough". Reporting the first when only the second is known would quietly
invalidate every conclusion drawn from these numbers.
"""

from __future__ import annotations

from fakes import FakeEventSink, FakeHistoryStore, FakeYouTubePort
from llm_youtube_comment_generation.application import scoreboard
from llm_youtube_comment_generation.domain.statuses import (
    HistoryMatchStatus,
    RetrievalOutcome,
    RetrievalStatus,
    WarningCode,
)
from llm_youtube_comment_generation.ports.youtube import CommentPage

VIDEO = "gC-J7zwYMAM"
OWNER = "UC" + "o" * 22


def posted(text, likes=0, replies=0, channel=OWNER):
    return {
        "comment_id": f"c{abs(hash(text)) % 10000}",
        "text": text,
        "like_count": likes,
        "total_reply_count": replies,
        "published_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
        "author_channel_id": channel,
        "is_reply": False,
    }


def run(drafts, live, *, max_comments=2000):
    return scoreboard.handle(
        VIDEO,
        history=FakeHistoryStore(drafts),
        youtube=FakeYouTubePort(comments=live),
        events=FakeEventSink(),
        operator_channel_id=OWNER,
        max_comments=max_comments,
    )


def test_a_posted_draft_is_found_with_its_likes():
    result = run(
        [{"video_id": VIDEO, "draft": "the argument here is settled"}],
        [posted("the argument here is settled", likes=42)],
    )
    board = result.value

    assert len(board.matched) == 1
    assert board.total_likes == 42
    assert board.matched[0]["match_status"] == HistoryMatchStatus.MATCHED


def test_a_draft_that_was_never_posted_is_reported_as_not_found():
    result = run(
        [{"video_id": VIDEO, "draft": "a reply that never went out"}],
        [posted("something else entirely")],
    )

    assert len(result.value.unmatched) == 1
    assert result.value.counted is True


def test_an_incomplete_scan_never_reports_a_draft_as_unposted():
    """The load-bearing refusal.

    With more comments than the scan requested, the retrieval is truncated,
    and a truncated scan may not conclude absence.
    """

    live = [posted(f"unrelated comment {i}") for i in range(60)]
    result = run(
        [{"video_id": VIDEO, "draft": "a reply that may or may not be there"}],
        live,
        max_comments=10,
    )
    board = result.value

    assert board.retrieval.status is RetrievalStatus.TOP_LEVEL_TRUNCATED
    assert board.counted is False
    assert board.unmatched == []
    assert len(board.ambiguous) == 1
    assert board.ambiguous[0]["unmatched_because_scan_incomplete"] is True
    assert any(w.code is WarningCode.RETRIEVAL_INCOMPLETE
               for w in result.warnings)


def test_locally_truncated_adapter_results_never_render_as_not_found():
    class LocallyTruncatedYouTube:
        api_operations_used = 1

        def comment_threads(self, video_id, *, order, maximum):
            return CommentPage(
                comments=[posted("one retained comment")],
                outcome=RetrievalOutcome(
                    status=RetrievalStatus.TOP_LEVEL_TRUNCATED,
                    retrieved=1,
                    notes=("the response exceeded the requested allowance",),
                ),
            )

    result = scoreboard.handle(
        VIDEO,
        history=FakeHistoryStore([{
            "video_id": VIDEO,
            "draft": "the discarded response item may be this draft",
        }]),
        youtube=LocallyTruncatedYouTube(),
        events=FakeEventSink(),
        operator_channel_id=OWNER,
        max_comments=1,
    )

    assert result.value.unmatched == []
    assert len(result.value.ambiguous) == 1
    assert "## Not found on YouTube" not in scoreboard.render(result.value)


def test_the_incompleteness_is_stated_in_the_rendered_scoreboard():
    live = [posted(f"unrelated {i}") for i in range(60)]
    result = run([{"video_id": VIDEO, "draft": "a reply"}], live,
                 max_comments=10)

    text = scoreboard.render(result.value)

    assert "This scan was incomplete" in text
    assert "did not look far enough" in text


def test_one_live_reply_is_never_credited_to_two_drafts():
    """Double counting silently doubles the only numbers this project has."""

    result = run(
        [
            {"video_id": VIDEO, "draft": "the same opening and one ending"},
            {"video_id": VIDEO, "draft": "the same opening and another ending"},
        ],
        [posted("the same opening and one ending", likes=40)],
    )

    assert len(result.value.matched) == 1
    assert result.value.total_likes == 40


def test_an_ambiguous_draft_is_not_reported_as_a_finding():
    opening = "the shared opening contains enough specific words to compare safely"
    result = run(
        [{"video_id": VIDEO, "draft": opening}],
        [
            posted(opening + " and one tail", likes=1),
            posted(opening + " and another tail", likes=2),
        ],
    )

    assert len(result.value.ambiguous) == 1
    assert result.value.matched == []


def test_matching_text_from_another_channel_is_not_credited():
    text = "the operator and another channel happened to use identical text"

    result = run(
        [{"video_id": VIDEO, "draft": text}],
        [posted(text, likes=99, channel="UC" + "x" * 22)],
    )

    assert result.value.matched == []
    assert len(result.value.unmatched) == 1


def test_drafts_for_other_videos_are_not_scored():
    result = run(
        [
            {"video_id": VIDEO, "draft": "this video"},
            {"video_id": "other", "draft": "another video"},
        ],
        [posted("this video", likes=5)],
    )

    assert len(result.value.rows) == 1


def test_an_empty_history_renders_without_pretending_to_a_finding():
    result = run([], [])

    text = scoreboard.render(result.value)

    assert "No drafts have been recorded yet" in text
    assert result.metrics["drafts"] == 0


def test_the_rendered_scoreboard_states_what_it_is_evidence_of():
    result = run(
        [{"video_id": VIDEO, "draft": "a posted reply"}],
        [posted("a posted reply", likes=3)],
    )

    text = scoreboard.render(result.value)

    assert "What this is evidence of" in text
    assert "retrieval: complete" in text


def test_found_replies_are_ordered_by_what_they_earned():
    result = run(
        [
            {"video_id": VIDEO, "draft": "the quiet one"},
            {"video_id": VIDEO, "draft": "the popular one"},
        ],
        [posted("the quiet one", likes=1), posted("the popular one", likes=99)],
    )

    text = scoreboard.render(result.value)

    assert text.index("the popular one") < text.index("the quiet one")
