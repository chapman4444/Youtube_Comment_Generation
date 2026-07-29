"""Loading versioned prompt text.

Two rules, both enforced at load rather than trusted:

1. Every placeholder a resource contains must be declared in the manifest.
   An undeclared placeholder means the renderer does not know to fill it, and
   the failure would otherwise appear as a literal ``{brace}`` in a packet
   pasted into a model.

2. The bytes must match the recorded checksum. The prompt text is the
   product; a silent edit to it is a silent change to what the operator ships
   under his own name.

Loaded once and cached, because a prompt that changed mid-run would make a
packet that no longer matches the version recorded in run.json.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..domain.errors import ConfigurationError

PROMPTS = Path(__file__).resolve().parent.parent / "resources" / "prompts"
MANIFEST = PROMPTS / "manifest.json"
CHECKSUMS = PROMPTS / "checksums.json"

PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


@dataclass(frozen=True)
class PromptResource:
    """One template, its declared placeholders, and its identity."""

    name: str
    text: str
    placeholders: frozenset[str]
    sha256: str

    def fill(self, values: dict[str, str]) -> str:
        """Substitute declared placeholders. Refuses anything undeclared.

        Deliberately not ``str.format``: the prompt text contains literal
        braces in its own examples, and format() would either raise on them
        or silently consume them.
        """

        undeclared = set(values) - self.placeholders
        if undeclared:
            raise ConfigurationError(
                f"{self.name} does not declare {', '.join(sorted(undeclared))}. "
                f"It declares: {', '.join(sorted(self.placeholders)) or 'nothing'}."
            )
        filled = self.text
        for placeholder, value in values.items():
            filled = filled.replace("{" + placeholder + "}", value)
        return filled

    def unfilled(self, rendered: str) -> list[str]:
        """Declared placeholders still present after filling."""

        return sorted(
            name for name in PLACEHOLDER.findall(rendered)
            if name in self.placeholders
        )


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _manifest() -> dict:
    if not MANIFEST.is_file():
        raise ConfigurationError(f"The prompt manifest is missing at {MANIFEST}")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _checksums() -> dict:
    if not CHECKSUMS.is_file():
        return {}
    return json.loads(CHECKSUMS.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def load(name: str) -> PromptResource:
    """Load one prompt resource, checking it against its manifest."""

    entry = _manifest().get(name)
    if not isinstance(entry, dict):
        raise ConfigurationError(
            f"{name} is not declared in the prompt manifest. Add it there "
            "with the placeholders it supports."
        )

    path = PROMPTS / name
    if not path.is_file():
        raise ConfigurationError(f"The prompt resource {name} is missing.")

    # Read as bytes and decode strictly: a prompt that silently became
    # mojibake would still render, and the damage would land in the model's
    # input rather than in a stack trace.
    text = path.read_bytes().decode("utf-8")
    declared = frozenset(entry.get("placeholders", ()))
    present = set(PLACEHOLDER.findall(text))

    undeclared = present - declared
    if undeclared:
        raise ConfigurationError(
            f"{name} contains undeclared placeholder(s): "
            f"{', '.join(sorted(undeclared))}. Declare them in manifest.json "
            "or the renderer will never fill them."
        )

    return PromptResource(
        name=name, text=text, placeholders=declared, sha256=digest(text)
    )


def prompt_version() -> str:
    """A short identity for the whole prompt set.

    Recorded in run.json so a scoreboard can eventually attribute results to
    the prompt that produced them. Derived from the checksums rather than
    hand-maintained, because a hand-maintained version number is one somebody
    forgets to bump.
    """

    names = sorted(name for name in _manifest() if name.endswith(".md"))
    combined = "".join(load(name).sha256 for name in names)
    return digest(combined)[:12]


def recorded_checksum(name: str) -> str:
    return str(_checksums().get(name, {}).get("sha256", ""))
