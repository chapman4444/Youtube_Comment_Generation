"""Transcribing the audio here, when YouTube published no captions.

The only source that can produce anything for a video with no caption track at
all. Verified once against a real video: 592 segments from 46 minutes of audio
in 317 seconds on tiny.en.

No test here downloads audio, loads a model, or reaches the network. The
downloader and the transcriber are both injected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_youtube_comment_generation.domain.statuses import TranscriptAvailability
from llm_youtube_comment_generation.infrastructure.whisper_transcript import (
    DEFAULT_MODEL,
    MINIMUM_CONFIDENCE,
    WhisperTranscriptAdapter,
    _entries,
)

VIDEO = "pshdWXte-hM"


class Segment:
    """What faster-whisper yields, as far as this code is concerned."""

    def __init__(self, start, end, text, avg_logprob=0.0):
        self.start = start
        self.end = end
        self.text = text
        self.avg_logprob = avg_logprob


def adapter(entries=None, language="en", **kwargs):
    written: list[Path] = []

    def download(video_id, into, proxy=""):
        path = Path(into) / f"{video_id}.m4a"
        path.write_bytes(b"not really audio")
        written.append(path)
        return path

    def transcribe(audio, *, model_name="", language=language):
        return (list(entries if entries is not None
                     else [{"text": "a line", "start": 0.0,
                            "duration": 1.0, "end": 1.0}]),
                language)

    port = WhisperTranscriptAdapter(
        downloader=download, transcriber=transcribe, **kwargs
    )
    port.written = written
    return port


# -- what it produces ------------------------------------------------------


def test_a_video_with_no_captions_gets_a_transcript_anyway():
    """The gap no amount of retrying, proxying or falling back could close:
    there was nothing on the other end to fetch."""

    result = adapter().fetch(VIDEO)

    assert result.availability is TranscriptAvailability.AVAILABLE
    assert len(result.entries) == 1


def test_a_machine_transcript_is_labelled_as_one():
    """The packet's transcript is evidence the model will quote. Words guessed
    at from audio on this machine are not the same kind of thing as a caption
    track the uploader published, and nothing downstream should have to guess
    which it got."""

    result = adapter().fetch(VIDEO)

    assert result.source == "whisper"
    assert result.is_generated is True
    assert "transcribed on this machine" in result.detail
    assert "not a transcript the uploader published" in result.detail


def test_the_model_that_produced_it_is_named():
    result = adapter(model_name="medium.en").fetch(VIDEO)

    assert "medium.en" in result.detail


def test_silence_is_not_a_transcript():
    assert adapter(entries=[]).fetch(VIDEO).availability is \
        TranscriptAvailability.EMPTY


# -- it cleans up after itself ---------------------------------------------


def test_the_audio_is_deleted_afterwards():
    """Half a gigabyte of stray .m4a would be this tool's mess, not his."""

    port = adapter()
    port.fetch(VIDEO)

    assert port.written and not port.written[0].exists()


def test_the_audio_is_deleted_even_when_transcription_fails():
    written: list[Path] = []

    def download(video_id, into, proxy=""):
        path = Path(into) / "audio.m4a"
        path.write_bytes(b"x")
        written.append(path)
        return path

    def explode(audio, *, model_name="", language=""):
        raise RuntimeError("the model could not be loaded")

    port = WhisperTranscriptAdapter(downloader=download, transcriber=explode)
    result = port.fetch(VIDEO)

    assert result.availability is TranscriptAvailability.FETCH_FAILED
    assert written and not written[0].exists()


# -- failures stay failures, and stay readable ------------------------------


def test_audio_that_will_not_download_is_reported_as_that():
    def refuse(video_id, into, proxy=""):
        raise OSError("HTTP Error 403: Forbidden")

    result = WhisperTranscriptAdapter(downloader=refuse).fetch(VIDEO)

    assert result.availability is TranscriptAvailability.FETCH_FAILED
    assert "could not be downloaded" in result.detail


def test_a_model_that_will_not_run_is_distinguished_from_a_bad_download():
    def explode(audio, *, model_name="", language=""):
        raise RuntimeError("out of memory")

    result = WhisperTranscriptAdapter(
        downloader=lambda v, into, proxy="": Path(into) / "a.m4a",
        transcriber=explode,
    ).fetch(VIDEO)

    assert "downloaded but could not be transcribed" in result.detail


def test_a_wall_of_text_is_cut_down():
    def explode(video_id, into, proxy=""):
        raise RuntimeError("ERROR\n" + "a long explanation. " * 60)

    result = WhisperTranscriptAdapter(downloader=explode).fetch(VIDEO)

    assert len(result.detail) < 220


# -- the expensive thing runs once and says it is running -------------------


def test_the_same_video_is_only_transcribed_once():
    """Minutes of CPU, not one request. Doing it twice for two packets of the
    same video is the mistake that got this machine banned, one tier up."""

    calls = []

    def transcribe(audio, *, model_name="", language=""):
        calls.append(audio)
        return [{"text": "x", "start": 0.0, "duration": 1.0, "end": 1.0}], "en"

    port = WhisperTranscriptAdapter(
        downloader=lambda v, into, proxy="": Path(into) / "a.m4a",
        transcriber=transcribe,
    )
    for _ in range(4):
        port.fetch(VIDEO)

    assert len(calls) == 1


def test_the_operator_is_told_before_the_slow_part():
    """It takes minutes. A console that goes quiet for five of them looks
    like a hang."""

    said = []

    class Events:
        def emit(self, event):
            said.append(event.message)

    adapter(events=Events()).fetch(VIDEO)

    assert any("transcribed here" in message for message in said)
    assert any("minutes, not seconds" in message for message in said)


# -- segment handling -------------------------------------------------------


def test_a_segment_the_model_is_unsure_of_is_not_quoted():
    """A guess about what was said is not the same as knowing, and a packet
    quotes its transcript as though somebody said it."""

    kept = list(_entries([
        Segment(0.0, 1.0, "clearly said", avg_logprob=-0.2),
        Segment(1.0, 2.0, "mumbled", avg_logprob=MINIMUM_CONFIDENCE - 0.5),
    ]))

    assert [entry["text"] for entry in kept] == ["clearly said"]


def test_whitespace_is_collapsed_and_empty_segments_dropped():
    kept = list(_entries([
        Segment(0.0, 1.0, "  spaced   out  "),
        Segment(1.0, 2.0, "   "),
    ]))

    assert [entry["text"] for entry in kept] == ["spaced out"]


def test_duration_comes_from_the_segment_rather_than_being_invented():
    kept = list(_entries([Segment(10.5, 14.25, "a line")]))

    assert kept[0]["start"] == 10.5
    assert kept[0]["end"] == 14.25
    assert kept[0]["duration"] == 3.75


def test_the_default_model_is_small_enough_to_be_usable():
    """A 1.5GB download in the middle of a packet build is not a default."""

    assert DEFAULT_MODEL.endswith(".en")
    assert DEFAULT_MODEL.startswith(("tiny", "base", "small"))
