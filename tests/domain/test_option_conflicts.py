"""Incompatible options resolve before any prompt text is rendered."""

from __future__ import annotations

from llm_youtube_comment_generation.domain.writing_options import (
    HUMOR_INCOMPATIBLE_REPLACEMENTS,
    resolve_prompt_spec,
)


def test_flat_ending_replaces_the_question_register():
    spec = resolve_prompt_spec(
        ("question", "short_hook"), {"ending": "flat"}
    )

    assert spec.variation_keys == ("short_hook", "unanswered_gap")
    assert "### 2. Unanswered gap" in spec.headings
    assert "ask it as the closing sentence" not in spec.final_contract
    assert "Do not append a" in spec.ending_contract
    assert "rhetorical question" in spec.ending_contract


def test_no_humor_replaces_the_dry_joke_register():
    spec = resolve_prompt_spec(
        ("short_hook", "dry_joke"), {"humor": "none"}
    )

    assert spec.variation_keys == ("short_hook", "dry_observation")
    assert "### 2. Dry observation" in spec.headings
    assert "Dry joke" not in " ".join(spec.headings)
    assert "Any humorous register has already been replaced" in (
        spec.output_directives
    )


def test_substitution_deduplicates_an_explicit_replacement():
    spec = resolve_prompt_spec(
        ("dry_joke", "dry_observation"), {"humor": "none"}
    )

    assert spec.variation_keys == ("dry_observation",)


def test_no_humor_resolves_every_classified_humorous_approach():
    spec = resolve_prompt_spec(
        tuple(HUMOR_INCOMPATIBLE_REPLACEMENTS), {"humor": "none"}
    )

    assert spec.variation_keys == ("dry_observation",)
    assert all(
        key not in spec.variation_keys
        for key in HUMOR_INCOMPATIBLE_REPLACEMENTS
    )


def test_no_critique_and_best_single_compose_without_hidden_dependencies():
    spec = resolve_prompt_spec(
        selections={"critique": "none", "final": "best_single"}
    )
    rendered = "\n".join((spec.critique_contract, spec.final_contract))

    assert spec.critique_contract == ""
    assert "Judge and rank the variations silently" in rendered
    assert "under its critique" not in rendered
    assert "the critique just quoted" not in rendered
    assert "Build a sixth text" not in rendered


def test_every_supported_dial_resolves_together():
    spec = resolve_prompt_spec(selections={
        "person": "impersonal",
        "hedging": "none",
        "ending": "flat",
        "humor": "none",
        "critique": "none",
        "final": "both",
        "grounding": "summary",
        "aggression": "never",
    })

    assert spec.headings[0] == "### What the video says"
    assert "### Harsh critique" not in spec.headings
    assert spec.headings[-1] == "### Hardened finals"
    assert "dry_observation" in spec.variation_keys
