"""The grounding pass is reusable and occupies one resolved output position."""

from __future__ import annotations

from llm_youtube_comment_generation.domain.writing_options import (
    default_dials,
    resolve_prompt_spec,
)

ON = {"grounding": "summary"}


def test_it_is_off_unless_asked_for():
    assert default_dials()["grounding"] == "off"
    assert resolve_prompt_spec().grounding_contract == ""


def test_it_asks_for_description_rather_than_argument():
    text = resolve_prompt_spec(selections=ON).grounding_contract

    assert "only what the video states" in text
    assert "Do not put interpretation, argument, or comment drafts" in text


def test_transcript_people_get_real_earliest_timestamps_only():
    text = resolve_prompt_spec(selections=ON).grounding_contract

    assert "every person named in the transcript" in text
    assert "their earliest transcript timestamp" in text
    assert "People named only in comments, replies, metadata, or the" in text
    assert "may be listed without a timestamp; do not invent one" in text


def test_fixture_specific_observations_are_not_prompt_semantics():
    text = resolve_prompt_spec(selections=ON).grounding_contract

    assert "cold open before the video's own introduction" not in text
    assert "never says who took over" not in text
    assert "Speaker changes are not attribution by themselves" in text


def test_the_resolved_headings_put_grounding_before_variation_one():
    headings = resolve_prompt_spec(selections=ON).headings

    assert headings[0] == "### What the video says"
    assert headings[1] == "### 1. Short hook"


def test_a_draft_that_outruns_the_summary_is_fixed_not_the_summary():
    assert "fix the draft rather than the section" in (
        resolve_prompt_spec(selections=ON).grounding_contract
    )
