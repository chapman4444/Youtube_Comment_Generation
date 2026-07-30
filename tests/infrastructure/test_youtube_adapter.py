"""The YouTube adapter, driven by recorded responses.

Recorded rather than live, deliberately: quota is finite, and a test whose
result depends on YouTube being up is not a test. The recorded payloads are
the real API's shape.

The rule these all serve: retrieval must report honestly why it stopped.
"""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.domain.errors import (
    CommentsDisabledError,
    ConfigurationError,
    OperationCancelled,
    QuotaExceededError,
    YouTubeAPIError,
)
from llm_youtube_comment_generation.domain.statuses import RetrievalStatus
from llm_youtube_comment_generation.infrastructure.youtube_api import (
    MAX_PAGE_REQUESTS,
    YouTubeAdapter,
)


class RecordedResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


class RecordedSession:
    """Replays prepared payloads and records what was asked for."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        if not self._responses:
            raise AssertionError(f"no recorded response left for {url}")
        return self._responses.pop(0)


class SimulatedRetryingSession:
    """A session whose one logical get represents transport-level attempts."""

    def __init__(self, *, attempts, response=None, error=None):
        self.transport_attempts = attempts
        self.response = response
        self.error = error
        self.logical_get_calls = 0

    def get(self, _url, params=None, timeout=None):
        self.logical_get_calls += 1
        if self.error is not None:
            raise self.error
        return self.response


def thread_page(ids, next_token=None, reply_counts=None):
    reply_counts = reply_counts or {}
    payload = {
        "items": [
            {
                "snippet": {
                    "totalReplyCount": reply_counts.get(cid, 0),
                    "topLevelComment": {
                        "id": cid,
                        "snippet": {
                            "authorDisplayName": f"@user{cid}",
                            "textOriginal": f"comment {cid}",
                            "likeCount": 1,
                            "publishedAt": "2026-07-01T00:00:00Z",
                            "updatedAt": "2026-07-01T00:00:00Z",
                            "authorChannelId": {"value": "UC" + cid.ljust(22, "z")},
                        },
                    },
                }
            }
            for cid in ids
        ]
    }
    if next_token:
        payload["nextPageToken"] = next_token
    return RecordedResponse(payload)


def adapter(responses, **kwargs):
    return YouTubeAdapter("test-key", RecordedSession(responses), **kwargs)


# --------------------------------------------------------------------------
# Construction and credentials
# --------------------------------------------------------------------------


def test_an_adapter_without_a_key_refuses_to_exist():
    with pytest.raises(ConfigurationError, match="API key is required"):
        YouTubeAdapter("", RecordedSession([]))


def test_the_key_is_sent_but_never_stored_in_the_call_record():
    session = RecordedSession([RecordedResponse({"items": [{"id": "x"}]})])
    YouTubeAdapter("secret-key-value", session).get("videos", {"id": "v"})

    assert session.calls[0]["params"]["key"] == "secret-key-value"


# --------------------------------------------------------------------------
# Completeness
# --------------------------------------------------------------------------


def test_a_scan_that_saw_everything_reports_complete():
    port = adapter([thread_page(["c1", "c2"])])

    page = port.comment_threads("v", maximum=100)

    assert page.outcome.status is RetrievalStatus.COMPLETE
    assert page.outcome.may_conclude_absence is True
    assert len(page.comments) == 2


def test_reaching_the_requested_limit_with_more_available_is_truncation():
    """The distinction that matters.

    Stopping because there was nothing left is COMPLETE. Stopping because we
    hit our own limit while the API still offered more is truncation, and a
    caller must not conclude absence from it.
    """

    port = adapter([thread_page(["c1", "c2"], next_token="more")])

    page = port.comment_threads("v", maximum=2)

    assert page.outcome.status is RetrievalStatus.TOP_LEVEL_TRUNCATED
    assert page.outcome.may_conclude_absence is False
    assert page.outcome.notes


def test_reaching_the_limit_with_nothing_left_is_still_complete():
    """Exactly-enough must not be misreported as truncated.

    A guard that cries wolf on a complete scan trains the operator to ignore
    it, which costs more than the guard saves.
    """

    port = adapter([thread_page(["c1", "c2"])])

    page = port.comment_threads("v", maximum=2)

    assert page.outcome.status is RetrievalStatus.COMPLETE


def test_pagination_walks_until_the_tokens_run_out():
    port = adapter([
        thread_page(["c1"], next_token="t2"),
        thread_page(["c2"], next_token="t3"),
        thread_page(["c3"]),
    ])

    page = port.comment_threads("v", maximum=100)

    assert [c["comment_id"] for c in page.comments] == ["c1", "c2", "c3"]
    assert page.outcome.status is RetrievalStatus.COMPLETE
    assert page.outcome.api_operations_used == 3


def test_a_repeated_page_token_stops_the_scan_rather_than_looping():
    """Continuing would spend the day's quota collecting one page forever."""

    port = adapter([
        thread_page(["c1"], next_token="same"),
        thread_page(["c2"], next_token="same"),
    ])

    page = port.comment_threads("v", maximum=1000)

    assert page.outcome.status is RetrievalStatus.PAGE_TOKEN_LOOP
    assert page.outcome.may_conclude_absence is False
    assert any("repeated page token" in note for note in page.outcome.notes)


def test_the_page_request_cap_bounds_a_runaway_thread():
    """A thread with endless pages must not consume the whole quota."""

    port = adapter([
        thread_page([f"c{i}"], next_token=f"t{i + 1}")
        for i in range(MAX_PAGE_REQUESTS + 5)
    ])

    page = port.comment_threads("v", maximum=1_000_000)

    assert page.outcome.status is RetrievalStatus.TOP_LEVEL_TRUNCATED
    assert page.outcome.api_operations_used == MAX_PAGE_REQUESTS
    assert any("page requests" in note for note in page.outcome.notes)


def test_a_truncated_reply_thread_gets_the_reply_specific_status():
    payload = {
        "items": [
            {"id": f"r{i}", "snippet": {
                "authorDisplayName": "@a", "textOriginal": "x", "likeCount": 0,
                "publishedAt": "2026-07-01T00:00:00Z",
                "updatedAt": "2026-07-01T00:00:00Z"}}
            for i in range(3)
        ],
        "nextPageToken": "more",
    }
    port = adapter([RecordedResponse(payload)])

    page = port.replies("c1", maximum=3)

    assert page.outcome.status is RetrievalStatus.REPLY_THREAD_TRUNCATED
    assert all(c["parent_comment_id"] == "c1" for c in page.comments)
    assert all(c["is_reply"] for c in page.comments)


def test_cancellation_stops_between_pages_and_keeps_what_was_retrieved():
    """Cancellation arrives from another thread while a page is in flight.

    The loop checks at the top of each iteration, so the page already being
    fetched completes and its comments are kept. Discarding them would punish
    the operator for stopping a long scan.
    """

    state = {"stop": False}

    class FlippingSession(RecordedSession):
        def get(self, url, params=None, timeout=None):
            response = super().get(url, params, timeout)
            state["stop"] = True        # cancelled while page 1 was in flight
            return response

    port = YouTubeAdapter(
        "test-key",
        FlippingSession([
            thread_page(["c1"], next_token="t2"),
            thread_page(["c2"]),
        ]),
        cancelled=lambda: state["stop"],
    )

    page = port.comment_threads("v", maximum=100)

    assert page.outcome.status is RetrievalStatus.CANCELLED
    assert page.outcome.may_conclude_absence is False
    assert [c["comment_id"] for c in page.comments] == ["c1"]
    assert any("cancelled" in note for note in page.outcome.notes)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


@pytest.mark.parametrize("reason, expected, code", [
    ("quotaExceeded", QuotaExceededError, 2),
    ("dailyLimitExceeded", QuotaExceededError, 2),
    ("commentsDisabled", CommentsDisabledError, 1),
    ("badRequest", YouTubeAPIError, 1),
])
def test_an_http_error_becomes_a_domain_error_with_its_exit_code(
    reason, expected, code
):
    """No caller above the adapter sees a status code."""

    payload = {"error": {"message": "nope", "errors": [{"reason": reason}]}}
    port = adapter([RecordedResponse(payload, status_code=403)])

    with pytest.raises(expected) as caught:
        port.video("gC-J7zwYMAM")

    assert caught.value.exit_code == code


def test_a_non_json_error_body_still_produces_a_domain_error():
    port = adapter([RecordedResponse(None, status_code=500, text="<html>502</html>")])

    with pytest.raises(YouTubeAPIError):
        port.video("gC-J7zwYMAM")


def test_a_video_that_does_not_exist_is_a_configuration_error():
    """Exit 3, not 1: the operator typed something wrong and can fix it."""

    port = adapter([RecordedResponse({"items": []})])

    with pytest.raises(ConfigurationError) as caught:
        port.video("gC-J7zwYMAM")

    assert caught.value.exit_code == 3


def test_cancelling_before_a_request_sends_nothing():
    session = RecordedSession([])
    port = YouTubeAdapter("k", session, cancelled=lambda: True)

    with pytest.raises(OperationCancelled):
        port.video("gC-J7zwYMAM")

    assert session.calls == []
    assert port.api_operations_used == 0


def test_success_without_retry_is_one_logical_api_operation():
    session = SimulatedRetryingSession(
        attempts=1,
        response=RecordedResponse({"items": [{"id": "video"}]}),
    )
    port = YouTubeAdapter("k", session)

    port.get("videos", {"id": "gC-J7zwYMAM"})

    assert session.transport_attempts == 1
    assert port.api_operations_used == 1


def test_retry_then_success_remains_one_logical_api_operation():
    session = SimulatedRetryingSession(
        attempts=2,
        response=RecordedResponse({"items": [{"id": "video"}]}),
    )
    port = YouTubeAdapter("k", session)

    port.get("videos", {"id": "gC-J7zwYMAM"})

    assert session.transport_attempts == 2
    assert session.logical_get_calls == 1
    assert port.api_operations_used == 1


def test_retry_exhaustion_still_records_the_one_logical_operation():
    session = SimulatedRetryingSession(
        attempts=4,
        error=RuntimeError("transport retries exhausted"),
    )
    port = YouTubeAdapter("k", session)

    with pytest.raises(RuntimeError, match="retries exhausted"):
        port.get("videos", {"id": "gC-J7zwYMAM"})

    assert session.transport_attempts == 4
    assert port.api_operations_used == 1


def test_non_retryable_4xx_is_one_logical_api_operation():
    response = RecordedResponse(
        {"error": {"message": "bad input"}},
        status_code=400,
    )
    port = adapter([response])

    with pytest.raises(YouTubeAPIError):
        port.video("gC-J7zwYMAM")

    assert port.api_operations_used == 1


@pytest.mark.parametrize("maximum", (0, -1))
def test_non_positive_comment_limit_is_refused_before_a_request(maximum):
    session = RecordedSession([])
    port = YouTubeAdapter("k", session)

    with pytest.raises(ConfigurationError, match="at least 1"):
        port.comment_threads("v", maximum=maximum)

    assert session.calls == []


@pytest.mark.parametrize("maximum", (0, -1))
def test_non_positive_reply_limit_is_refused_before_a_request(maximum):
    session = RecordedSession([])
    port = YouTubeAdapter("k", session)

    with pytest.raises(ConfigurationError, match="at least 1"):
        port.replies("c1", maximum=maximum)

    assert session.calls == []


# --------------------------------------------------------------------------
# Parsing and accounting
# --------------------------------------------------------------------------


def test_a_thread_carries_its_reported_reply_count():
    """The count YouTube reports, not the count we fetched.

    They differ on any busy thread, and the difference is what tells the
    application a thread was truncated.
    """

    port = adapter([thread_page(["c1"], reply_counts={"c1": 178})])

    page = port.comment_threads("v")

    assert page.comments[0]["total_reply_count"] == 178


def test_the_ordering_is_recorded_on_each_comment():
    port = adapter([thread_page(["c1"])])

    page = port.comment_threads("v", order="time")

    assert page.comments[0]["order_source"] == "time"
    assert port._session.calls[0]["params"]["order"] == "time"


def test_quota_accounting_counts_every_request():
    port = adapter([
        thread_page(["c1"], next_token="t2"),
        thread_page(["c2"]),
    ])

    port.comment_threads("v", maximum=100)

    assert port.api_operations_used == 2


def test_a_handle_resolves_to_a_channel_id():
    port = adapter([RecordedResponse({"items": [{"id": "UC" + "a" * 22}]})])

    assert port.channel_id_for_handle("someone") == "UC" + "a" * 22
    assert port._session.calls[0]["params"]["forHandle"] == "@someone"


def test_an_unknown_handle_refuses():
    port = adapter([RecordedResponse({"items": []})])

    with pytest.raises(ConfigurationError, match="No channel was found"):
        port.channel_id_for_handle("@nobody")
