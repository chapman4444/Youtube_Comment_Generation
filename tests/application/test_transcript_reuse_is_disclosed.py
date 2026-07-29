"""A reused transcript must be visible, not merely legal.

The fallback worked on its first live run and said nothing anywhere: the run
record read "availability: available" like any other build, no warning
reached the console, and the packet gave no sign the words in it were fetched
an hour earlier. Reusing is fine. Reusing quietly is the thing this project
keeps having to fix.
"""

from __future__ import annotations

import json

from fakes import FakeEventSink, FakeYouTubePort
from llm_youtube_comment_generation.application.build_comment_packet import (
    BuildCommentPacketCommand,
    handle,
)
from llm_youtube_comment_generation.domain.statuses import (
    TranscriptAvailability,
    TranscriptResult,
    WarningCode,
)
from llm_youtube_comment_generation.infrastructure import prompt_resources

VIDEO = "gC-J7zwYMAM"

TEMPLATES = {
    name: prompt_resources.load(name).text
    for name in ("comment_workflow.md", "comment_final_check.md")
}


class TranscriptStub:
    def __init__(self, result):
        self.result = result

    def fetch(self, video_id, languages=()):
        return self.result


def comment(index):
    return {
        "comment_id": f"c{index}", "author": f"@u{index}",
        "author_channel_id": "UC" + str(index).ljust(22, "z"),
        "text": "a comment body worth reading and counting",
        "like_count": index, "total_reply_count": 0,
        "published_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
    }


class CollectingArtifacts:
    """Keeps staged files in memory. Nothing reaches the disk."""

    def __init__(self):
        self.files: dict[str, str] = {}

    def stage(self, name, text):
        self.files[name] = text

    def commit(self):
        return list(self.files)


def build(transcript, **command_options):
    youtube = FakeYouTubePort(
        videos={VIDEO: {"video_id": VIDEO, "title": "A video",
                        "description": "d", "comment_count": 4}},
        comments=[comment(i) for i in range(4)],
    )
    return handle(
        BuildCommentPacketCommand(video=VIDEO, **command_options),
        youtube=youtube,
        transcripts=TranscriptStub(transcript),
        events=FakeEventSink(),
        artifacts=CollectingArtifacts(),
        templates=TEMPLATES,
        prompt_version="test",
    )


def reused():
    return TranscriptResult(
        availability=TranscriptAvailability.AVAILABLE,
        entries=[{"text": "a line", "start": 0.0, "duration": 2.0}],
        source="saved-transcript",
        detail=("the live fetch failed (IpBlocked), so this is the transcript "
                "saved with run 20260728-080321. It is reused unchanged and "
                "was not fetched again."),
    )


def fresh():
    return TranscriptResult(
        availability=TranscriptAvailability.AVAILABLE,
        entries=[{"text": "a line", "start": 0.0, "duration": 2.0}],
        source="youtube-transcript-api",
        language="English (auto-generated)",
    )


def record(result):
    return result.value["run"]


def test_a_reused_transcript_warns_on_the_console():
    result = build(reused())
    messages = [w.message for w in result.warnings]

    assert any("reused, not fetched" in message for message in messages)
    assert any("20260728-080321" in message for message in messages)


def test_the_run_record_says_where_the_transcript_came_from():
    stored = record(build(reused()))["transcript"]

    assert stored["source"] == "saved-transcript"
    assert "not fetched again" in stored["detail"]
    assert stored["availability"] == "available"


def test_a_freshly_fetched_transcript_warns_about_nothing():
    result = build(fresh())

    assert not any("reused" in w.message for w in result.warnings)


def test_a_fresh_run_still_records_its_source():
    stored = record(build(fresh()))["transcript"]

    assert stored["source"] == "youtube-transcript-api"


def test_a_missing_transcript_is_still_its_own_warning():
    result = build(
        TranscriptResult(
            availability=TranscriptAvailability.NOT_PUBLISHED,
            source="youtube-transcript-api",
        ),
        allow_no_transcript=True,
    )

    assert any(w.code is WarningCode.TRANSCRIPT_UNAVAILABLE
               for w in result.warnings)
    assert any("without a transcript" in w.message for w in result.warnings)
