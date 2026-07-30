"""Captions by way of yt-dlp's player API.

The scrape endpoint and this one are blocked separately. On the day this was
written the operator's address was refused by the first for two days while the
second served 821 caption events for the same video, from the same connection,
in the same minute.

Verified against the other adapter on a real video once the block lifted: both
returned 411 entries for x2ExZ4xSblI. No test here reaches the network.
"""

from __future__ import annotations

import json

import pytest

from llm_youtube_comment_generation.domain.statuses import TranscriptAvailability
from llm_youtube_comment_generation.infrastructure.ytdlp_transcript import (
    YtDlpTranscriptAdapter,
    choose_track,
    parse_json3,
)

VIDEO = "x2ExZ4xSblI"


def test_ytdlp_failure_never_exposes_proxy_credentials():
    proxy = (
        "http://" + "proxy-user:proxy-password@" + "proxy.example:8080"
    )

    def fail(_video_id, _proxy=""):
        raise RuntimeError(f"request failed through {proxy}")

    detail = YtDlpTranscriptAdapter(
        proxy_url=proxy,
        extractor=fail,
    ).fetch(VIDEO).detail

    assert "proxy.example:8080" in detail
    assert "proxy-user" not in detail
    assert "proxy-password" not in detail


def track(url="https://captions/en.json3", ext="json3"):
    return [{"ext": "vtt", "url": "https://captions/en.vtt"},
            {"ext": ext, "url": url}]


def info(manual=None, automatic=None):
    return {"subtitles": manual or {}, "automatic_captions": automatic or {}}


def json3(*events):
    return json.dumps({"events": list(events)})


def event(start_ms, duration_ms, *texts):
    return {"tStartMs": start_ms, "dDurationMs": duration_ms,
            "segs": [{"utf8": text} for text in texts]}


def adapter(payload, extracted, **kwargs):
    return YtDlpTranscriptAdapter(
        extractor=lambda video_id, proxy="": extracted,
        reader=lambda url: payload,
        **kwargs,
    )


# -- choosing a track ------------------------------------------------------


def test_a_published_track_beats_an_automatic_one():
    """The words matter more than who typed them, but a human transcript in
    the right language is still better than a machine one."""

    chosen = choose_track(
        info(manual={"en": track("https://manual")},
             automatic={"en": track("https://auto")}),
        ("en",),
    )

    assert chosen == ("https://manual", "en", False)


def test_the_requested_language_beats_a_published_track_in_another():
    chosen = choose_track(
        info(manual={"de": track("https://german")},
             automatic={"en": track("https://english")}),
        ("en",),
    )

    assert chosen == ("https://english", "en", True)


def test_a_regional_variant_counts_as_the_language():
    chosen = choose_track(info(automatic={"en-GB": track("https://gb")}),
                          ("en",))

    assert chosen is not None and chosen[1] == "en-GB"


def test_a_track_with_no_json3_format_is_not_offered():
    """srt and vtt would have to be parsed back out of display text, and srv1
    rounds its timings."""

    assert choose_track(
        info(automatic={"en": [{"ext": "vtt", "url": "https://x"}]}), ("en",)
    ) is None


def test_no_captions_at_all_is_no_track():
    assert choose_track(info(), ("en",)) is None


# -- reading the track -----------------------------------------------------


def test_segments_are_joined_into_one_line():
    entries = parse_json3(json.loads(json3(event(1680, 4079, "Do you think ",
                                                 "there's a Mormon mafia?"))))

    assert entries == [{
        "text": "Do you think there's a Mormon mafia?",
        "start": 1.68, "duration": 4.079, "end": 1.68 + 4.079,
    }]


def test_a_blank_event_is_spacing_not_speech():
    """json3 uses empty events for timing. One counted as an entry shows up in
    the packet as a timestamp with nothing beside it."""

    entries = parse_json3(json.loads(
        json3(event(0, 1000, "real"), event(1000, 500, ""),
              event(2000, 1000, "   "))
    ))

    assert [entry["text"] for entry in entries] == ["real"]


def test_milliseconds_become_seconds():
    entries = parse_json3(json.loads(json3(event(3_723_000, 2_000, "late"))))

    assert entries[0]["start"] == 3723.0
    assert entries[0]["duration"] == 2.0


# -- the adapter as a whole ------------------------------------------------


def test_a_video_with_captions_comes_back_available():
    port = adapter(json3(event(0, 1000, "a line")),
                   info(automatic={"en": track()}))

    result = port.fetch(VIDEO)

    assert result.availability is TranscriptAvailability.AVAILABLE
    assert result.source == "yt-dlp"
    assert result.is_generated is True
    assert len(result.entries) == 1


def test_a_video_with_no_captions_says_so_rather_than_failing():
    """Not published is an answer about the video. Reporting it as a failure
    would send the chain on to ask a second source the same question."""

    port = adapter("", info())

    assert port.fetch(VIDEO).availability is TranscriptAvailability.NOT_PUBLISHED


def test_a_track_that_lists_but_will_not_read_is_a_failure():
    def refuse(url):
        raise OSError("403")

    port = YtDlpTranscriptAdapter(
        extractor=lambda video_id, proxy="": info(automatic={"en": track()}),
        reader=refuse,
    )
    result = port.fetch(VIDEO)

    assert result.availability is TranscriptAvailability.FETCH_FAILED
    assert "listed but could not be read" in result.detail


def test_a_private_video_is_not_reported_as_a_transport_failure():
    def unavailable(video_id, proxy=""):
        raise RuntimeError("Video unavailable. This video is private")

    port = YtDlpTranscriptAdapter(extractor=unavailable)

    assert port.fetch(VIDEO).availability is TranscriptAvailability.NOT_PUBLIC


def test_the_wall_of_text_a_failure_arrives_with_is_cut_down():
    def noisy(video_id, proxy=""):
        raise RuntimeError("ERROR: something\n" + "a long explanation. " * 60)

    result = YtDlpTranscriptAdapter(extractor=noisy).fetch(VIDEO)

    assert len(result.detail) < 260


def test_the_same_video_is_only_extracted_once():
    calls = []

    def counting(video_id, proxy=""):
        calls.append(video_id)
        return info(automatic={"en": track()})

    port = YtDlpTranscriptAdapter(
        extractor=counting, reader=lambda url: json3(event(0, 1000, "x"))
    )
    for _ in range(5):
        port.fetch(VIDEO)

    assert calls == [VIDEO]


def test_the_proxy_reaches_the_extractor():
    seen = []
    port = YtDlpTranscriptAdapter(
        proxy_url="http://127.0.0.1:8888",
        extractor=lambda video_id, proxy="": seen.append(proxy) or info(),
    )
    port.fetch(VIDEO)

    assert seen == ["http://127.0.0.1:8888"]
