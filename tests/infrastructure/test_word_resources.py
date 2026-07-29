"""The operator's word lists, shipped as package data.

The lists came from his parse_words project, which is not modified. The copy
of omit_words.txt has to stay identical to it, so that a future divergence is
something somebody chose rather than something that drifted.
"""

from __future__ import annotations

from llm_youtube_comment_generation.domain.transcript_words import (
    keyword_frequencies,
)
from llm_youtube_comment_generation.infrastructure import word_resources


def test_the_default_filter_is_both_lists():
    assert word_resources.TRANSCRIPT_STOPWORDS == (
        "omit_words.txt", "spoken_extra.txt",
    )


def test_the_ported_list_is_still_the_size_it_was_copied_at():
    """353 words. A silent edit to it is a silent change to every table."""

    assert len(word_resources.load("omit_words.txt")) == 353


def test_the_spoken_filler_list_is_a_subset_of_the_standard_one():
    """custom_stopwords.txt adds nothing, which is why it is not loaded.

    Its 346 words are all already in omit_words.txt. Loading both would load
    one of them twice.
    """

    custom = word_resources.load("custom_stopwords.txt")
    omit = word_resources.load("omit_words.txt")

    assert custom <= omit


def test_comments_in_a_list_file_are_not_words():
    """spoken_extra.txt opens with a paragraph of explanation."""

    extra = word_resources.load("spoken_extra.txt")

    assert not any(word.startswith("#") for word in extra)
    assert "think" in extra
    assert "guys" in extra


def test_topic_words_are_never_filtered():
    """The point of the table is the word nobody predicted.

    A stopword list that swallows "police" on a police video has destroyed
    the only thing the table was for.
    """

    stopwords = word_resources.stopwords()

    for topic in ("police", "criminal", "case", "report", "shotgun",
                  "lawyer", "investigation", "money"):
        assert topic not in stopwords


def test_the_default_filter_removes_the_words_that_topped_a_real_table():
    text = "[00:00:01] I think you know it was going to be a good one guys"
    words = [row.word for row in
             keyword_frequencies(text, word_resources.stopwords())]

    for filler in ("think", "know", "going", "guys"):
        assert filler not in words


def test_words_that_could_be_the_subject_survive_the_filter():
    """Which words those are was measured, not decided by taste.

    tools/measure_filler.py over sixteen transcripts: a word is filler when
    it appears in nearly every video and its busiest video uses it at close
    to its median rate. "good" appears in ten of sixteen and spikes 4.2x
    where it matters, so it stays countable. "one" appears in all sixteen at
    a flat 2.3x, so it does not.

    The risk is not symmetric: a filler word left in costs one line the
    reader skips, and a topic word filtered out is signal that disappears
    with nothing in the output to say it is missing.
    """

    text = "[00:00:01] I think you know it was going to be a good one guys"
    words = [row.word for row in
             keyword_frequencies(text, word_resources.stopwords())]

    assert "good" in words

    survivors = word_resources.stopwords()
    for topical in ("people", "real", "part", "time", "way", "whole",
                    "great", "huge", "little", "good"):
        assert topical not in survivors, f"{topical} spikes where it matters"


def test_the_words_the_corpus_calls_filler_are_filtered():
    """Everywhere, and evenly spread: measured at 2.5x median or below."""

    survivors = word_resources.stopwords()

    for filler in ("right", "one", "first", "lets", "happened"):
        assert filler in survivors


def test_an_unknown_list_says_what_there_is():
    try:
        word_resources.load("nope.txt")
    except Exception as error:            # noqa: BLE001 - message is the test
        assert "omit_words.txt" in str(error)
    else:                                 # pragma: no cover
        raise AssertionError("an unknown word list should not load")
