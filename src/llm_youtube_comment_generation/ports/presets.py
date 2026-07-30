"""Storage boundary for user-created writing presets."""

from __future__ import annotations

from typing import Protocol, Sequence

from ..domain.writing_presets import WritingPreset


class PresetStore(Protocol):
    def all(self) -> Sequence[WritingPreset]:
        """Return built-in presets followed by custom presets."""

    def save(self, preset: WritingPreset) -> WritingPreset:
        """Create or replace one custom preset."""

    def delete(self, name: str) -> bool:
        """Delete a custom preset by name; built-ins cannot be deleted."""
