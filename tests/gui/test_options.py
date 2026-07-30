"""Every option the window offers, checked without a window.

Taken from the old application's GUI, which is the only place these choices
have ever been written down. The rebuilt window had none of them — no
register, no dial, no length, no comment count could be set from it.

Nothing here creates a Tk interpreter. These are the rules that decide what
gets built, which is the part worth being certain about, and interpreter
creation is flaky on this machine.
"""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.domain.packets import (
    MINIMUM_PACKET_CHARACTERS,
)
from llm_youtube_comment_generation.domain.writing_options import (
    DEFAULT_REPLY_VARIATIONS,
    DEFAULT_VARIATIONS,
    DIALS,
)
from llm_youtube_comment_generation.interfaces.gui.options import (
    DEFAULT_DIAL_BEHAVIOR,
    LENGTH_CHOICES,
    LENGTH_HINTS,
    PacketOptionsModel,
    approach_choices,
    dial_help,
    register_choices,
)
from llm_youtube_comment_generation.domain.writing_presets import (
    BUILT_IN_PRESETS,
)


def model(**kwargs) -> PacketOptionsModel:
    return PacketOptionsModel(video="gC-J7zwYMAM", **kwargs)


# -- registers -------------------------------------------------------------


def test_choosing_nothing_means_the_defaults_not_nothing():
    """The old picker says so in its own label. A window that read an empty
    listbox as an empty answer would build a packet asking for no sections."""

    assert model().registers_for("comment") == tuple(DEFAULT_VARIATIONS)
    assert model().registers_for("reply") == tuple(DEFAULT_REPLY_VARIATIONS)


def test_selection_uses_custom_values_and_an_empty_selection_uses_defaults():
    chosen = model(
        comment_approach_mode="custom",
        comment_variations=("meta", "devils_advocate"),
    )

    assert chosen.registers_for("comment") == ("devils_advocate", "meta")
    assert model(
        comment_approach_mode="custom"
    ).registers_for("comment") == tuple(DEFAULT_VARIATIONS)


def test_the_two_modes_keep_separate_register_lists():
    """A comment and a reply are not answering the same thing."""

    chosen = model(
        comment_variations=("short_hook",),
        reply_variations=("dry_one_liner",),
        comment_approach_mode="custom",
        reply_approach_mode="custom",
    )

    assert chosen.registers_for("comment") == ("short_hook",)
    assert chosen.registers_for("reply") == ("dry_one_liner",)


def test_a_register_that_no_longer_exists_is_a_problem_not_a_crash():
    assert any("no comment register" in problem
               for problem in model(comment_variations=("gone",)).problems())


def test_the_two_registers_sharing_a_heading_are_told_apart():
    """Two entries are both "One concrete thing": one worded for a comment
    section, one for a thread. Both are the operator's prose and neither may
    be reworded, so the list disambiguates instead."""

    labels = [label for _key, label in register_choices("comment")]
    concrete = [label for label in labels if label.startswith("One concrete")]

    assert len(concrete) > 1
    assert all("wording)" in label for label in concrete)


def test_every_register_is_offered():
    """A picker that silently omits one is a register the operator can never
    choose again."""

    from llm_youtube_comment_generation.domain.writing_options import (
        VARIATION_LIBRARY,
    )

    assert len(register_choices("comment")) == len(VARIATION_LIBRARY)


# -- dials -----------------------------------------------------------------


def test_every_dial_is_reported_including_the_untouched_ones():
    """"Absent" and "at its default" are indistinguishable in a run record
    afterwards, so the record names them all."""

    values = model().dial_values()

    assert set(values) == set(DIALS)
    assert all(value for value in values.values())


def test_a_dial_set_to_something_it_does_not_offer_is_refused():
    problems = model(dials={"grounding": "banana"}).problems()

    assert any("cannot be 'banana'" in problem for problem in problems)
    assert any("summary" in problem for problem in problems)


def test_an_invented_dial_is_refused():
    assert any("no dial called" in problem
               for problem in model(dials={"nonsense": "x"}).problems())


# -- length ----------------------------------------------------------------


def test_a_typed_number_beats_the_radio_buttons():
    """The old field is labelled "or words:", so a typed number always wins
    rather than there being a fifth radio."""

    chosen = model(length="exact", custom_length="120")

    assert chosen.explicit_length() == (96, 150)
    assert "120" not in chosen.length_hint()
    assert "96 to 150 words" in chosen.length_hint()


def test_one_number_is_a_target_not_a_ceiling():
    low, high = model(length="exact", custom_length="100").explicit_length()

    assert low < 100 < high


def test_a_non_numeric_target_is_not_silently_interpreted():
    assert model(length="exact", custom_length="140-80").explicit_length() is None


def test_no_number_leaves_the_radio_in_charge():
    chosen = model(length="medium", custom_length="  ")

    assert chosen.explicit_length() is None
    assert chosen.length_hint()


def test_nonsense_in_the_box_does_not_become_a_length():
    assert model(length="exact", custom_length="lots").explicit_length() is None
    assert any(
        "whole number" in problem
        for problem in model(
            length="exact", custom_length="lots"
        ).problems()
    )


def test_every_length_choice_has_a_hint():
    for value, _label in LENGTH_CHOICES:
        assert model(length=value).length_hint()


def test_switching_away_from_exact_clears_its_validation_blocker():
    assert any(
        "target word" in problem.lower()
        for problem in model(length="exact", custom_length="").problems()
    )
    assert not any(
        "target word" in problem.lower()
        for problem in model(length="short", custom_length="").problems()
    )


def test_length_descriptions_explain_targets_not_exact_promises():
    assert set(LENGTH_HINTS) == dict(LENGTH_CHOICES).keys()
    assert "target" in LENGTH_HINTS["auto"].lower()
    assert "not a hard" in LENGTH_HINTS["auto"].lower()


# -- languages -------------------------------------------------------------


def test_languages_are_split_on_commas():
    assert model(languages="en, de ,fr").transcript_languages == (
        "en", "de", "fr")


def test_an_empty_language_field_does_not_become_an_empty_language():
    """A code of "" matches no caption track, so it would turn "I did not set
    this" into "no transcript is acceptable"."""

    assert model(languages="").transcript_languages == ("en",)
    assert model(languages="  ,  ").transcript_languages == ("en",)


# -- validation ------------------------------------------------------------


def test_a_missing_video_is_reported():
    assert any("no video" in p.lower()
               for p in PacketOptionsModel().problems())


def test_reply_mode_needs_a_handle_and_comment_mode_does_not():
    without = model()

    assert without.problems(mode="comment") == []
    assert any("@username" in p for p in without.problems(mode="reply"))


def test_a_budget_below_the_smallest_usable_packet_is_reported():
    problems = model(packet_characters=1_000).problems()

    assert any(f"{MINIMUM_PACKET_CHARACTERS:,}" in p for p in problems)


def test_every_problem_is_reported_at_once():
    """A form that reports the first mistake, is corrected, then reports the
    second takes four attempts to fill in."""

    problems = PacketOptionsModel(
        packet_characters=10, dials={"grounding": "no"}, length="enormous",
    ).problems(mode="reply")

    assert len(problems) >= 4


# -- persistence -----------------------------------------------------------


def test_settings_survive_a_round_trip():
    original = model(
        my_handle="@someone", languages="en,de", packet_characters=300_000,
        comment_variations=("short_hook", "dry_joke"),
        comment_approach_mode="custom",
        dials={"grounding": "summary"}, auto_watch=True, top_repliers=5,
    )

    restored = PacketOptionsModel.from_settings(original.to_settings())

    assert restored.to_settings() == original.to_settings()


def test_the_field_names_are_the_old_applications():
    """The settings file is his, written by the old application and read by
    it afterwards, so the names are its names and not tidier ones."""

    payload = model().to_settings()

    for name in (
        "my_handle", "max_top", "max_recent", "use_triage",
        "custom_length", "auto_watch", "editor_path",
        "transcribe_locally", "whisper_policy", "whisper_model",
    ):
        assert name in payload


def test_old_checked_whisper_setting_migrates_to_automatic():
    restored = PacketOptionsModel.from_settings({
        "transcribe_locally": True,
    })

    assert restored.whisper_policy == "automatic"


def test_old_unchecked_whisper_setting_migrates_to_ask():
    restored = PacketOptionsModel.from_settings({
        "transcribe_locally": False,
    })

    assert restored.whisper_policy == "ask"


def test_manual_transcript_route_is_a_one_run_choice():
    options = PacketOptionsModel(transcript_route="whisper")

    assert "transcript_route" not in options.to_settings()
    assert PacketOptionsModel.from_settings(
        options.to_settings()
    ).transcript_route == "automatic"


def test_a_malformed_settings_file_does_not_stop_the_window_opening():
    """The worst outcome of a bad settings file should be one field not
    being remembered."""

    restored = PacketOptionsModel.from_settings({
        "packet_characters": "not a number",
        "max_top": None,
        "dials": "not a mapping",
        "comment_variations": "not a list",
        "unknown_field_from_the_future": 1,
    })

    assert restored.packet_characters == PacketOptionsModel().packet_characters
    assert restored.dials == {}
    assert restored.comment_variations == ()


def test_a_register_removed_from_the_library_is_dropped_on_load():
    restored = PacketOptionsModel.from_settings(
        {"comment_variations": ["short_hook", "deleted_last_year"]}
    )

    assert restored.comment_variations == ("short_hook",)


def test_no_settings_at_all_is_the_defaults():
    assert PacketOptionsModel.from_settings(None).to_settings() == \
        PacketOptionsModel().to_settings()


# -- reset -----------------------------------------------------------------


def test_reset_clears_the_writing_options_and_nothing_else():
    """Somebody reaching for "reset the writing options" has not asked to
    retype the address."""

    before = model(
        comment_variations=("short_hook",), dials={"grounding": "summary"},
        comment_approach_mode="custom",
        output_directory="D:/out", my_handle="@someone",
    )

    after = before.reset_output_options()

    assert after.comment_variations == ()
    assert after.comment_approach_mode == "default"
    assert after.dials == {}
    assert after.output_directory == "D:/out"
    assert after.my_handle == "@someone"
    assert after.video == before.video


def test_preset_round_trip_preserves_writing_choices_only():
    before = model(
        comment_variations=("short_hook",),
        reply_variations=("flat_contradiction",),
        dials={"ending": "flat"},
        length="long",
        output_directory="D:/personal",
    )

    captured = before.as_writing_preset("My preset")
    restored = PacketOptionsModel(
        video=before.video,
        output_directory=before.output_directory,
    ).apply_writing_preset(captured)

    assert restored.comment_variations == before.comment_variations
    assert restored.reply_variations == before.reply_variations
    assert restored.dials == before.dials
    assert restored.length == before.length
    assert restored.output_directory == "D:/personal"


def test_builtin_default_preset_really_resets_writing_choices():
    changed = model(
        comment_variations=("short_hook",),
        dials={"ending": "flat"},
        length="long",
    )

    reset = changed.apply_writing_preset(BUILT_IN_PRESETS[0])

    assert reset.comment_variations == ()
    assert reset.reply_variations == ()
    assert reset.dials == {}
    assert reset.length == "auto"


def test_approach_help_comes_from_authoritative_backend_metadata():
    choices = {
        key: (dimension, description)
        for key, _label, dimension, description in approach_choices("comment")
    }

    assert choices["devils_advocate"][0] == "stance"
    assert choices["devils_advocate"][1]
    assert all(
        dimension and description
        for dimension, description in choices.values()
    )


def test_dial_help_is_concise_and_does_not_repeat_ui_metadata():
    text = dial_help("ending", "flat")

    assert "End on the claim itself" in text
    assert "How it ends:" not in text
    assert "Behavior:" not in text
    assert "\n\n" not in text


def test_every_default_dial_help_describes_actual_behavior():
    assert set(DEFAULT_DIAL_BEHAVIOR) == set(DIALS)
    for name, dial in DIALS.items():
        text = dial_help(name, dial.default)
        assert "resolved template default" not in text.lower()
        assert "resolver" not in text.lower()
        assert len(text) >= 30
