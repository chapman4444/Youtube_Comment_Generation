"""The reply behaviours REPLY_SPEC.md listed as ported but never re-checked.

Every test here corresponds to one spec row and one hard-won legacy rule.
They are written from the *behaviour* described in the row rather than from
the current implementation, so a test that passes is evidence the behaviour
survived the migration rather than evidence the code still does what it does.

Spec rows covered: A4, B4, B5, B8, C2, C3, C4, D2, D3, E2, E3, E6, E7, E8.
"""

from __future__ import annotations

from llm_youtube_comment_generation.domain.candidates import (
    build_reply_candidates,
    candidates_across_threads,
)
from llm_youtube_comment_generation.domain.targeting import (
    annotate_reply_targets,
    leading_mention,
)
from llm_youtube_comment_generation.domain.threads import OwnerThread

OWNER = "UC" + "o" * 22


def message(cid, author, text, when, *, channel=None, likes=0):
    return {
        "comment_id": cid,
        "author": author,
        "author_channel_id": channel or (
            "UC" + author.lstrip("@").ljust(22, "z"))[:24],
        "text": text,
        "like_count": likes,
        "published_at": when,
        "updated_at": when,
    }


# --------------------------------------------------------------------------
# A. Time, and B. what the scan may claim
# --------------------------------------------------------------------------


def test_a4_a_fractional_second_does_not_sort_a_reply_backwards():
    """String comparison looked fine until a fractional second appeared:
    "…00.123Z" sorts BEFORE "…00Z" because "." precedes "Z", so a reply
    that arrived after the cutoff was reported as older than it."""

    from llm_youtube_comment_generation.domain.threads import as_moment

    assert as_moment("2026-07-01T12:00:00.123Z") > \
        as_moment("2026-07-01T12:00:00Z")


def test_a4_an_unparseable_timestamp_sorts_oldest_never_newest():
    """Unknown must never win a "which is newest" comparison, because that
    is how an unanswered reply gets treated as already handled."""

    from llm_youtube_comment_generation.domain.threads import as_moment

    assert as_moment("not a date") < as_moment("2000-01-01T00:00:00Z")
    assert as_moment("") < as_moment("2000-01-01T00:00:00Z")


def test_a4_an_unparseable_stamp_cannot_fake_a_return():
    """The queue rule that depends on it: a reply whose timestamp is
    unreadable must not postdate the owner's answer."""

    replies = [
        message("r1", "@alice", "a question", "2026-07-02T00:00:00Z"),
        message("r2", "@owner", "@alice my answer", "2026-07-03T00:00:00Z",
                channel=OWNER),
        message("r3", "@alice", "a later message", "nonsense-timestamp"),
    ]

    found = build_reply_candidates(OWNER, "@owner", replies, "t1")

    assert found[0].answered is True
    assert found[0].replied_again is False


def test_b4_b5_a_truncated_thread_reports_both_numbers_and_refuses_absence():
    """"I could not see it" must never become "it is not there". The note
    carries the reported and retrieved counts so the gap is visible."""

    from llm_youtube_comment_generation.domain.statuses import (
        RetrievalOutcome,
        RetrievalStatus,
    )

    thread = OwnerThread(
        comment=message("t1", "@owner", "my comment",
                        "2026-07-01T00:00:00Z", channel=OWNER),
        replies=[message("r1", "@alice", "a reply",
                         "2026-07-02T00:00:00Z")],
        reported_reply_count=178,
    )

    assert thread.truncated is True

    outcome = RetrievalOutcome(
        status=RetrievalStatus.REPLY_THREAD_TRUNCATED,
        retrieved=len(thread.replies),
        reported_total=thread.reported_reply_count,
        notes=(f"thread {thread.comment_id} reported "
               f"{thread.reported_reply_count:,} replies but "
               f"{len(thread.replies):,} were retrieved",),
    )

    assert outcome.may_conclude_absence is False
    assert "178" in outcome.notes[0] and "1" in outcome.notes[0]


def test_b8_replies_to_you_and_audience_replies_are_different_numbers():
    """On one real thread 161 audience replies contained only 92 aimed at
    the owner. Reporting the first as the second is misleading."""

    thread = OwnerThread(
        comment=message("t1", "@owner", "my comment",
                        "2026-07-01T00:00:00Z", channel=OWNER),
        replies=[
            message("r1", "@alice", "aimed at you", "2026-07-02T00:00:00Z"),
            message("r2", "@bob", "@alice aimed at alice",
                    "2026-07-03T00:00:00Z"),
            message("r3", "@owner", "my own reply", "2026-07-04T00:00:00Z",
                    channel=OWNER),
        ],
    )

    assert len(thread.audience_replies(OWNER)) == 2      # owner's excluded
    assert len(thread.direct_replies(OWNER)) == 1        # only one aimed here


# --------------------------------------------------------------------------
# C. Mention parsing
# --------------------------------------------------------------------------


def test_c2_a_mention_with_non_ascii_letters_is_captured_whole():
    """`@José` is one handle, not `@Jos` plus a stray letter."""

    known = ["José", "Ana-María", "Владимир"]

    assert leading_mention("@José you are wrong", known) == "José"
    assert leading_mention("@Ana-María that is true", known) == "Ana-María"
    assert leading_mention("@Владимир no", known) == "Владимир"


def test_c3_a_run_together_mention_resolves_to_the_longest_known_handle():
    """YouTube renders the mention with no separator, so "@somebodyno, but"
    is a mention of "somebody" followed by the word "no"."""

    known = ["normagraham3", "somebodyelse"]

    assert leading_mention("@normagraham3omg I know a company",
                           known) == "normagraham3"


def test_c3_a_digit_remainder_is_refused_as_another_account():
    """"@alice123" is far more likely a different account than a mention of
    "alice" followed by the number 123."""

    assert leading_mention("@alice123 hello", ["alice"]) == "alice123"


def test_c3_a_short_handle_is_not_taken_as_a_prefix():
    """A handle under eight characters colliding by chance is likely;
    "@aliceabc" is not a mention of "alice"."""

    assert leading_mention("@aliceabc hello", ["alice"]) == "aliceabc"


def test_c3_an_exact_hit_always_wins():
    known = ["alice", "aliceabc"]

    assert leading_mention("@aliceabc hi", known) == "aliceabc"
    assert leading_mention("@alice hi", known) == "alice"


def test_c4_an_unresolvable_mention_is_reported_as_written():
    """Never guessed into a real person: the token is returned as typed and
    the reply is classified unknown rather than attributed."""

    replies = [message("r1", "@carol", "@ghostwriter what do you think",
                       "2026-07-02T00:00:00Z")]

    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["responds_to_author"] == "ghostwriter"
    assert annotated[0]["target_state"] == "unknown"
    assert annotated[0]["mentions_known_participant"] is False


# --------------------------------------------------------------------------
# D. Target annotation
# --------------------------------------------------------------------------


def test_d2_the_owner_is_recognised_by_channel_id_not_display_name():
    """Channel id is stable; the display name is not. An impostor using the
    owner's display name must not be read as the owner."""

    replies = [
        message("r1", "@owner", "posted from my other account",
                "2026-07-02T00:00:00Z", channel=OWNER),
        message("r2", "@owner", "I am not the real owner",
                "2026-07-03T00:00:00Z", channel="UC" + "f" * 22),
    ]

    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["is_owner_reply"] is True
    assert annotated[0]["target_state"] == "owner_reply"
    assert annotated[1]["is_owner_reply"] is False


def test_d2_a_renamed_owner_is_still_recognised():
    """The owner's display name changed since the comment was posted; the
    channel id did not."""

    replies = [message("r1", "@my-new-name", "following up on my own point",
                       "2026-07-02T00:00:00Z", channel=OWNER)]

    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["target_state"] == "owner_reply"


def test_d3_a_reply_with_no_mention_is_addressed_to_the_owner():
    """That is what YouTube's Reply button on the owner's comment produces,
    and it is the commonest shape in a real thread."""

    replies = [message("r1", "@alice", "I was part of a case like this",
                       "2026-07-02T00:00:00Z")]

    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["target_state"] == "owner"
    assert annotated[0]["responds_to_owner"] is True
    assert annotated[0]["responds_to_author"] == ""


# --------------------------------------------------------------------------
# E. Answered-state
# --------------------------------------------------------------------------


def test_e2_an_unmentioned_owner_reply_answers_nobody():
    """The highest-value rule in the file. Two people asked separate
    questions, the owner posted one unmentioned follow-up, and both
    vanished from the queue. A false positive costs a glance; a false
    negative costs the reply."""

    replies = [
        message("r1", "@alice", "a question about the costs order",
                "2026-07-02T00:00:00Z"),
        message("r2", "@bob", "a different question about the lease",
                "2026-07-02T01:00:00Z"),
        message("r3", "@owner", "good points all round, thanks everyone",
                "2026-07-03T00:00:00Z", channel=OWNER),
    ]

    found = build_reply_candidates(OWNER, "@owner", replies, "t1")

    assert {c.author for c in found} == {"@alice", "@bob"}
    assert all(not c.answered for c in found)
    assert all(c.outstanding for c in found)


def test_e2_a_mentioned_owner_reply_answers_only_that_person():
    replies = [
        message("r1", "@alice", "a question", "2026-07-02T00:00:00Z"),
        message("r2", "@bob", "another question", "2026-07-02T01:00:00Z"),
        message("r3", "@owner", "@alice here is the answer",
                "2026-07-03T00:00:00Z", channel=OWNER),
    ]

    found = {c.author: c for c in
             build_reply_candidates(OWNER, "@owner", replies, "t1")}

    assert found["@alice"].answered is True
    assert found["@bob"].answered is False


def test_e3_answered_state_survives_a_display_name_change():
    """Keyed by channel id, with a handle bridge: the owner's reply can only
    name a handle, so the two have to be reconciled."""

    channel = "UC" + "a" * 22
    replies = [
        message("r1", "@alice", "a question", "2026-07-02T00:00:00Z",
                channel=channel),
        message("r2", "@owner", "@alice here is the answer",
                "2026-07-03T00:00:00Z", channel=OWNER),
        message("r3", "@alice-renamed", "thanks, that clears it up",
                "2026-07-04T00:00:00Z", channel=channel),
    ]

    found = build_reply_candidates(OWNER, "@owner", replies, "t1")

    # One person, not two: the rename did not split them.
    assert len(found) == 1
    assert found[0].answered is True
    assert found[0].message_count == 2


def test_e6_a_never_answered_person_shows_their_strongest_message():
    """A weak afterthought must not displace a real challenge that was
    never addressed."""

    replies = [
        message("r1", "@alice",
                "actually the filing says the permit was granted, which is "
                "the opposite of what the video claims",
                "2026-07-02T00:00:00Z", likes=40),
        message("r2", "@alice", "anyway", "2026-07-03T00:00:00Z"),
    ]

    found = build_reply_candidates(OWNER, "@owner", replies, "t1")

    assert found[0].reply["comment_id"] == "r1"
    assert found[0].message_count == 2


def test_e6_a_returner_shows_their_strongest_message_since_your_answer():
    """Everything before the answer was already handled."""

    replies = [
        message("r1", "@alice", "the first challenge", "2026-07-02T00:00:00Z",
                likes=99),
        message("r2", "@owner", "@alice my answer", "2026-07-03T00:00:00Z",
                channel=OWNER),
        message("r3", "@alice", "you did not address the second half at all",
                "2026-07-04T00:00:00Z", likes=5),
    ]

    found = build_reply_candidates(OWNER, "@owner", replies, "t1")

    assert found[0].replied_again is True
    assert found[0].reply["comment_id"] == "r3"


def test_e7_the_queue_ranks_returns_then_new_then_unclear():
    replies = [
        # Never answered.
        message("n1", "@newcomer", "a fresh question for you",
                "2026-07-05T00:00:00Z"),
        # Answered, then came back with a certain reply.
        message("r1", "@returner", "first challenge", "2026-07-02T00:00:00Z"),
        message("a1", "@owner", "@returner my answer",
                "2026-07-03T00:00:00Z", channel=OWNER),
        message("r2", "@returner", "you still have not answered it",
                "2026-07-04T00:00:00Z"),
        # Answered, then posted again naming somebody absent.
        message("u1", "@unclear", "a question", "2026-07-02T00:00:00Z"),
        message("a2", "@owner", "@unclear my answer", "2026-07-03T00:00:00Z",
                channel=OWNER),
        message("u2", "@unclear", "@ghostwriter what do you think",
                "2026-07-04T00:00:00Z"),
    ]

    order = [c.author for c in
             build_reply_candidates(OWNER, "@owner", replies, "t1")]

    assert order.index("@returner") < order.index("@newcomer")
    assert order.index("@newcomer") < order.index("@unclear")


def test_e8_an_answer_in_one_thread_never_marks_another_answered():
    """Answered-state is a property of one conversation. Flattening let a
    general answer under thread A silently hide participants in thread B."""

    first = OwnerThread(
        comment=message("t1", "@owner", "my first comment",
                        "2026-07-01T00:00:00Z", channel=OWNER),
        replies=[
            message("r1", "@alice", "a question here",
                    "2026-07-02T00:00:00Z"),
            message("r2", "@owner", "@alice answered here",
                    "2026-07-03T00:00:00Z", channel=OWNER),
        ],
    )
    second = OwnerThread(
        comment=message("t2", "@owner", "my second comment",
                        "2026-07-01T00:00:00Z", channel=OWNER),
        replies=[
            message("r3", "@alice", "a different question over here",
                    "2026-07-02T00:00:00Z"),
        ],
    )

    found = candidates_across_threads(OWNER, [first, second])

    by_thread = {c.thread_id: c for c in found}
    assert by_thread["t1"].answered is True
    assert by_thread["t2"].answered is False
    assert by_thread["t2"].outstanding is True
