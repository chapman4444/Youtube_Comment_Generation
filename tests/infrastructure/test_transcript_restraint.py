"""The tool must not be able to get this machine banned again.

A sweep built nine packets from one video and fetched that video's caption
track for every one of them, plus retries: about twenty requests for one
transcript that had not changed. The endpoint is scraped unauthenticated and
throttles by address, so it blocked the operator's own connection for two days
and every build afterwards refused.

The transcript adapter is the only thing that talks to that endpoint, so the
guard belongs here rather than in each caller's discipline.
"""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.domain.statuses import (
    TranscriptAvailability,
    TranscriptResult,
)
from llm_youtube_comment_generation.infrastructure import transcript_api
from llm_youtube_comment_generation.infrastructure.transcript_api import (
    GIVE_UP_AFTER,
    TranscriptAdapter,
    transcript_client,
)

VIDEO = "x2ExZ4xSblI"


def test_caption_provider_failure_never_exposes_proxy_credentials(monkeypatch):
    proxy = (
        "http://" + "proxy-user:proxy-password@" + "proxy.example:8080"
    )

    class FailingClient:
        def list(self, _video_id):
            raise RuntimeError(f"connection refused for {proxy}")

    monkeypatch.setattr(
        transcript_api,
        "transcript_client",
        lambda _proxy: FailingClient(),
    )

    detail = TranscriptAdapter(proxy_url=proxy).fetch(VIDEO).detail

    assert "proxy.example:8080" in detail
    assert "proxy-user" not in detail
    assert "proxy-password" not in detail


class CountingAdapter(TranscriptAdapter):
    """Counts live attempts without making any."""

    def __init__(self, result, **kwargs):
        super().__init__(**kwargs)
        self.result = result
        self.attempts = 0

    def _fetch_live(self, video_id, wanted):
        self.attempts += 1
        return self.result(video_id) if callable(self.result) else self.result


def available():
    return TranscriptResult(
        availability=TranscriptAvailability.AVAILABLE,
        entries=({"text": "a line", "start": 0.0, "duration": 1.0},),
        source="youtube-transcript-api",
    )


def blocked():
    return TranscriptResult(
        availability=TranscriptAvailability.FETCH_FAILED,
        source="youtube-transcript-api",
        detail="IpBlocked: too many requests from this address\nand a wall of "
               "README links after it",
    )


def no_captions():
    return TranscriptResult(
        availability=TranscriptAvailability.NOT_PUBLISHED,
        source="youtube-transcript-api",
        detail="no caption tracks were published",
    )


# -- one fetch per video, per process --------------------------------------


def test_the_same_transcript_is_only_fetched_once():
    """Nine packets from one video made nine identical requests. A published
    video's captions do not change between one packet and the next."""

    adapter = CountingAdapter(available())

    for _ in range(9):
        assert adapter.fetch(VIDEO).availability is TranscriptAvailability.AVAILABLE

    assert adapter.attempts == 1


def test_a_different_video_is_still_fetched():
    adapter = CountingAdapter(available())

    adapter.fetch(VIDEO)
    adapter.fetch("qru7vjVsJGc")

    assert adapter.attempts == 2


def test_a_different_language_is_still_fetched():
    """A cache keyed on the video alone would hand back an English transcript
    for a request that asked for German."""

    adapter = CountingAdapter(available())

    adapter.fetch(VIDEO, ("en",))
    adapter.fetch(VIDEO, ("de",))

    assert adapter.attempts == 2


def test_a_failure_is_not_cached_as_an_answer():
    """A transient failure must not poison the video for the whole run."""

    results = [blocked(), available()]
    adapter = CountingAdapter(lambda _video: results.pop(0))

    assert adapter.fetch(VIDEO).availability is TranscriptAvailability.FETCH_FAILED
    assert adapter.fetch(VIDEO).availability is TranscriptAvailability.AVAILABLE
    assert adapter.attempts == 2


# -- and it stops knocking ---------------------------------------------------


def test_repeated_refusal_stops_this_process_trying():
    adapter = CountingAdapter(blocked())

    for _ in range(10):
        adapter.fetch(VIDEO)

    assert adapter.attempts == GIVE_UP_AFTER


def test_giving_up_says_why_and_what_to_do_instead():
    adapter = CountingAdapter(blocked(), give_up_after=2)
    adapter.fetch(VIDEO)
    adapter.fetch("qru7vjVsJGc")

    detail = adapter.fetch("pshdWXte-hM").detail

    assert "not attempted" in detail
    assert "IpBlocked" in detail
    assert "can deepen an address block" in detail
    assert "comment rebuild" in detail
    assert "proxy_url" in detail
    # The library's message is a thousand characters of README links, and the
    # whole point of this text is that it is read in a console.
    assert "README" not in detail
    assert len(detail) < 400


def test_a_video_with_no_captions_never_counts_against_the_budget():
    """"This video has no transcript" is an answer about the video, not a sign
    the endpoint is refusing us. Counting it would stop a run part way through
    a queue of perfectly fine videos that simply have no captions."""

    adapter = CountingAdapter(no_captions())

    for index in range(10):
        adapter.fetch(f"video{index}")

    assert adapter.attempts == 10


def test_a_success_forgives_earlier_failures():
    results = [blocked(), blocked(), available(), blocked(), blocked()]
    adapter = CountingAdapter(lambda _video: results.pop(0))

    for index in range(5):
        adapter.fetch(f"video{index}")

    assert adapter.attempts == 5, "a success should reset the run of failures"


# -- the session the old application always passed in -----------------------


@pytest.fixture
def captured(monkeypatch):
    """Records what the caption library would have been constructed with."""

    import youtube_transcript_api

    seen: dict = {}

    class Recorder:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    # transcript_client imports the name inside the function, so patching the
    # module attribute is enough and nothing is constructed for real.
    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi",
                        Recorder)
    return seen


def test_caption_requests_go_through_this_project_s_own_session(captured):
    """A bare client builds its own session, so every caption request went out
    as python-requests/x.y.z with no retry policy — while the Data API calls
    beside them carried a real User-Agent and backoff on 429. The old
    application passed its session in; this rebuild had dropped it."""

    transcript_client()

    session = captured["http_client"]
    assert "python-requests" not in session.headers["User-Agent"]
    assert "llm-youtube-comment-generation" in session.headers["User-Agent"]


def test_proxy_url_finally_reaches_the_endpoint_that_gets_banned(captured):
    """It was in the configuration for the whole project and reached only the
    authenticated, quota-metered API, which is never the one blocked."""

    transcript_client("http://127.0.0.1:8888")

    assert captured["http_client"].proxies == {
        "http": "http://127.0.0.1:8888",
        "https": "http://127.0.0.1:8888",
    }


def test_no_proxy_url_sets_no_proxy(captured):
    transcript_client("")

    assert captured["http_client"].proxies == {}


def test_the_adapter_passes_its_proxy_through(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(transcript_api, "transcript_client",
                        lambda url="": seen.append(url) or _Raiser())

    TranscriptAdapter(proxy_url="http://127.0.0.1:9999").fetch(VIDEO)

    assert seen == ["http://127.0.0.1:9999"]


class _Raiser:
    """Stands in for the client without reaching anything."""

    def list(self, video_id):
        raise RuntimeError("no network in tests")
