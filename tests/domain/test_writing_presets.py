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


def test_built_in_presets_have_unique_valid_names():
    assert len(BUILT_IN_PRESETS) >= 11
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
