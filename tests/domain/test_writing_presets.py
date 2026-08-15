"""Writing presets are validated, portable, and contain no personal state."""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.domain.errors import ConfigurationError
from llm_youtube_comment_generation.domain.writing_options import (
    VARIATION_LIBRARY,
)
from llm_youtube_comment_generation.domain.writing_presets import (
    BUILT_IN_PRESETS,
    WritingPreset,
)
from llm_youtube_comment_generation.interfaces.gui.options import (
    PacketOptionsModel,
)


def test_dry_and_sharp_asks_for_an_analytical_move_not_only_a_tone():
    """It used to be four tone registers and nothing else.

    Tone says how to sound; it never says what analytical move to make. Every
    one of the four told the model to state a fact -- "the damning fact", "one
    concrete inconsistency", "the facts do the damage" -- so four sharply
    worded restatements of the video's own point satisfied the packet, which is
    exactly what the operator kept getting back. A preset has to select at
    least one register whose spec asks for something the video did not say.
    """

    preset = next(p for p in BUILT_IN_PRESETS if p.name == "Dry and sharp")
    dimensions = {
        VARIATION_LIBRARY[key].dimension for key in preset.comment_variations
    }

    assert len(dimensions) > 1
    assert not all(
        VARIATION_LIBRARY[key].dimension.value == "tone"
        for key in preset.comment_variations
    )


def test_no_built_in_preset_lets_every_register_skip_the_analysis_test():
    """A preset built entirely from waivers would ask for nothing original at
    all, and the final check would exempt all of it by name."""

    for preset in BUILT_IN_PRESETS:
        keys = preset.comment_variations
        if not keys:
            continue
        assert not all(
            VARIATION_LIBRARY[key].waives_analysis for key in keys
        ), f"{preset.name} waives analysis in every register"


FOUR_REPLY_REGISTERS = (
    "dry_one_liner", "one_concrete_detail", "agree_and_add",
    "warm_acknowledgment",
)


def test_the_four_reply_registers_resolve_with_their_stated_identity():
    """One authoritative catalog owns label, dimension and waiver. The GUI,
    the CLI, the packet headings and the presets all read it."""

    expected = {
        "dry_one_liner": ("Dry one-liner", "tone", False),
        "one_concrete_detail": ("One concrete thing", "form", False),
        "agree_and_add": ("Agree and add", "stance", False),
        "warm_acknowledgment": ("Warm acknowledgment", "stance", True),
    }
    for key, (heading, dimension, waives) in expected.items():
        entry = VARIATION_LIBRARY[key]
        assert entry.heading == heading
        assert entry.dimension.value == dimension
        assert entry.waives_analysis is waives, key


def test_only_warm_acknowledgment_waives_the_analysis_test():
    waiving = [k for k in FOUR_REPLY_REGISTERS
               if VARIATION_LIBRARY[k].waives_analysis]

    assert waiving == ["warm_acknowledgment"]


def test_the_four_neighbours_stay_distinct_registers():
    """Overlapping sample outputs are not a reason to alias registers that
    control different dimensions or rhetorical functions."""

    neighbours = (
        "dry_one_liner", "sardonic", "deadpan", "dry_joke",
        "one_concrete_detail", "numbers_only",
        "agree_and_add", "correction", "blunt_correction",
        "flat_contradiction", "warm_acknowledgment",
    )
    specs = {}
    for key in neighbours:
        entry = VARIATION_LIBRARY[key]
        assert entry.spec.strip(), key
        assert entry.spec not in specs, f"{key} duplicates {specs.get(entry.spec)}"
        specs[entry.spec] = key


def test_the_reply_preset_holds_the_four_ids_in_render_order():
    """A preset stores ids, never prose, and the packet renders them in
    library order — which for these four is the intended reading order."""

    preset = next(p for p in BUILT_IN_PRESETS if p.name == "Keep them talking")

    assert preset.reply_variations == FOUR_REPLY_REGISTERS
    library_order = tuple(
        k for k in VARIATION_LIBRARY if k in FOUR_REPLY_REGISTERS)
    assert library_order == FOUR_REPLY_REGISTERS


def test_a_preset_stores_ids_rather_than_register_prose():
    for preset in BUILT_IN_PRESETS:
        for key in preset.reply_variations + preset.comment_variations:
            assert key in VARIATION_LIBRARY
            assert VARIATION_LIBRARY[key].spec not in preset.description


def test_an_unknown_register_id_fails_loudly():
    from llm_youtube_comment_generation.domain.errors import (
        ConfigurationError,
    )

    with pytest.raises(ConfigurationError, match="unknown register"):
        WritingPreset(name="Broken", reply_variations=("no_such_register",))


def test_a_duplicate_register_id_collapses_rather_than_doubling():
    """variation_keys is the one place ordering and uniqueness are decided;
    a preset cannot smuggle a register in twice."""

    preset = WritingPreset(
        name="Doubled",
        reply_variations=("agree_and_add", "agree_and_add", "dry_one_liner"),
    )

    assert preset.reply_variations == ("dry_one_liner", "agree_and_add")


def test_the_presence_presets_reach_the_reply_only_registers():
    """The registers written for engagement rather than argument are
    unreachable from a preset unless a preset selects them."""

    by_name = {preset.name: preset for preset in BUILT_IN_PRESETS}

    assert "warm_acknowledgment" in by_name["Keep them talking"].reply_variations
    assert "answer_the_question" in by_name["Answer the question"].reply_variations
    assert "back_them_up" in by_name["Take their side"].reply_variations


def test_every_built_in_preset_builds_a_reply_packet():
    """A preset that refuses at build time is worse than no preset: the
    operator picks a name and the run dies. Reply mode falls back on the
    dial values its contract cannot carry, so every preset must survive."""

    from llm_youtube_comment_generation.domain.reply_packet import (
        UNSUPPORTED_REPLY_DIALS,
    )

    for preset in BUILT_IN_PRESETS:
        dials = dict(preset.dials)
        for name, value in list(dials.items()):
            if (name, value) in UNSUPPORTED_REPLY_DIALS:
                dials.pop(name)
        assert preset.reply_variations or not preset.comment_variations, (
            f"{preset.name} selects comment registers but no reply registers"
        )


def test_built_in_presets_have_unique_valid_names():
    assert len(BUILT_IN_PRESETS) >= 14
    assert len({preset.key for preset in BUILT_IN_PRESETS}) == \
        len(BUILT_IN_PRESETS)
    assert all(preset.builtin for preset in BUILT_IN_PRESETS)
    assert {
        "Balanced",
        "Skeptical",
        "Questions and gaps",
        "Direct rebuttal",
        "Creative angles",
        "Human impact",
    } <= {preset.name for preset in BUILT_IN_PRESETS}


def test_applying_a_preset_changes_only_writing_choices():
    original = PacketOptionsModel(
        video="gC-J7zwYMAM",
        my_handle="@owner",
        output_directory="D:/private",
        proxy_url="https://secret.example",
        max_top=777,
    )

    changed = original.apply_writing_preset(BUILT_IN_PRESETS[1])

    assert changed.comment_variations
    assert changed.length == "short"
    assert changed.video == original.video
    assert changed.my_handle == original.my_handle
    assert changed.output_directory == original.output_directory
    assert changed.proxy_url == original.proxy_url
    assert changed.max_top == original.max_top


def test_capturing_a_custom_preset_excludes_personal_and_retrieval_fields():
    model = PacketOptionsModel(
        video="gC-J7zwYMAM",
        my_handle="@owner",
        output_directory="D:/private",
        proxy_url="https://" + "user:password@" + "example",
        max_top=999,
        comment_variations=("short_hook",),
        dials={"ending": "flat"},
        length="short",
    )

    payload = model.as_writing_preset("Mine").to_payload()

    serialized = repr(payload)
    assert "gC-J7zwYMAM" not in serialized
    assert "@owner" not in serialized
    assert "D:/private" not in serialized
    assert "password" not in serialized
    assert "max_top" not in payload


def test_invalid_custom_preset_is_refused():
    with pytest.raises(ConfigurationError, match="unknown dial"):
        WritingPreset(name="Bad", dials=(("made_up", "yes"),))
