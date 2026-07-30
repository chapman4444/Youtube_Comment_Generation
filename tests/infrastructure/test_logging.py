"""Logging that cannot leak the key.

A key in a log file is a key in the bug report the log gets pasted into.
"""

from __future__ import annotations

import io
import json
import logging

import pytest

from llm_youtube_comment_generation.infrastructure.logging_setup import (
    MINIMUM_SECRET_LENGTH,
    RedactingFilter,
    configure,
)

KEY = "AIzaSyDeliberatelyLongExampleKey123"


@pytest.fixture
def captured():
    stream = io.StringIO()
    yield stream, configure("DEBUG", secrets=[KEY], stream=stream)
    logging.getLogger().handlers.clear()


def test_the_key_never_reaches_the_log(captured):
    stream, _ = captured

    logging.getLogger("test").error("request failed for key %s", KEY)

    output = stream.getvalue()
    assert KEY not in output
    assert "[redacted]" in output


def test_the_key_is_redacted_inside_a_url(captured):
    stream, _ = captured

    logging.getLogger("test").warning(
        "GET https://example.invalid/v3/videos?key=%s&id=x", KEY
    )

    assert KEY not in stream.getvalue()


def test_a_secret_discovered_later_can_be_registered(captured):
    stream, redactor = captured
    redactor.add("AnotherLongSecretValue")

    logging.getLogger("test").error("token AnotherLongSecretValue leaked")

    assert "AnotherLongSecretValue" not in stream.getvalue()


def test_proxy_credentials_are_redacted_from_logs(captured):
    stream, redactor = captured
    proxy = (
        "http://" + "proxy-user:proxy-password@" + "proxy.example:8080"
    )
    redactor.add_proxy(proxy)

    logging.getLogger("test").error(
        "provider failed through %s; user=%s password=%s",
        proxy,
        "proxy-user",
        "proxy-password",
    )

    output = stream.getvalue()
    assert "proxy.example:8080" in output
    assert "proxy-user" not in output
    assert "proxy-password" not in output


def test_short_strings_are_never_redacted():
    """Replacing a two-character secret would corrupt every message that
    happened to contain those characters."""

    redactor = RedactingFilter(["ab", "x"])
    record = logging.LogRecord("t", logging.INFO, "f", 1,
                               "a table about absolutely nothing", None, None)

    redactor.filter(record)

    assert record.msg == "a table about absolutely nothing"


def test_the_minimum_length_is_stated_rather_than_implied():
    assert MINIMUM_SECRET_LENGTH >= 8


def test_jsonl_logging_produces_one_object_per_line():
    stream = io.StringIO()
    configure("INFO", secrets=[KEY], jsonl=True, stream=stream)

    logging.getLogger("ytcomment").info("started a run")
    logging.getLogger("ytcomment").error("failed with key %s", KEY)
    logging.getLogger().handlers.clear()

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]

    assert [entry["level"] for entry in lines] == ["INFO", "ERROR"]
    assert lines[0]["message"] == "started a run"
    assert KEY not in lines[1]["message"]


def test_an_exception_is_recorded_without_the_key():
    stream = io.StringIO()
    configure("DEBUG", secrets=[KEY], jsonl=True, stream=stream)

    try:
        raise RuntimeError(f"boom with {KEY}")
    except RuntimeError:
        logging.getLogger("ytcomment").exception("run failed")
    logging.getLogger().handlers.clear()

    entry = json.loads(stream.getvalue().splitlines()[0])
    assert "exception" in entry
    assert KEY not in stream.getvalue()


def test_configuring_twice_does_not_double_every_line():
    """Otherwise a second run in the same process logs everything twice."""

    stream = io.StringIO()
    configure("INFO", stream=stream)
    configure("INFO", stream=stream)

    logging.getLogger("ytcomment").info("once")
    logging.getLogger().handlers.clear()

    assert stream.getvalue().count("once") == 1
