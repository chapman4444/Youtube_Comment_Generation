"""Reusing a transcript this machine already has.

The caption endpoint rate-limits by IP. Twenty builds of one video got this
machine blocked, and every build afterwards refused while the transcript sat
in the previous run's directory, unchanged and usable.
"""

from __future__ import annotations

import json

import pytest

from llm_youtube_comment_generation.domain.statuses import (
    TranscriptAvailability,
    TranscriptResult,
)
from llm_youtube_comment_generation.infrastructure.saved_transcripts import (
    SavedTranscriptFallback,
    find_saved,
    parse_timestamped,
)

VIDEO = "x2ExZ4xSblI"
SAVED = "\n".join([
    "[00:00:00] Officer Abrams?",
    "[00:00:04] >> In your opinion, would you go get a shotgun?",
    "[00:00:09] >> Police opened a criminal case.",
])


class FakeLive:
    """A transcript port that fails the way the real one does."""

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def fetch(self, video_id, languages=()):
        self.calls += 1
        return self.result


def blocked():
    return TranscriptResult(
        availability=TranscriptAvailability.FETCH_FAILED,
        source="youtube-transcript-api",
        detail="IpBlocked: too many requests from this address",
    )


def working():
    return TranscriptResult(
        availability=TranscriptAvailability.AVAILABLE,
        entries=[{"text": "live", "start": 0.0, "duration": 1.0}],
        source="youtube-transcript-api",
    )


def run_directory(
    tmp_path,
    video=VIDEO,
    stamp="20260728-080321",
    text=SAVED,
    transcript_record=None,
):
    directory = tmp_path / f"{video}_{stamp}"
    directory.mkdir(parents=True)
    (directory / "transcript_timestamped.txt").write_text(text,
                                                          encoding="utf-8")
    if transcript_record is not None:
        (directory / "run.json").write_text(
            json.dumps({"transcript": transcript_record}),
            encoding="utf-8",
        )
    return directory


# -- when it is used -------------------------------------------------------


def test_a_blocked_fetch_falls_back_to_the_saved_copy(tmp_path):
    run_directory(tmp_path)
    port = SavedTranscriptFallback(FakeLive(blocked()), tmp_path)

    result = port.fetch(VIDEO)

    assert result.availability is TranscriptAvailability.AVAILABLE
    assert len(result.entries) == 3
    assert result.entries[0]["text"] == "Officer Abrams?"


def test_a_working_fetch_always_wins(tmp_path):
    """The fallback must never hide a transcript that has since changed."""

    run_directory(tmp_path)
    live = FakeLive(working())
    port = SavedTranscriptFallback(live, tmp_path)

    result = port.fetch(VIDEO)

    assert result.entries[0]["text"] == "live"
    assert result.source == "youtube-transcript-api"
    assert live.calls == 1


@pytest.mark.parametrize(
    "availability",
    [
        TranscriptAvailability.NOT_PUBLISHED,
        TranscriptAvailability.EMPTY,
        TranscriptAvailability.LANGUAGE_UNAVAILABLE,
        TranscriptAvailability.NOT_PUBLIC,
    ],
)
def test_conclusive_live_states_never_reuse_a_saved_transcript(
    tmp_path,
    availability,
):
    run_directory(tmp_path)
    live = TranscriptResult(
        availability=availability,
        source="youtube-transcript-api",
        detail=f"current live state: {availability.value}",
    )
    port = SavedTranscriptFallback(FakeLive(live), tmp_path)

    result = port.fetch(VIDEO)

    assert result is live
    assert result.availability is availability
    assert result.entries == ()


@pytest.mark.parametrize(
    "availability",
    [
        TranscriptAvailability.NOT_PUBLISHED,
        TranscriptAvailability.EMPTY,
        TranscriptAvailability.LANGUAGE_UNAVAILABLE,
    ],
)
def test_approved_local_transcription_can_follow_caption_absence(
    tmp_path,
    availability,
):
    run_directory(tmp_path)
    live = TranscriptResult(
        availability=availability,
        source="youtube-transcript-api",
        detail=f"current live state: {availability.value}",
    )
    local = FakeLive(working())
    asked = []
    port = SavedTranscriptFallback(
        FakeLive(live),
        tmp_path,
        local_fallback=local,
        approve_local_fallback=lambda reason: asked.append(reason) or True,
    )

    result = port.fetch(VIDEO)

    assert result.source == "youtube-transcript-api"
    assert result.entries[0]["text"] == "live"
    assert local.calls == 1
    assert asked == [live]


def test_the_newest_saved_run_is_the_one_reused(tmp_path):
    run_directory(tmp_path, stamp="20260101-000000", text="[00:00:00] old")
    run_directory(tmp_path, stamp="20260728-080321")
    newest = run_directory(tmp_path, stamp="20260728-235959",
                           text="[00:00:00] newest")

    assert find_saved(tmp_path, VIDEO).parent == newest


def test_another_video_is_never_borrowed_from(tmp_path):
    run_directory(tmp_path, video="qru7vjVsJGc")
    port = SavedTranscriptFallback(FakeLive(blocked()), tmp_path)

    assert port.fetch(VIDEO).availability is TranscriptAvailability.FETCH_FAILED


def test_nothing_saved_leaves_the_failure_exactly_as_it_was(tmp_path):
    live = blocked()
    port = SavedTranscriptFallback(FakeLive(live), tmp_path)

    result = port.fetch(VIDEO)

    assert result is live
    assert "IpBlocked" in result.detail


def test_an_empty_saved_file_is_not_a_transcript(tmp_path):
    run_directory(tmp_path, text="")
    port = SavedTranscriptFallback(FakeLive(blocked()), tmp_path)

    assert port.fetch(VIDEO).availability is TranscriptAvailability.FETCH_FAILED


def test_local_fallback_runs_only_after_live_and_saved_sources_fail(tmp_path):
    local = FakeLive(working())
    asked = []
    port = SavedTranscriptFallback(
        FakeLive(blocked()),
        tmp_path,
        local_fallback=local,
        approve_local_fallback=lambda reason: asked.append(reason) or True,
    )

    result = port.fetch(VIDEO)

    assert result.available
    assert local.calls == 1
    assert asked and asked[0].availability is TranscriptAvailability.FETCH_FAILED


def test_declining_local_fallback_preserves_the_reason(tmp_path):
    failure = blocked()
    local = FakeLive(working())
    port = SavedTranscriptFallback(
        FakeLive(failure),
        tmp_path,
        local_fallback=local,
        approve_local_fallback=lambda _reason: False,
    )

    result = port.fetch(VIDEO)

    assert result is failure
    assert local.calls == 0


def test_a_saved_transcript_prevents_an_unnecessary_whisper_prompt(tmp_path):
    run_directory(tmp_path)
    asked = []
    local = FakeLive(working())
    port = SavedTranscriptFallback(
        FakeLive(blocked()),
        tmp_path,
        local_fallback=local,
        approve_local_fallback=lambda reason: asked.append(reason) or True,
    )

    result = port.fetch(VIDEO)

    assert result.source == "saved-transcript"
    assert asked == []
    assert local.calls == 0


def test_saved_transcript_can_be_requested_without_a_live_attempt(tmp_path):
    run_directory(tmp_path)
    port = SavedTranscriptFallback(None, tmp_path)

    result = port.fetch(VIDEO)

    assert result.available
    assert result.source == "saved-transcript"


# -- and it says so --------------------------------------------------------


def test_a_thousand_character_library_error_is_cut_to_its_first_line(tmp_path):
    """The caption library's message is a wall of README links. Printing all
    of it buried the one sentence the operator needed."""

    run_directory(tmp_path)
    verbose = TranscriptResult(
        availability=TranscriptAvailability.FETCH_FAILED,
        source="youtube-transcript-api",
        detail=("IpBlocked: could not retrieve a transcript!\n\n"
                "YouTube is blocking requests from your IP.\n"
                + "- a very long explanation. " * 40),
    )
    port = SavedTranscriptFallback(FakeLive(verbose), tmp_path)

    detail = port.fetch(VIDEO).detail

    assert "IpBlocked" in detail
    assert "README" not in detail
    assert "cloud provider" not in detail
    assert len(detail) < 220


def test_the_stated_reason_is_ascii_for_a_windows_console(tmp_path):
    run_directory(tmp_path)
    port = SavedTranscriptFallback(FakeLive(blocked()), tmp_path)

    port.fetch(VIDEO).detail.encode("ascii")


def test_the_reuse_is_stated_with_the_run_it_came_from(tmp_path):
    """A packet built from an hour-old transcript is fine. One built from it
    without saying so is not."""

    run_directory(tmp_path)
    port = SavedTranscriptFallback(FakeLive(blocked()), tmp_path)

    result = port.fetch(VIDEO)

    assert result.source == "saved-transcript"
    assert "20260728-080321" in result.detail
    assert "was not fetched again" in result.detail
    assert "IpBlocked" in result.detail


def test_saved_whisper_preserves_generated_provenance(tmp_path):
    directory = run_directory(
        tmp_path,
        transcript_record={
            "source": "whisper",
            "original_source": "whisper",
            "is_generated": True,
            "language": "English",
            "language_code": "en",
        },
    )

    result = SavedTranscriptFallback(FakeLive(blocked()), tmp_path).fetch(VIDEO)

    assert result.source == "saved-transcript"
    assert result.original_source == "whisper"
    assert result.is_generated is True
    assert result.language == "English"
    assert result.language_code == "en"
    assert result.originating_run == directory.name


def test_saved_human_caption_preserves_not_generated_provenance(tmp_path):
    run_directory(
        tmp_path,
        transcript_record={
            "source": "youtube-transcript-api",
            "is_generated": False,
            "language": "English",
            "language_code": "en-US",
        },
    )

    result = SavedTranscriptFallback(FakeLive(blocked()), tmp_path).fetch(VIDEO)

    assert result.original_source == "youtube-transcript-api"
    assert result.is_generated is False
    assert result.language_code == "en-US"


def test_legacy_saved_run_does_not_invent_provenance(tmp_path):
    directory = run_directory(tmp_path)

    result = SavedTranscriptFallback(FakeLive(blocked()), tmp_path).fetch(VIDEO)

    assert result.source == "saved-transcript"
    assert result.original_source == ""
    assert result.is_generated is None
    assert result.originating_run == directory.name
    assert "Original source: unknown" in result.detail


# -- parsing the saved form ------------------------------------------------


def test_each_entry_runs_until_the_next_one_starts():
    entries = parse_timestamped(SAVED)

    assert entries[0]["start"] == 0.0
    assert entries[0]["duration"] == 4.0
    assert entries[1]["start"] == 4.0
    assert entries[1]["duration"] == 5.0


def test_the_last_entry_borrows_the_previous_gap_rather_than_inventing_one():
    entries = parse_timestamped(SAVED)

    assert entries[-1]["duration"] == entries[-2]["duration"]


def test_lines_without_a_timestamp_are_not_entries():
    entries = parse_timestamped("a heading\n[00:00:03] real line\n\n")

    assert len(entries) == 1
    assert entries[0]["text"] == "real line"


def test_hours_are_read_rather_than_truncated():
    entries = parse_timestamped("[01:02:03] late in a long video")

    assert entries[0]["start"] == 3723.0
