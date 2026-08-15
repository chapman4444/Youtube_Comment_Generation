"""Custom preset persistence is atomic, recoverable, and bounded."""

from __future__ import annotations

import json

import pytest

from llm_youtube_comment_generation.domain.errors import ConfigurationError
from llm_youtube_comment_generation.domain.writing_presets import WritingPreset


def test_saving_over_an_unreadable_file_refuses_rather_than_clobbering(
    tmp_path,
):
    """save() rebuilds the file from what _load() returned; treating a
    corrupt file as empty silently destroyed every other custom preset."""

    from llm_youtube_comment_generation.infrastructure.json_preset_store \
        import JsonPresetStore

    path = tmp_path / "presets.json"
    path.write_text("{ not json", encoding="utf-8")
    store = JsonPresetStore(path)

    assert store.all()          # display still works: built-ins only

    with pytest.raises(ConfigurationError, match="overwrite presets"):
        store.save(WritingPreset(name="Mine",
                                 reply_variations=("dry_one_liner",)))
    assert path.read_text(encoding="utf-8") == "{ not json"


def test_a_newer_schema_file_is_never_overwritten(tmp_path):
    from llm_youtube_comment_generation.infrastructure.json_preset_store \
        import JsonPresetStore

    path = tmp_path / "presets.json"
    path.write_text(json.dumps({"schema_version": 99, "presets": []}),
                    encoding="utf-8")
    store = JsonPresetStore(path)

    with pytest.raises(ConfigurationError, match="schema_version 99"):
        store.save(WritingPreset(name="Mine",
                                 reply_variations=("dry_one_liner",)))

import json

import pytest

from llm_youtube_comment_generation.domain.errors import ConfigurationError
from llm_youtube_comment_generation.domain.writing_presets import (
    BUILT_IN_PRESETS,
    WritingPreset,
)
from llm_youtube_comment_generation.infrastructure.json_preset_store import (
    JsonPresetStore,
)


def test_store_combines_builtins_and_saved_custom_presets(tmp_path):
    store = JsonPresetStore(tmp_path / "writing_presets.json")
    saved = store.save(WritingPreset(
        name="My careful preset",
        comment_variations=("one_concrete_thing",),
        dials=(("humor", "none"),),
        length="medium",
    ))

    assert saved.name == "My careful preset"
    assert [preset.name for preset in store.all()][-1] == "My careful preset"
    assert store.path.is_file()
    assert not store.path.with_name("writing_presets.json.tmp").exists()


def test_saving_the_same_custom_name_replaces_it(tmp_path):
    store = JsonPresetStore(tmp_path / "presets.json")
    store.save(WritingPreset(name="Mine", length="short"))
    store.save(WritingPreset(name="mine", length="long"))

    custom = [preset for preset in store.all() if not preset.builtin]

    assert len(custom) == 1
    assert custom[0].length == "long"


def test_builtin_names_cannot_be_replaced_or_deleted(tmp_path):
    store = JsonPresetStore(tmp_path / "presets.json")

    with pytest.raises(ConfigurationError, match="built-in"):
        store.save(WritingPreset(name=BUILT_IN_PRESETS[0].name))
    with pytest.raises(ConfigurationError, match="cannot be deleted"):
        store.delete(BUILT_IN_PRESETS[0].name)


def test_custom_preset_can_be_deleted(tmp_path):
    store = JsonPresetStore(tmp_path / "presets.json")
    store.save(WritingPreset(name="Temporary"))

    assert store.delete("temporary")
    assert not [preset for preset in store.all() if not preset.builtin]
    assert not store.delete("missing")


def test_malformed_or_future_file_falls_back_to_builtins(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text("{broken", encoding="utf-8")
    assert JsonPresetStore(path).all() == BUILT_IN_PRESETS

    path.write_text(
        json.dumps({"schema_version": 999, "presets": []}),
        encoding="utf-8",
    )
    assert JsonPresetStore(path).all() == BUILT_IN_PRESETS
