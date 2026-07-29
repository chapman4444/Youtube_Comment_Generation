"""Keyword frequencies from a transcript.

Adapted from the operator's parse_words project. These tests pin the things
that differ from that corpus: our transcripts carry timestamps and speaker
markers, and the words worth counting are the ones nobody predicted.
"""

from __future__ import annotations

from llm_youtube_comment_generation.domain.transcript_words import (
    keyword_frequencies,
    load_word_list,
    render_table,
    strip_markup,
    summarise,
    tokenize,
)

TRANSCRIPT = "\n".join([
    "[00:00:00] >> Yeah, so the shotgun question came up again.",
    "[00:00:04] >> Okay, but the shotgun is the part that matters.",
    "[00:01:09] >> Um, the appropriate legal channels, he said.",
    "[00:01:36] >> I personally encourage people to carry legally. 😂",
])

STOPWORDS = {"yeah", "okay", "the", "so", "but", "is", "that", "he", "said",
             "and", "to", "up", "again", "part", "matters", "came"}


def test_timestamps_never_become_words():
    """Otherwise "00" is the most frequent keyword in every transcript."""

    rows = keyword_frequencies(TRANSCRIPT, STOPWORDS)
    words = [row.word for row in rows]

    assert "00" not in words
    assert not any(word.isdigit() for word in words)


def test_caption_annotations_are_not_spoken_words():
    """Auto-captioning writes [music], [laughter] and [ __ ] for a bleep.

    On a real transcript music ranked ninth and laughter thirty-ninth.
    Nobody said either word.
    """

    rows = keyword_frequencies(
        "[00:00:26] criminal case [music] against them [laughter] again "
        "[ __ ] [snorts]",
        {"against", "them", "again"},
    )
    words = [row.word for row in rows]

    assert words == ["case", "criminal"]
    assert "music" not in words
    assert "laughter" not in words
    assert "snorts" not in words


def test_speaker_markers_are_removed_before_counting():
    assert ">>" not in strip_markup(TRANSCRIPT)
    assert "[00:00:00]" not in strip_markup(TRANSCRIPT)


def test_the_repeated_content_word_comes_first():
    rows = keyword_frequencies(TRANSCRIPT, STOPWORDS)

    assert rows[0].word == "shotgun"
    assert rows[0].count == 2


def test_filler_on_the_stopword_list_is_gone():
    words = [row.word for row in keyword_frequencies(TRANSCRIPT, STOPWORDS)]

    assert "yeah" not in words
    assert "okay" not in words


def test_short_tokens_are_dropped_whatever_the_stopword_list_says():
    """Speech is full of "um", "im" and "ok". No list catches them all."""

    rows = keyword_frequencies("[00:00:01] um ok im so uh", set())

    assert rows == []


def test_emoji_are_not_tokens():
    assert tokenize("great 😂 point") == ["great", "point"]


def test_the_order_is_stable_when_counts_tie():
    """The same transcript has to produce the same table twice."""

    text = "[00:00:01] zebra apple zebra apple mango"
    rows = keyword_frequencies(text, set())

    assert [row.word for row in rows] == ["apple", "zebra", "mango"]
    assert keyword_frequencies(text, set()) == rows


def test_a_minimum_count_drops_the_long_tail():
    rows = keyword_frequencies(TRANSCRIPT, STOPWORDS, minimum_count=2)

    assert all(row.count >= 2 for row in rows)
    assert rows


# -- word lists ------------------------------------------------------------


def test_comments_and_blank_lines_are_not_words():
    loaded = load_word_list("# a comment\n\nyeah\n  okay  \n#another\n")

    assert loaded == {"yeah", "okay"}


def test_word_lists_are_lower_cased_on_load():
    assert load_word_list("Yeah\nOKAY") == {"yeah", "okay"}


# -- the rendered table ----------------------------------------------------


def test_the_table_states_how_much_was_filtered():
    """A list of words says nothing about whether the filter worked."""

    rows, total, removed = summarise(TRANSCRIPT, STOPWORDS)
    table = render_table(rows, total_tokens=total, removed=removed)

    assert "shotgun" in table
    assert f"{total:,} tokens" in table
    assert "removed as filler" in table


def test_an_empty_result_says_which_kind_of_empty():
    """Nothing to count and everything filtered look identical otherwise."""

    table = render_table([])

    assert "empty" in table
    assert "stopword list" in table


def test_a_contraction_is_filtered_without_its_apostrophe():
    """"that's" tokenizes to "thats", which no apostrophe entry can match.

    It was the top keyword of a real transcript for exactly this reason.
    """

    rows = keyword_frequencies(
        "[00:00:01] thats what he said, thats the point",
        {"that's", "what", "he", "said", "the", "point"},
    )

    assert [row.word for row in rows] == []


def test_deriving_the_stripped_form_needs_no_edit_to_the_word_list():
    """The list is the operator's data. The fix belongs in the matching."""

    assert keyword_frequencies("[00:00:01] wont cant couldnt",
                               {"won't", "can't", "couldn't"}) == []


def test_a_truncated_table_still_reports_the_whole_result():
    """A --top 15 run reported "15 distinct keywords" for 436 of them."""

    rows, total, removed = summarise(TRANSCRIPT, STOPWORDS)
    table = render_table(rows[:2], total_tokens=total, removed=removed,
                         distinct=len(rows))

    assert f"{len(rows):,} distinct keywords" in table
    assert "2 distinct keywords" not in table


def test_the_counts_reconcile():
    """Tokens seen must equal tokens kept plus tokens removed."""

    rows, total, removed = summarise(TRANSCRIPT, STOPWORDS)

    assert sum(row.count for row in rows) + removed == total
