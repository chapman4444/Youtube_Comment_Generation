"""Atomic JSON persistence for custom writing presets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain.errors import ConfigurationError
from ..domain.writing_presets import (
    BUILT_IN_PRESETS,
    PRESET_SCHEMA_VERSION,
    WritingPreset,
    built_in_by_name,
)


class JsonPresetStore:
    """Keep user presets outside the project and merge them with built-ins."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def all(self) -> tuple[WritingPreset, ...]:
        custom = sorted(self._load(), key=lambda preset: preset.name.casefold())
        return BUILT_IN_PRESETS + tuple(custom)

    def save(self, preset: WritingPreset) -> WritingPreset:
        if preset.builtin or built_in_by_name(preset.name):
            raise ConfigurationError(
                f"{preset.name!r} is a built-in preset. Choose another name."
            )
        custom = {
            existing.key: existing
            for existing in self._load(for_write=True)
        }
        saved = WritingPreset.from_payload(preset.to_payload())
        custom[saved.key] = saved
        self._write(tuple(custom.values()))
        return saved

    def delete(self, name: str) -> bool:
        if built_in_by_name(name):
            raise ConfigurationError("Built-in presets cannot be deleted.")
        wanted = str(name).casefold()
        existing = self._load(for_write=True)
        kept = tuple(preset for preset in existing if preset.key != wanted)
        if len(kept) == len(existing):
            return False
        self._write(kept)
        return True

    def _load(self, *, for_write: bool = False) -> tuple[WritingPreset, ...]:
        """Read the custom presets; a broken file must never be clobbered.

        Reading an unreadable or newer-schema file as "no presets" is fine
        for display — the built-ins still work. Writing on top of it is
        not: save() rebuilds the whole file from what _load() returned, so
        treating corruption as emptiness silently destroyed every other
        custom preset (harsh-critic review, finding 14). A write against a
        file this method cannot read refuses instead.
        """

        def unreadable(reason: str) -> tuple[WritingPreset, ...]:
            if for_write:
                raise ConfigurationError(
                    f"The preset file at {self.path} {reason}, so saving "
                    "would overwrite presets this version cannot read. "
                    "Move the file aside (or fix it) and try again."
                )
            return ()

        if not self.path.is_file():
            return ()
        try:
            payload: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return unreadable("could not be read as JSON")
        if not isinstance(payload, dict):
            return unreadable("does not hold a preset document")
        if payload.get("schema_version") != PRESET_SCHEMA_VERSION:
            return unreadable(
                f"has schema_version {payload.get('schema_version')!r}, "
                f"not {PRESET_SCHEMA_VERSION}"
            )
        rows = payload.get("presets", [])
        if not isinstance(rows, list):
            return unreadable("holds no preset list")
        loaded: list[WritingPreset] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                preset = WritingPreset.from_payload(row)
            except ConfigurationError:
                continue
            if built_in_by_name(preset.name):
                continue
            loaded.append(preset)
        # Last duplicate wins, matching Save's replacement semantics.
        unique = {preset.key: preset for preset in loaded}
        return tuple(unique.values())

    def _write(self, presets: tuple[WritingPreset, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        payload = {
            "schema_version": PRESET_SCHEMA_VERSION,
            "presets": [
                preset.to_payload()
                for preset in sorted(
                    presets, key=lambda item: item.name.casefold()
                )
            ],
        }
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
