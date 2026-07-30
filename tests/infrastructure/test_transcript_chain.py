"""Ordering the transcript sources, and saying which one answered."""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.domain.statuses import (
    TranscriptAvailability,
    TranscriptResult,
)
from llm_youtube_comment_generation.infrastructure.transcript_chain import (
    ChainedTranscripts,
)

VIDEO = "x2ExZ4xSblI"


class Source:
    def __init__(self, result, name="source"):
        self.result = result
        self.name = name
        self.calls = 0

    def fetch(self, video_id, languages=()):
        self.calls += 1
        return self.result


def available(source="a"):
    return TranscriptResult(
        availability=TranscriptAvailability.AVAILABLE,
        entries=({"text": "line", "start": 0.0, "duration": 1.0},),
        source=source,
    )


def unreachable(detail="IpBlocked", source="a"):
    return TranscriptResult(
        availability=TranscriptAvailability.FETCH_FAILED,
        source=source, detail=detail,
    )


def no_captions(source="a"):
    return TranscriptResult(
        availability=TranscriptAvailability.NOT_PUBLISHED,
        source=source, detail="no caption tracks were published",
    )


def empty(source="a"):
    return TranscriptResult(
        availability=TranscriptAvailability.EMPTY,
        source=source,
        detail="caption track was empty",
    )


def test_the_first_source_that_works_is_the_one_used():
    first, second = Source(available("first")), Source(available("second"))

    result = ChainedTranscripts(first, second).fetch(VIDEO)

    assert result.source == "first"
    assert second.calls == 0


def test_an_unreachable_source_moves_on_to_the_next():
    """The whole point: an address refused by the scrape endpoint was being
    served by yt-dlp's player API in the same minute."""

    blocked, working = Source(unreachable()), Source(available("yt-dlp"))

    result = ChainedTranscripts(blocked, working).fetch(VIDEO)

    assert result.source == "yt-dlp"
    assert blocked.calls == 1 and working.calls == 1


def test_first_source_absent_does_not_hide_second_source_caption():
    absent = Source(no_captions("scrape"))
    second = Source(available("yt-dlp"))

    result = ChainedTranscripts(absent, second).fetch(VIDEO)

    assert result.availability is TranscriptAvailability.AVAILABLE
    assert result.source == "yt-dlp"
    assert absent.calls == second.calls == 1
    assert [attempt["source"] for attempt in result.attempts] == [
        "scrape", "yt-dlp",
    ]


def test_empty_first_source_does_not_hide_second_source_caption():
    result = ChainedTranscripts(
        Source(empty("scrape")),
        Source(available("yt-dlp")),
    ).fetch(VIDEO)

    assert result.source == "yt-dlp"


def test_both_absent_are_exhausted_before_absence_is_returned():
    first = Source(no_captions("scrape"))
    second = Source(no_captions("yt-dlp"))

    result = ChainedTranscripts(first, second).fetch(VIDEO)

    assert result.availability is TranscriptAvailability.NOT_PUBLISHED
    assert first.calls == second.calls == 1
    assert "scrape=not_published" in result.detail
    assert "yt-dlp=not_published" in result.detail


def test_no_captions_runs_an_explicit_local_fallback():
    absent = Source(no_captions())
    local = Source(available("local-whisper"))

    result = ChainedTranscripts(
        absent,
        local_fallback=local,
    ).fetch(VIDEO)

    assert result.source == "local-whisper"
    assert absent.calls == 1
    assert local.calls == 1
    assert result.attempts[0]["availability"] == "not_published"


def test_private_video_never_runs_the_local_fallback():
    private = Source(TranscriptResult(
        availability=TranscriptAvailability.NOT_PUBLIC,
        source="captions",
    ))
    local = Source(available("local-whisper"))

    result = ChainedTranscripts(
        private,
        local_fallback=local,
    ).fetch(VIDEO)

    assert result.availability is TranscriptAvailability.NOT_PUBLIC
    assert local.calls == 0


def test_a_private_video_ends_the_search_too():
    private = Source(TranscriptResult(
        availability=TranscriptAvailability.NOT_PUBLIC, source="a"))
    second = Source(available())

    ChainedTranscripts(private, second).fetch(VIDEO)

    assert second.calls == 0


def test_when_everything_is_unreachable_the_first_failure_is_reported():
    """The later ones are usually "not installed" noise about a fallback the
    operator never chose; the first is from the source he actually uses."""

    first = Source(unreachable("IpBlocked: too many requests", "scrape"))
    second = Source(unreachable("yt-dlp is not installed", "yt-dlp"))

    result = ChainedTranscripts(first, second).fetch(VIDEO)

    assert "IpBlocked" in result.detail
    assert result.source == "scrape"


def test_the_result_still_names_the_source_that_answered():
    """A packet built from yt-dlp and one built from the scrape endpoint have
    to be distinguishable after the fact; run.json carries this."""

    result = ChainedTranscripts(
        Source(unreachable()), Source(available("yt-dlp"))
    ).fetch(VIDEO)

    assert result.source == "yt-dlp"


def test_a_chain_of_one_is_allowed():
    assert ChainedTranscripts(Source(available())).fetch(VIDEO).entries


def test_a_chain_of_none_is_a_programming_error():
    with pytest.raises(ValueError):
        ChainedTranscripts()


def test_the_requested_languages_reach_every_source():
    seen = []

    class Recording:
        def fetch(self, video_id, languages=()):
            seen.append(languages)
            return unreachable()

    ChainedTranscripts(Recording(), Recording()).fetch(VIDEO, ("de", "en"))

    assert seen == [("de", "en"), ("de", "en")]
