"""Mention parsing and reply-target reconstruction.

Measured across 860 real replies there is no true nesting in the YouTube API
at all, and 25 percent of replies open with an @mention. These rules are how
a flat list becomes a conversation.
"""

from __future__ import annotations

from llm_youtube_comment_generation.domain.targeting import (
    INVISIBLE_CHARACTERS,
    annotate_reply_targets,
    leading_mention,
    strip_invisible,
)

OWNER = "UC" + "o" * 22


def test_the_invisible_character_set_is_exactly_what_youtube_inserts():
    """New in the port.

    The constant is written as escape sequences because the characters are
    invisible in an editor and do not survive a careless encoding round-trip.
    A comment cannot enforce that; this can.
    """

    assert INVISIBLE_CHARACTERS == "​‌‍⁠﻿"
    assert [ord(c) for c in INVISIBLE_CHARACTERS] == [
        0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF
    ]


def test_strip_invisible_removes_format_characters():
    assert strip_invisible("​@alice hi") == "@alice hi"
    assert strip_invisible("﻿⁠  text") == "text"
    assert strip_invisible("") == ""
    assert strip_invisible(None) == ""


def test_zero_width_space_before_a_mention_is_handled():
    """U+200B is category Cf, not whitespace, so \\s never matched it."""

    assert leading_mention("​@alice hello", ["alice"]) == "alice"


def test_mention_running_into_a_word_still_resolves():
    """The rendered mention runs straight into the next word, with no space."""

    assert leading_mention("@somebodyno, but", ["somebody"]) == "somebody"


def test_mention_running_into_the_next_word_is_split_correctly():
    known = ["longhandlename", "other"]
    assert leading_mention("@longhandlenameyes it is", known) == "longhandlename"


def test_short_handle_is_not_matched_as_a_prefix():
    """"@aliceabc" is not a mention of "alice"; the handle is too short."""

    assert leading_mention("@aliceabc hi", ["alice"]) == "aliceabc"


def test_a_digit_remainder_is_a_different_account():
    """Ported from the prefix rules: "@alice123" is not "alice" plus a number."""

    assert leading_mention("@alice123", ["alice"]) == "alice123"


def test_longer_handles_are_not_shadowed_by_shorter_ones():
    known = ["alicejohnson", "alice"]
    assert leading_mention("@alicejohnson hi", known) == "alicejohnson"


def test_mention_of_a_longer_handle_is_not_attributed_to_a_shorter_one():
    known = ["bob", "bobbytables"]
    assert leading_mention("@bobbytables hello", known) == "bobbytables"


def test_mention_of_an_absent_participant_is_flagged():
    """Report it as written rather than guessing at a real person."""

    assert leading_mention("@ghostuser what?", ["alice"]) == "ghostuser"


def test_an_exact_hit_always_wins():
    assert leading_mention("@alice hi", ["alice", "alicejohnson"]) == "alice"


def test_text_with_no_mention_yields_nothing():
    assert leading_mention("just talking", ["alice"]) == ""
    assert leading_mention("", ["alice"]) == ""


# --------------------------------------------------------------------------
# Target reconstruction
# --------------------------------------------------------------------------


def build(reply, entries):
    return [reply(*entry[:4], **entry[4]) for entry in entries]


def test_replies_without_a_mention_answer_the_owner(reply):
    """YouTube's Reply button on the owner's comment adds no mention."""

    replies = [reply("r1", "@alice", "you are wrong", "2026-01-01T00:00:00Z")]
    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["target_state"] == "owner"
    assert annotated[0]["responds_to_owner"] is True
    assert annotated[0]["responds_to_author"] == ""


def test_mention_of_the_owner_counts_as_answering_the_owner(reply):
    replies = [reply("r1", "@alice", "@owner you are wrong", "2026-01-01T00:00:00Z")]
    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["target_state"] == "owner"
    assert annotated[0]["responds_to_owner"] is True
    assert annotated[0]["responds_to_author"] == "owner"


def test_both_ways_of_addressing_the_owner_count(reply):
    replies = [
        reply("r1", "@alice", "no mention here", "2026-01-01T00:00:00Z"),
        reply("r2", "@bob", "@owner named you", "2026-01-02T00:00:00Z"),
    ]
    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert [r["responds_to_owner"] for r in annotated] == [True, True]


def test_replies_mentioning_someone_else_are_a_side_conversation(reply):
    replies = [
        reply("r1", "@alice", "first point", "2026-01-01T00:00:00Z"),
        reply("r2", "@bob", "@alice I disagree", "2026-01-02T00:00:00Z"),
    ]
    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[1]["target_state"] == "other"
    assert annotated[1]["responds_to_owner"] is False
    assert annotated[1]["responds_to_author"] == "alice"


def test_owner_replies_are_labelled_as_the_owners(reply):
    replies = [
        reply("r1", "@owner", "@alice no", "2026-01-01T00:00:00Z",
              channel_id=OWNER),
    ]
    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["is_owner_reply"] is True
    assert annotated[0]["target_state"] == "owner_reply"


def test_owner_is_never_a_reply_target(reply):
    """Channel ID is stable; the display name is not.

    A reply written by the owner cannot be a reply to the owner however it is
    worded, because identity is decided by channel and not by handle.
    """

    replies = [
        reply("r1", "@owner", "@owner talking to myself", "2026-01-01T00:00:00Z",
              channel_id=OWNER),
    ]
    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["is_owner_reply"] is True
    assert annotated[0]["responds_to_owner"] is False


def test_an_unresolved_target_is_not_described_as_a_side_exchange(reply):
    """Three states, not two.

    Guessing "side exchange" for a mention naming somebody absent made
    legitimate replies disappear from the queue.
    """

    replies = [reply("r1", "@alice", "@ghostuser what?", "2026-01-01T00:00:00Z")]
    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["target_state"] == "unknown"
    assert annotated[0]["target_state"] != "other"
    assert annotated[0]["mentions_known_participant"] is False


def test_resolved_mentions_are_still_classified_normally(reply):
    replies = [
        reply("r1", "@alice", "first", "2026-01-01T00:00:00Z"),
        reply("r2", "@bob", "@alice yes", "2026-01-02T00:00:00Z"),
    ]
    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[1]["mentions_known_participant"] is True
    assert annotated[1]["target_state"] == "other"


def test_annotation_does_not_mutate_the_input(reply):
    replies = [reply("r1", "@alice", "hello", "2026-01-01T00:00:00Z")]
    before = [dict(record) for record in replies]

    annotate_reply_targets("@owner", replies, OWNER)

    assert replies == before
    assert "target_state" not in replies[0]
