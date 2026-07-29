"""Time rules and the owner's own threads."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from llm_youtube_comment_generation.domain.errors import ConfigurationError
from llm_youtube_comment_generation.domain.threads import (
    OwnerThread,
    as_moment,
    parse_since,
    reply_is_new,
)

OWNER = "UC" + "o" * 22


def test_fractional_timestamps_compare_correctly():
    """String comparison was wrong and looked right.

    "2026-07-01T12:00:00.123Z" sorts BEFORE "2026-07-01T12:00:00Z" as text,
    because "." precedes "Z", so a reply that arrived after the cutoff was
    reported as older than it.
    """

    later = "2026-07-01T12:00:00.123Z"
    earlier = "2026-07-01T12:00:00Z"

    assert later < earlier                      # the trap, as plain text
    assert as_moment(later) > as_moment(earlier)


def test_an_unparseable_timestamp_sorts_first_never_newest():
    """Unknown must never win a "newest" comparison."""

    floor = datetime.min.replace(tzinfo=timezone.utc)

    assert as_moment("") == floor
    assert as_moment("not a date") == floor
    assert as_moment(None) == floor
    assert as_moment("2026-01-01T00:00:00Z") > as_moment("garbage")


def test_a_naive_timestamp_is_read_as_utc():
    assert as_moment("2026-07-01T12:00:00") == as_moment("2026-07-01T12:00:00Z")


def test_an_offset_timestamp_is_normalised_to_utc():
    assert as_moment("2026-07-01T14:00:00+02:00") == as_moment("2026-07-01T12:00:00Z")


def test_since_accepts_a_day_count():
    """The clock is injected, so "7 days back" is testable without freezing time."""

    now = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

    assert parse_since("7", now=now) == "2026-07-20T12:00:00Z"
    assert parse_since("0", now=now) == "2026-07-27T12:00:00Z"


def test_since_accepts_iso_forms():
    assert parse_since("2026-07-01") == "2026-07-01T00:00:00Z"
    assert parse_since("2026-07-01T09:30:00Z") == "2026-07-01T09:30:00Z"
    assert parse_since("2026-07-01T11:30:00+02:00") == "2026-07-01T09:30:00Z"


def test_blank_since_means_no_cutoff():
    assert parse_since(None) is None
    assert parse_since("") is None
    assert parse_since("   ") is None


def test_bad_since_is_a_configuration_error():
    with pytest.raises(ConfigurationError, match="Invalid --since"):
        parse_since("last tuesday")


def test_reply_newness_filter(reply):
    cutoff = "2026-01-02T00:00:00Z"
    old = reply("r1", "@alice", "old", "2026-01-01T00:00:00Z")
    new = reply("r2", "@bob", "new", "2026-01-03T00:00:00Z")
    exact = reply("r3", "@carol", "exact", cutoff)

    assert reply_is_new(old, cutoff) is False
    assert reply_is_new(new, cutoff) is True
    assert reply_is_new(exact, cutoff) is True          # inclusive
    assert reply_is_new(old, None) is True              # no cutoff, all new


# --------------------------------------------------------------------------
# OwnerThread
# --------------------------------------------------------------------------


@pytest.fixture
def thread(reply):
    return OwnerThread(
        comment={"comment_id": "t1", "author": "@owner"},
        replies=[
            reply("r1", "@alice", "aimed at you", "2026-01-01T00:00:00Z"),
            reply("r2", "@owner", "@alice my answer", "2026-01-02T00:00:00Z",
                  channel_id=OWNER),
            reply("r3", "@bob", "@alice side chat", "2026-01-03T00:00:00Z"),
        ],
        new_replies=[
            reply("r3", "@bob", "@alice side chat", "2026-01-03T00:00:00Z"),
        ],
        reported_reply_count=3,
    )


def test_counts_exclude_your_own_replies(thread):
    """Your own replies are context, not inbox."""

    audience = thread.audience_replies(OWNER)

    assert len(audience) == 2
    assert "@owner" not in [r["author"] for r in audience]


def test_audience_and_direct_replies_are_different_numbers(thread):
    """On one real thread 161 audience replies contained only 92 aimed at you.

    Reporting the first as the second overstates what is actually owed.
    """

    assert len(thread.audience_replies(OWNER)) == 2
    assert len(thread.direct_replies(OWNER)) == 1
    assert thread.direct_replies(OWNER)[0]["author"] == "@alice"


def test_a_truncated_reply_thread_is_reported_as_incomplete():
    """Silence about a partial fetch reads as "this is everything"."""

    complete = OwnerThread(replies=[{"comment_id": "r1"}], reported_reply_count=1)
    partial = OwnerThread(replies=[{"comment_id": "r1"}], reported_reply_count=178)

    assert complete.truncated is False
    assert partial.truncated is True


def test_new_direct_replies_are_the_intersection(thread, reply):
    """New and aimed-at-you are separate filters; the queue needs both."""

    assert thread.new_direct_replies(OWNER) == []

    thread.new_replies = [
        reply("r1", "@alice", "aimed at you", "2026-01-01T00:00:00Z"),
    ]
    assert [r["comment_id"] for r in thread.new_direct_replies(OWNER)] == ["r1"]


def test_an_absent_owner_channel_keeps_every_reply(thread):
    """Without an identity there is nothing to exclude, so exclude nothing."""

    assert len(thread.audience_replies("")) == 3
    assert len(thread.new_audience_replies("")) == 1


def test_the_thread_reports_its_own_comment_id():
    assert OwnerThread(comment={"comment_id": "t9"}).comment_id == "t9"
    assert OwnerThread().comment_id == ""
