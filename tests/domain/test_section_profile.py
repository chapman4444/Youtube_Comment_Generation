"""Measuring a comment section, and writing the length rule from it."""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.domain.errors import ConfigurationError
from llm_youtube_comment_generation.domain.section_profile import (
    CommentRegister,
    DEFAULT_LENGTH_RULE,
    keyword_counts,
    length_rule_for,
    measure_comment_register,
    parse_length,
    percentile,
    tokenize,
)


def body(words: int, text: str = "word") -> str:
    return " ".join([text] * words)


def test_percentile_is_stable_on_small_samples():
    """Nearest-rank. Interpolation on a sample of four is false precision."""

    assert percentile([], 0.5) == 0
    assert percentile([7], 0.5) == 7
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert percentile([1, 2, 3, 4, 5], 0.9) == 5
    assert percentile([5, 3, 1], 0.5) == 3          # sorts first


def test_keyword_counts_exclude_stop_words():
    counts = keyword_counts("the economy and the economy and the market")
    terms = {entry["term"]: entry["count"] for entry in counts}

    assert terms["economy"] == 2
    assert "the" not in terms
    assert "and" not in terms


def test_tokenizing_drops_short_tokens_and_digits():
    assert tokenize("a bb ccc dddd 1234") == ["ccc", "dddd"]
    assert "don't" in tokenize("don't stop")


def test_register_measures_length_distribution(comment):
    sample = [comment(f"c{i}", text=body(i + 1)) for i in range(20)]

    register = measure_comment_register(sample)

    assert register.sample_size == 20
    # Nearest rank over 1..20 words: index round(f * 19) into the sorted list.
    assert register.median_words == 11
    assert register.p75_words == 15
    assert register.p90_words == 18
    assert register.median_words <= register.p75_words <= register.p90_words


def test_register_reports_what_actually_gets_liked(comment):
    """The most-liked figure matters most: it is what earns a response here."""

    # The top-liked figure is the median of the 25 most-liked comments, so the
    # liked group has to fill that window for the measurement to mean anything.
    sample = [comment(f"long{i}", text=body(60), likes=0) for i in range(40)]
    sample += [comment(f"short{i}", text=body(9), likes=500) for i in range(25)]

    register = measure_comment_register(sample)

    assert register.top_liked_median_words == 9
    assert register.top_liked_median_words < register.median_words


def test_register_reports_the_short_comment_share(comment):
    sample = [comment(f"s{i}", text=body(5)) for i in range(3)]
    sample += [comment(f"l{i}", text=body(50)) for i in range(1)]

    register = measure_comment_register(sample)

    assert register.under_10_words == 0.75
    assert register.under_40_words == 0.75


def test_register_detects_style_markers(comment):
    sample = [
        comment("c1", text="no closing punctuation"),
        comment("c2", text="Ends properly."),
        comment("c3", text="Two\n\nparagraphs here."),
        comment("c4", text="Is this a question?"),
        comment("c5", text="An em — dash."),
        comment("c6", text="A semicolon; here."),
    ]

    register = measure_comment_register(sample)

    assert register.no_terminal_punctuation == pytest.approx(1 / 6)
    assert register.multi_paragraph == pytest.approx(1 / 6)
    assert register.ends_with_question == pytest.approx(1 / 6)
    assert register.em_dash == pytest.approx(1 / 6)
    assert register.semicolon == pytest.approx(1 / 6)


def test_register_detects_direct_address(comment):
    sample = [
        comment("c1", text="you are wrong about this"),
        comment("c2", text="Your argument fails."),
        comment("c3", text="The claim fails on its own terms."),
    ]

    assert measure_comment_register(sample).direct_address == pytest.approx(2 / 3)


def test_register_survives_an_empty_sample():
    register = measure_comment_register([], [])

    assert register.sample_size == 0
    assert register.median_words == 0


def test_blank_comments_are_not_counted(comment):
    sample = [comment("c1", text="real"), comment("c2", text="   ")]

    assert measure_comment_register(sample).sample_size == 1


def test_replies_join_the_sample(comment):
    sample = [comment("c1", text=body(10))]
    replies = [comment("r1", text=body(10))]

    assert measure_comment_register(sample, replies).sample_size == 2


# --------------------------------------------------------------------------
# Length
# --------------------------------------------------------------------------


def test_length_settings_parse():
    assert parse_length("auto") is None
    assert parse_length("") is None
    assert parse_length("match") is None
    assert parse_length("short") == (5, 20)
    assert parse_length("medium") == (20, 50)
    assert parse_length("long") == (50, 100)
    assert parse_length("20-60") == (20, 60)
    assert parse_length("45") == (15, 45)


def test_length_rule_bands_are_always_ordered():
    """A reversed range is a typo, not a request for an empty band."""

    assert parse_length("60-20") == (20, 60)
    low, high = parse_length("60-20")
    assert low < high


def test_bad_length_is_rejected():
    with pytest.raises(ConfigurationError, match="Unrecognised length"):
        parse_length("quite short please")


def test_length_rule_falls_back_when_nothing_was_measured():
    assert length_rule_for(None) == DEFAULT_LENGTH_RULE
    assert length_rule_for(CommentRegister()) == DEFAULT_LENGTH_RULE


def test_length_rule_is_written_from_the_measured_section():
    """The hardcoded 80-140 band was about six times too long everywhere.

    On the measured video the section median was 14 words and the most-liked
    comments ran 9, while every generated variation landed between 85 and 119
    because the prompt said so.
    """

    register = CommentRegister(
        sample_size=300, median_words=14, p75_words=25, p90_words=40,
        top_liked_median_words=9,
    )

    rule = length_rule_for(register)

    assert "9 words" in rule
    assert "14 words" in rule
    assert "80-140" not in rule
    assert "do not pad" in rule


def test_an_explicit_band_still_warns_about_padding():
    """Setting a length must not discard the finding that most affects reach."""

    rule = length_rule_for(None, explicit=(20, 60))

    assert "20-60 words" in rule
    assert "Never exceed 78 words" in rule
    assert "do not pad" in rule


def test_an_explicit_band_still_reports_the_measured_section():
    register = CommentRegister(sample_size=300, median_words=14,
                               top_liked_median_words=9)

    rule = length_rule_for(register, explicit=(20, 60))

    assert "14 words at the median" in rule
    assert "9 for its most-liked" in rule


def test_the_measured_band_never_collapses():
    """A section of one-word comments must still leave room to make a point."""

    register = CommentRegister(sample_size=50, median_words=1, p90_words=2,
                               top_liked_median_words=1)

    rule = length_rule_for(register)

    assert "about 6 words" in rule           # floored, not 1
    assert "past 26" in rule                 # short + 20
