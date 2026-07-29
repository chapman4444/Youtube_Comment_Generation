"""Packet budgeting and section selection."""

from __future__ import annotations

from llm_youtube_comment_generation.domain.packets import (
    CAPS,
    DEFAULT_PACKET_CHARACTERS,
    FLOORS,
    MINIMUM_PACKET_CHARACTERS,
    PACKET_SCAFFOLDING_ALLOWANCE,
    grow,
    select_packet_sections,
)


def test_minimum_exceeds_its_own_protected_floors():
    """The advertised minimum has to be reachable.

    most_replied_comments belongs in the protected slots: that section is
    rendered and never cut, so leaving it out understated the mandatory cost
    and made the minimum unreachable on any video whose comments have replies.
    """

    assert CAPS.protected_comment_slots == 75 + 30 + 40 + 20
    assert MINIMUM_PACKET_CHARACTERS > (
        PACKET_SCAFFOLDING_ALLOWANCE + FLOORS.transcript + FLOORS.description
    )
    assert DEFAULT_PACKET_CHARACTERS > MINIMUM_PACKET_CHARACTERS


def test_highest_liked_section_actually_holds_the_highest_liked(comment):
    """Relevance used to go first and eat them.

    On one measured video the highest-liked section's ceiling was 82 likes
    while the relevance section above it carried a comment with 7,211.
    """

    pool = [comment(f"c{i}", likes=i * 100) for i in range(10)]
    relevance_order = list(pool)                 # relevance likes the big ones too

    selection = select_packet_sections(relevance_order, [], pool, [])

    assert max(c["like_count"] for c in selection.most_liked) == 900


def test_most_replied_is_a_separate_list_from_most_liked(comment):
    """Measured across 1,506 real comments the two top-40 lists overlap 67%.

    The pool has to exceed the most-liked cap for this to be observable at
    all: sections are filled in order and each one consumes what it takes, so
    on a pool of ten the most-liked section absorbs every comment and the
    most-replied section is legitimately empty.
    """

    liked = [comment(f"liked{i}", likes=1000 - i, replies=0) for i in range(40)]
    replied = [comment(f"replied{i}", likes=0, replies=50 - i) for i in range(5)]

    selection = select_packet_sections([], [], liked + replied, [])

    assert len(selection.most_liked) == CAPS.most_liked_comments
    assert all(c["comment_id"].startswith("liked") for c in selection.most_liked)
    assert {c["comment_id"] for c in selection.most_replied} == \
           {f"replied{i}" for i in range(5)}


def test_comments_without_replies_never_enter_the_replied_list(comment):
    """Filled with enough high-liked filler that the two sections are distinct."""

    filler = [comment(f"f{i}", likes=500 - i, replies=0) for i in range(35)]
    pool = filler + [comment("a", likes=0, replies=0),
                     comment("b", likes=0, replies=3)]

    selection = select_packet_sections([], [], pool, [])

    assert [c["comment_id"] for c in selection.most_replied] == ["b"]
    assert "a" not in {c["comment_id"] for c in selection.most_replied}


def test_sections_do_not_repeat_a_comment(comment):
    """Every section draws from one pool, and a comment is used once."""

    pool = [comment(f"c{i}", likes=i, replies=i % 3) for i in range(30)]

    selection = select_packet_sections(pool, pool, pool, [])
    rendered = (selection.most_liked + selection.most_replied
                + selection.relevant + selection.recent)
    ids = [c["comment_id"] for c in rendered]

    assert len(ids) == len(set(ids))
    assert selection.rendered_ids == set(ids)


def test_eligibility_counts_what_was_available_not_what_was_shown(comment):
    """The reduction summary reports real eligibility, so it must be counted."""

    pool = [comment(f"c{i}", likes=i) for i in range(50)]

    selection = select_packet_sections([], [], pool, [], caps=CAPS)

    assert len(selection.most_liked) == CAPS.most_liked_comments
    assert selection.most_liked_eligible == 50


def test_threads_are_ordered_by_live_conversation(comment, reply):
    """The parent's reported reply count leads, then the fetched depth."""

    parents = [comment("busy", replies=100), comment("quiet", replies=2)]
    replies = [
        reply("r1", "@a", "x", "2026-01-02T00:00:00Z", parent="quiet"),
        reply("r2", "@b", "y", "2026-01-01T00:00:00Z", parent="busy"),
    ]

    selection = select_packet_sections([], [], parents, replies)

    assert [parent["comment_id"] for parent, _ in selection.threads] == \
           ["busy", "quiet"]


def test_replies_render_in_chronological_order(comment, reply):
    parents = [comment("p", replies=3)]
    replies = [
        reply("r3", "@c", "third", "2026-01-03T00:00:00Z", parent="p"),
        reply("r1", "@a", "first", "2026-01-01T00:00:00Z", parent="p"),
        reply("r2", "@b", "second", "2026-01-02T00:00:00Z", parent="p"),
    ]

    selection = select_packet_sections([], [], parents, replies)
    _, thread = selection.threads[0]

    assert [r["comment_id"] for r in thread] == ["r1", "r2", "r3"]


def test_a_reply_to_an_unretrieved_parent_still_forms_a_thread(comment, reply):
    """Losing the thread because the parent was not in the page is silent data loss."""

    replies = [reply("r1", "@a", "x", "2026-01-01T00:00:00Z", parent="missing")]

    selection = select_packet_sections([], [], [], replies)

    assert selection.threads[0][0] == {"comment_id": "missing"}


def test_caps_never_shrink_below_the_defaults():
    """grow() is one-way. A factor of one is the identity."""

    assert grow(CAPS, 1) == CAPS

    for factor in (2, 5, 12):
        grown = grow(CAPS, factor)
        assert grown.relevant_comments >= CAPS.relevant_comments
        assert grown.recent_comments >= CAPS.recent_comments


def test_caps_grow_into_an_unused_budget():
    """The defaults are a floor, not a ceiling.

    On a typical run they rendered 145 comments while leaving roughly three
    quarters of the character budget unspent.
    """

    grown = grow(CAPS, 4)

    assert grown.relevant_comments == 300
    assert grown.recent_comments == 100


def test_the_showcase_section_does_not_scale(comment):
    """Scaling it made it swallow the pool, emptying relevance and recent."""

    grown = grow(CAPS, 8)

    assert grown.most_liked_comments == CAPS.most_liked_comments
    assert grown.most_replied_comments == CAPS.most_replied_comments
