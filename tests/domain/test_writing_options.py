"""The selectable registers and dials.

The load-bearing property of this whole module is that a run left alone
produces the packet that existed before any of it: every dial's default maps
to an empty string, so choosing nothing emits nothing.
"""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.domain.errors import ConfigurationError
from llm_youtube_comment_generation.domain.writing_options import (
    ApproachDimension,
    DEFAULT_REPLY_VARIATIONS,
    DEFAULT_VARIATIONS,
    DIALS,
    HUMOR_INCOMPATIBLE_REPLACEMENTS,
    REQUIRED_OUTPUT_HEADINGS,
    VARIATION_LIBRARY,
    analysis_waiver,
    default_dials,
    dial_choice_classification,
    DialChoiceClassification,
    default_output_options,
    dial_choice,
    format_dial_listing,
    format_register_listing,
    headings_for,
    instruction_cost,
    output_directives,
    parse_dials,
    parse_registers,
    reply_variation_specs,
    resolve_prompt_spec,
    variation_keys,
    variation_specs,
)
from llm_youtube_comment_generation.domain.packets import (
    DEFAULT_PACKET_CHARACTERS,
    INSTRUCTION_BUDGET_SHARE,
)


def test_the_five_comment_variations_are_registers():
    """They used to be prose in the template, so every run asked for the same five."""

    assert DEFAULT_VARIATIONS == (
        "short_hook", "flat_claim", "one_concrete_thing", "dry_joke",
        "full_argument",
    )
    for key in DEFAULT_VARIATIONS:
        assert key in VARIATION_LIBRARY


def test_the_reply_registers_keep_their_own_wording():
    """Three have no comment equivalent, and one is worded for a thread."""

    assert DEFAULT_REPLY_VARIATIONS == (
        "dry_one_liner", "flat_contradiction", "one_concrete_detail",
        "agree_and_add", "full_answer",
    )
    assert VARIATION_LIBRARY["one_concrete_detail"].heading == "One concrete thing"
    assert VARIATION_LIBRARY["one_concrete_thing"].heading == "One concrete thing"
    assert (VARIATION_LIBRARY["one_concrete_detail"].spec
            != VARIATION_LIBRARY["one_concrete_thing"].spec)


def test_two_registers_sharing_a_heading_are_kept_apart_when_both_are_asked_for():
    """Otherwise the packet names two sections identically.

    Check 2 reads that as two variations sharing a register, and validating
    the answer against a duplicated heading is ambiguous.
    """

    both = ["one_concrete_thing", "one_concrete_detail"]
    headings = headings_for(both)

    assert headings[0] == "### 1. One concrete thing (one_concrete_thing)"
    assert headings[1] == "### 2. One concrete thing (one_concrete_detail)"
    assert len(set(headings)) == len(headings)


def test_a_selection_without_the_clash_keeps_its_plain_headings():
    """The disambiguation must be invisible to every ordinary run."""

    assert headings_for()[2] == "### 3. One concrete thing"
    assert (headings_for(default=DEFAULT_REPLY_VARIATIONS)[2]
            == "### 3. One concrete thing")


def test_an_empty_or_unknown_selection_falls_back_to_the_original_five():
    """Never build a packet that asks for no variations at all."""

    assert variation_keys(None) == DEFAULT_VARIATIONS
    assert variation_keys(()) == DEFAULT_VARIATIONS
    assert variation_keys(("no_such_register",)) == DEFAULT_VARIATIONS


def test_an_empty_reply_selection_falls_back_to_the_reply_five():
    assert variation_keys(None, DEFAULT_REPLY_VARIATIONS) == DEFAULT_REPLY_VARIATIONS
    assert variation_keys((), DEFAULT_REPLY_VARIATIONS) == DEFAULT_REPLY_VARIATIONS


def test_choosing_three_registers_asks_for_three_not_five():
    chosen = ("short_hook", "dry_joke", "summary")

    headings = headings_for(chosen)

    assert len(headings) == 5                       # three plus the two fixed
    assert headings[-2:] == ("### Harsh critique", "### Hardened final")
    assert "### 1. Short hook" in headings
    assert "### 3. Summary" in headings


def test_selection_is_returned_in_library_order_not_argument_order():
    """Otherwise the same set produces two different packets."""

    assert variation_keys(("dry_joke", "short_hook")) == \
           variation_keys(("short_hook", "dry_joke"))


def test_a_repeated_register_is_asked_for_once():
    assert variation_keys(("short_hook", "short_hook")) == ("short_hook",)


def test_a_summary_register_is_exempt_from_the_analysis_test():
    """Applying it would fail the variation for doing its job."""

    waiver = analysis_waiver(variation_keys(("summary",)))

    assert "Summary" in waiver
    assert "does not apply" in waiver
    assert VARIATION_LIBRARY["summary"].waives_analysis is True


def test_the_analysis_waiver_is_absent_when_every_register_must_pass():
    """The default set spends no words saying nothing."""

    assert analysis_waiver(variation_keys(None)) == ""


def test_the_waiver_agrees_with_itself_about_number():
    one = analysis_waiver(variation_keys(("summary",)))
    two = analysis_waiver(variation_keys(("summary", "question")))

    assert "its value is" in one and "discard or downgrade it" in one
    assert "their value is" in two and "discard or downgrade them" in two


def test_a_register_can_be_named_by_its_heading_or_its_key():
    assert parse_registers("short_hook") == ("short_hook",)
    assert parse_registers("Short hook") == ("short_hook",)
    assert parse_registers("SHORT_HOOK") == ("short_hook",)
    assert parse_registers("short_hook, dry_joke") == ("short_hook", "dry_joke")


def test_a_misspelled_register_stops_the_run_before_it_spends_quota():
    """A typed argument is a request.

    Silently building a different packet than the one asked for is how a run
    gets trusted when it should not be. A stale settings file is tolerated;
    a command line is not.
    """

    with pytest.raises(ConfigurationError, match="Unknown register"):
        parse_registers("short_hok")

    with pytest.raises(ConfigurationError, match="--registers was given nothing"):
        parse_registers("")


def test_no_register_argument_leaves_the_defaults_alone():
    assert variation_specs(None) == variation_specs(DEFAULT_VARIATIONS)


# --------------------------------------------------------------------------
# Dials
# --------------------------------------------------------------------------


def test_untouched_dials_add_nothing_to_the_packet():
    """Byte for byte what it was before any of this existed."""

    assert output_directives(None) == ""
    assert output_directives({}) == ""
    assert output_directives(default_dials()) == ""


def test_a_changed_dial_states_itself_once():
    directives = output_directives({"person": "as_me"})

    assert "## Output options" in directives
    assert directives.count("Write in the first person") == 1


def test_the_humor_replacement_notice_stays_after_the_other_directives():
    """The comment workflow appends its humor=none line after the dial loop
    rather than emitting it in DIALS order, where humor sits before
    aggression. Emitting it in place reorders the block for every humor=none
    build, which silently rewrites text the model reads.

    This is the comment path, reached through ``resolve_prompt_spec``. The
    reply workflow's ``output_directives`` is a separate block with no
    replacement wording, and asserting this there proves nothing.
    """

    spec = resolve_prompt_spec(
        (),
        {"humor": "none", "person": "as_me", "aggression": "uncapped"},
    )
    lines = [
        line for line in spec.output_directives.splitlines()
        if line.startswith("- [")
    ]

    assert [line.split("]")[0] + "]" for line in lines] == [
        "- [person=as_me]",
        "- [aggression=uncapped]",
        "- [humor=none]",
    ]


def test_every_dial_choice_has_compliance_semantics():
    for name, dial in DIALS.items():
        for value in dial.choices:
            assert isinstance(
                dial_choice_classification(name, value),
                DialChoiceClassification,
            )


def test_permissive_choices_are_classified_as_permitted():
    assert dial_choice_classification(
        "humor", "sarcasm"
    ) is DialChoiceClassification.PERMITTED
    assert dial_choice_classification(
        "aggression", "uncapped"
    ) is DialChoiceClassification.PERMITTED


def test_an_unknown_dial_value_falls_back_rather_than_breaking_the_packet():
    """A stale settings entry must not stop the application opening."""

    assert dial_choice("person", {"person": "nonsense"}) == DIALS["person"].default
    assert output_directives({"person": "nonsense"}) == ""


def test_a_bad_dial_says_which_settings_exist():
    with pytest.raises(ConfigurationError, match="Unknown dial"):
        parse_dials(["nosuchdial=x"])

    with pytest.raises(ConfigurationError, match="has no setting called"):
        parse_dials(["person=nonsense"])

    with pytest.raises(ConfigurationError, match="wants name=value"):
        parse_dials(["person"])


def test_dials_parse_into_stored_values():
    assert parse_dials(["person=as_me", "hedging=none"]) == {
        "person": "as_me", "hedging": "none",
    }
    assert parse_dials([]) == {}


def test_every_dial_default_emits_nothing():
    """This is the property the reset guarantee rests on."""

    for name, entry in DIALS.items():
        assert entry.choices[entry.default] == "", name


def test_reset_reproduces_the_prompt_from_before_the_options_existed():
    """Reset has to be an explicit, testable value, not "clear it and hope"."""

    registers, dials = default_output_options()

    assert registers == DEFAULT_VARIATIONS
    assert dials == default_dials()
    assert output_directives(dials) == ""
    assert variation_specs(registers) == variation_specs(None)
    assert headings_for(registers) == REQUIRED_OUTPUT_HEADINGS


def test_the_listings_mark_the_defaults_and_the_waivers():
    """Without these the command line is unusable."""

    registers = format_register_listing()

    assert "short_hook" in registers
    assert "[default]" in registers or "default" in registers
    assert "waives the analysis test" in registers
    for key in VARIATION_LIBRARY:
        assert key in registers

    dials = format_dial_listing()

    assert "[default]" in dials
    for name in DIALS:
        assert name in dials


# --------------------------------------------------------------------------
# Cost
# --------------------------------------------------------------------------


def test_a_shorter_register_set_makes_the_prompt_shorter():
    assert len(variation_specs(("short_hook",))) < len(variation_specs(None))


def test_the_named_approaches_survive_a_single_narrow_length_band():
    """Modes can change function or stance, not merely surface register."""

    specs = variation_specs(("short_hook", "flat_claim"))

    assert "do not force different dimensions to share one conclusion" in specs
    assert "still sit inside it" in specs
    assert "same selected angle" not in specs
    assert "differ by register alone" not in specs


def test_critique_and_final_reject_unsupported_repeated_analysis():
    spec = resolve_prompt_spec()

    assert "unstated premise about motive, control" in spec.critique_contract
    assert "silently convert it into fact" in spec.critique_contract
    assert "call the later one a duplicate" in spec.critique_contract
    assert "Redundancy test:" in spec.final_contract
    assert "inside the preferred band" in spec.final_contract


def test_reply_specs_use_the_same_dimension_semantics_as_comments():
    specs = reply_variation_specs(None)

    assert specs.startswith("Then output exactly these five variation sections")
    assert "Do not force different dimensions to answer with the same point" \
        in specs
    assert "differ by REGISTER" not in specs


def test_a_reply_can_be_asked_for_a_different_register_set():
    chosen = ("hostile", "agreeable", "summary")

    rendered = reply_variation_specs(chosen)

    assert "Then output exactly these three variation sections" in rendered
    assert "The three follow the current user direction" in rendered
    assert "### 1. Agreeable" in rendered
    assert "### 3. Summary" in rendered
    assert "Dry one-liner" not in rendered
    # The waiver travels with the library, not with the pipeline.
    assert "The analysis test does not apply to Summary." in rendered
    assert headings_for(chosen, DEFAULT_REPLY_VARIATIONS)[-2:] == (
        "### Harsh critique",
        "### Hardened final",
    )


def test_mixed_approaches_are_classified_by_the_axis_they_change():
    expected = {
        "devils_advocate": ApproachDimension.STANCE,
        "historical_parallel": ApproachDimension.EVIDENCE,
        "prediction": ApproachDimension.TEMPORAL,
        "summary": ApproachDimension.FUNCTION,
        "meta": ApproachDimension.SUBJECT,
        "sardonic": ApproachDimension.TONE,
    }

    for key, dimension in expected.items():
        assert VARIATION_LIBRARY[key].dimension is dimension


def test_every_humor_required_approach_has_a_nonhumorous_replacement():
    classified = {
        key for key, entry in VARIATION_LIBRARY.items()
        if entry.requires_humor
    }

    assert classified == set(HUMOR_INCOMPATIBLE_REPLACEMENTS)
    for replacement in HUMOR_INCOMPATIBLE_REPLACEMENTS.values():
        assert not VARIATION_LIBRARY[replacement].requires_humor


def test_the_whole_library_is_nowhere_near_the_instruction_budget():
    """Recorded as real headroom rather than asserted as a vague comfort.

    Selecting every register at once is not a sensible run, but it is the
    worst case the guard has to survive, and it costs about half the ceiling.
    """

    ceiling = int(DEFAULT_PACKET_CHARACTERS * INSTRUCTION_BUDGET_SHARE)
    worst_case = instruction_cost(tuple(VARIATION_LIBRARY), {
        name: [v for v in entry.choices if v != entry.default][0]
        for name, entry in DIALS.items()
    })

    assert worst_case < ceiling, (
        f"the whole library costs {worst_case:,} against a {ceiling:,} ceiling"
    )
    # Headroom recorded so a future change that halves it is visible in a diff.
    assert worst_case < ceiling * 0.75


def test_the_default_set_costs_a_fraction_of_the_budget():
    ceiling = int(DEFAULT_PACKET_CHARACTERS * INSTRUCTION_BUDGET_SHARE)

    assert instruction_cost(None, None) < ceiling * 0.2
