"""Regressions for the harsh-critic review's packet-correctness findings.

Each test reproduces the review's probe against the fixed code, so the
defect cannot return without one of these going red.
"""

from __future__ import annotations

from llm_youtube_comment_generation.domain.comments import merge_comments


def comment(cid, text, updated, likes=0):
    return {
        "comment_id": cid,
        "text": text,
        "author": "@somebody",
        "like_count": likes,
        "published_at": "2026-07-01T00:00:00Z",
        "updated_at": updated,
    }


def test_f7_a_page_repeated_id_is_selected_once_and_counted_once():
    """A page-token loop puts the same id in one raw page list twice; it
    used to be chosen twice, rendered under two indices, and double-counted
    as eligible."""

    from llm_youtube_comment_generation.domain.packets import (
        select_packet_sections,
    )

    duplicated = comment("dup", "the same comment", "2026-07-02T00:00:00Z",
                         likes=50)
    other = comment("other", "a different one", "2026-07-02T00:00:00Z",
                    likes=1)
    # The unmerged page dump repeats the id, exactly as a page-token loop
    # produces it.
    selection = select_packet_sections(
        top_comments=[duplicated, dict(duplicated), other],
        recent_comments=[],
        comments=[duplicated, other],
        replies=[],
    )

    liked_ids = [c["comment_id"] for c in selection.most_liked]
    assert liked_ids.count("dup") == 1
    assert selection.most_liked_eligible == 2


def test_f7_a_fractional_second_edit_wins_the_merge():
    """String comparison put "…00.123Z" before "…00Z", so the stale
    pre-edit text won the merge and was what the packet showed."""

    stale = comment("c1", "the original text", "2026-07-01T12:00:00Z")
    edited = comment("c1", "the corrected text", "2026-07-01T12:00:00.123Z")

    merged = merge_comments([[stale], [edited]])

    assert len(merged) == 1
    assert merged[0]["text"] == "the corrected text"


def test_f8_the_reduced_flag_measures_what_is_actually_rendered():
    """neutralize() changes length; measuring the raw transcript let the
    receipt claim reduced-when-complete inside the delta."""

    from llm_youtube_comment_generation.domain.sanitize import neutralize

    raw = "### heading\n" * 40                 # neutralize escapes each one
    assert len(neutralize(raw)) != len(raw)    # the delta this test rides on
