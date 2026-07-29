"""The final check is rendered from the resolved option state."""

from __future__ import annotations

from llm_youtube_comment_generation.domain.writing_options import (
    render_final_check,
)
from llm_youtube_comment_generation.infrastructure import prompt_resources

TEMPLATE = prompt_resources.load("comment_final_check.md").text


def rendered(dials):
    return render_final_check(TEMPLATE, None, selections=dials)


def test_the_default_check_describes_the_default_contract():
    text = rendered({})

    assert "then Harsh critique, then Hardened final" in text
    assert "one assembled comment" in text
    assert "amend the checks" not in text


def test_no_critique_is_a_direct_check_not_a_late_amendment():
    text = rendered({"critique": "none"})

    assert "Harsh critique" not in text
    assert "ranked silently" in text
    assert "amend the checks" not in text


def test_best_single_is_checked_as_a_non_hybrid_winner():
    text = rendered({"final": "best_single"})

    assert "one repaired winning variation" in text
    assert "no material from other drafts" in text
    assert "assembled from the drafts" not in text


def test_both_finals_have_distinct_checked_semantics_and_terminal_order():
    text = rendered({"final": "both"})

    assert "Assembled followed by Single best" in text
    assert "Assembled may combine drafts" in text
    assert "Single best is a repaired non-hybrid winner" in text
    assert "last content" in text


def test_required_and_forbidden_option_semantics_are_objective():
    text = rendered({
        "person": "as_me",
        "hedging": "none",
        "grounding": "summary",
        "humor": "none",
        "ending": "flat",
        "aggression": "never",
    })

    assert "Required — person=as_me" in text
    assert "Forbidden — hedging=none" in text
    assert "Required — grounding" in text
    assert "Required — flat ending" in text
    assert "Forbidden — humor" in text
    assert "Forbidden — aggression=never" in text


def test_impersonal_is_an_objective_forbidden_check():
    text = rendered({"person": "impersonal"})

    assert "Forbidden — person=impersonal" in text
    assert "no finished comment uses first person or direct address" in text


def test_permitted_behavior_does_not_become_a_compliance_check():
    text = rendered({
        "humor": "sarcasm",
        "aggression": "uncapped",
    })

    assert "Required — humor=sarcasm" not in text
    assert "Forbidden — humor=sarcasm" not in text
    assert "Required — aggression=uncapped" not in text
    assert "Forbidden — aggression=uncapped" not in text
