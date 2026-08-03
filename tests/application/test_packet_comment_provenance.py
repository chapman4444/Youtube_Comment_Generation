"""Packet section labels preserve the ordering YouTube supplied."""

from __future__ import annotations

from fakes import FakeArtifactStore, FakeEventSink, FakeTranscriptPort
from llm_youtube_comment_generation.application import build_comment_packet
from llm_youtube_comment_generation.application.build_comment_packet import (
    BuildCommentPacketCommand,
)
from llm_youtube_comment_generation.domain.statuses import (
    RetrievalOutcome,
    RetrievalStatus,
)
from llm_youtube_comment_generation.infrastructure import prompt_resources
from llm_youtube_comment_generation.ports.youtube import CommentPage

VIDEO = "gC-J7zwYMAM"
TEMPLATES = {
    name: prompt_resources.load(name).text
    for name in ("comment_workflow.md", "comment_final_check.md")
}


def comment(comment_id):
    return {
        "comment_id": comment_id,
        "author": "@viewer",
        "author_channel_id": "UC" + comment_id.ljust(22, "z")[:22],
        "text": f"evidence from {comment_id}",
        "like_count": 0,
        "total_reply_count": 0,
        "published_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
    }


class DifferentlyOrderedYouTube:
    def __init__(self):
        self.relevance = [comment(f"rel{i:03}") for i in range(120)]
        self.recent = [comment(f"time{i:03}") for i in range(120)]
        self.api_operations_used = 0

    def video(self, video_id):
        self.api_operations_used += 1
        return {
            "video_id": video_id,
            "title": "Different orderings",
            "description": "description",
            "comment_count": 240,
        }

    def comment_threads(self, video_id, *, order="relevance", maximum=100):
        self.api_operations_used += 1
        source = self.relevance if order == "relevance" else self.recent
        comments = [dict(item, order_source=order) for item in source[:maximum]]
        return CommentPage(
            comments=comments,
            outcome=RetrievalOutcome(
                status=RetrievalStatus.COMPLETE,
                retrieved=len(comments),
                reported_total=len(source),
                api_operations_used=1,
            ),
        )

    def replies(self, parent_comment_id, *, maximum=100):
        raise AssertionError("the test comments have no replies")


def test_relevant_and_recent_sections_use_their_own_fetched_orderings(monkeypatch):
    captured = {}
    real_fit = build_comment_packet.fit_packet_sections

    def fit(top_comments, recent_comments, evidence, options, **templates):
        selection = real_fit(
            top_comments,
            recent_comments,
            evidence,
            options,
            **templates,
        )
        captured["selection"] = selection
        captured["top"] = top_comments
        captured["recent"] = recent_comments
        captured["aggregate"] = evidence.comments
        return selection

    monkeypatch.setattr(build_comment_packet, "fit_packet_sections", fit)
    youtube = DifferentlyOrderedYouTube()

    build_comment_packet.handle(
        BuildCommentPacketCommand(video=VIDEO),
        youtube=youtube,
        transcripts=FakeTranscriptPort(),
        events=FakeEventSink(),
        artifacts=FakeArtifactStore(),
        templates=TEMPLATES,
        prompt_version="test",
    )

    selection = captured["selection"]
    assert [item["comment_id"] for item in captured["top"]] == [
        f"rel{i:03}" for i in range(120)
    ]
    assert [item["comment_id"] for item in captured["recent"]] == [
        f"time{i:03}" for i in range(120)
    ]
    assert len(captured["aggregate"]) == 240
    assert len(selection.rendered_ids) == 240
    assert len(selection.relevant) > 75
    assert all(item["comment_id"].startswith("rel")
               for item in selection.relevant)
    assert selection.recent
    assert all(item["comment_id"].startswith("time")
               for item in selection.recent)


def test_debug_build_stages_a_diagnostic_packet_without_replacing_packet():
    artifacts = FakeArtifactStore()

    result = build_comment_packet.handle(
        BuildCommentPacketCommand(
            video=VIDEO,
            debug=True,
            debug_settings={"length": "medium", "whisper_policy": "ask"},
        ),
        youtube=DifferentlyOrderedYouTube(),
        transcripts=FakeTranscriptPort(),
        events=FakeEventSink(),
        artifacts=artifacts,
        templates=TEMPLATES,
        prompt_version="test",
    )

    assert artifacts.read("packet.md") == result.value["packet"].text
    debug_packet = artifacts.read("debug_packet.md")
    assert "## Debug-build instructions" in debug_packet
    assert "### Debug report" in debug_packet
    assert "will be rejected" in debug_packet
    assert result.value["debug_packet"] == debug_packet


def test_reply_retrieval_limits_become_packet_limits():
    result = build_comment_packet.handle(
        BuildCommentPacketCommand(
            video=VIDEO,
            max_reply_threads=7,
            max_replies_per_thread=17,
        ),
        youtube=DifferentlyOrderedYouTube(),
        transcripts=FakeTranscriptPort(),
        events=FakeEventSink(),
        artifacts=FakeArtifactStore(),
        templates=TEMPLATES,
        prompt_version="test",
    )

    allocation = result.value["run"]["allocation"]
    assert allocation["reply_threads"] == 0
    assert allocation["replies_per_thread"] == 17
