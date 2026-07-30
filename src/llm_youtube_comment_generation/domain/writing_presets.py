"""Named, portable sets of writing choices.

A preset deliberately contains only the choices that shape prose. Videos,
handles, paths, proxies, retrieval limits, and credentials are personal or
run-specific and can never enter this model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ConfigurationError
from .writing_options import DIALS, VARIATION_LIBRARY, variation_keys

PRESET_SCHEMA_VERSION = 1
VALID_LENGTHS = frozenset({"auto", "short", "medium", "long", "exact"})


@dataclass(frozen=True)
class WritingPreset:
    """One validated collection of comment and reply writing choices."""

    name: str
    description: str = ""
    comment_variations: tuple[str, ...] = ()
    reply_variations: tuple[str, ...] = ()
    dials: tuple[tuple[str, str], ...] = ()
    length: str = "auto"
    custom_length: str = ""
    builtin: bool = False

    def __post_init__(self) -> None:
        name = " ".join(str(self.name).split())
        if not name:
            raise ConfigurationError("A preset needs a name.")
        if len(name) > 60:
            raise ConfigurationError("A preset name cannot exceed 60 characters.")
        if any(character in name for character in "\r\n\t"):
            raise ConfigurationError("A preset name must be one line.")

        def validated(values: tuple[str, ...]) -> tuple[str, ...]:
            unknown = [value for value in values if value not in VARIATION_LIBRARY]
            if unknown:
                raise ConfigurationError(
                    f"Preset {name!r} contains unknown register "
                    f"{unknown[0]!r}."
                )
            return variation_keys(values) if values else ()

        comments = validated(self.comment_variations)
        replies = validated(self.reply_variations)

        dial_map: dict[str, str] = {}
        for dial, choice in self.dials:
            if dial not in DIALS:
                raise ConfigurationError(
                    f"Preset {name!r} contains unknown dial {dial!r}."
                )
            if choice not in DIALS[dial].choices:
                raise ConfigurationError(
                    f"Preset {name!r} cannot set {dial} to {choice!r}."
                )
            dial_map[dial] = choice

        length = str(self.length or "auto")
        if length not in VALID_LENGTHS:
            raise ConfigurationError(
                f"Preset {name!r} contains unknown length {length!r}."
            )
        custom = str(self.custom_length or "").strip()
        if length == "exact" and (not custom.isdigit() or int(custom) < 2):
            raise ConfigurationError(
                f"Preset {name!r} needs a target of at least 2 words."
            )

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(self, "comment_variations", comments)
        object.__setattr__(self, "reply_variations", replies)
        object.__setattr__(self, "dials", tuple(sorted(dial_map.items())))
        object.__setattr__(self, "length", length)
        object.__setattr__(
            self, "custom_length", custom if length == "exact" else ""
        )

    @property
    def dial_values(self) -> dict[str, str]:
        return dict(self.dials)

    @property
    def key(self) -> str:
        return self.name.casefold()

    def to_payload(self) -> dict[str, Any]:
        """The stable JSON representation used for custom presets."""

        return {
            "name": self.name,
            "description": self.description,
            "comment_variations": list(self.comment_variations),
            "reply_variations": list(self.reply_variations),
            "dials": self.dial_values,
            "length": self.length,
            "custom_length": self.custom_length,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        builtin: bool = False,
    ) -> "WritingPreset":
        dials = payload.get("dials", {})
        if not isinstance(dials, Mapping):
            raise ConfigurationError("Preset dials must be an object.")
        comments = payload.get("comment_variations", ())
        replies = payload.get("reply_variations", ())
        if not isinstance(comments, (list, tuple)):
            raise ConfigurationError("Preset comment variations must be a list.")
        if not isinstance(replies, (list, tuple)):
            raise ConfigurationError("Preset reply variations must be a list.")
        return cls(
            name=str(payload.get("name", "")),
            description=str(payload.get("description", "")),
            comment_variations=tuple(str(value) for value in comments),
            reply_variations=tuple(str(value) for value in replies),
            dials=tuple(
                (str(name), str(value)) for name, value in dials.items()
            ),
            length=str(payload.get("length", "auto")),
            custom_length=str(payload.get("custom_length", "")),
            builtin=builtin,
        )


BUILT_IN_PRESETS: tuple[WritingPreset, ...] = (
    WritingPreset(
        name="Default",
        description="The normal five approaches and default writing behavior.",
        builtin=True,
    ),
    WritingPreset(
        name="Concise and direct",
        description="Short, concrete drafts with minimal setup.",
        comment_variations=(
            "short_hook", "flat_claim", "one_concrete_thing",
        ),
        reply_variations=(
            "dry_one_liner", "flat_contradiction", "one_concrete_detail",
        ),
        dials=(
            ("ending", "flat"),
            ("critique", "ranking"),
            ("final", "best_single"),
        ),
        length="short",
        builtin=True,
    ),
    WritingPreset(
        name="Evidence first",
        description="Lead with timestamps, numbers, quotations, and correction.",
        comment_variations=(
            "timestamp_callout", "numbers_only", "quote_and_react",
            "correction",
        ),
        reply_variations=(
            "one_concrete_detail", "timestamp_callout", "numbers_only",
            "quote_and_react", "correction",
        ),
        dials=(("humor", "none"), ("grounding", "summary")),
        length="medium",
        builtin=True,
    ),
    WritingPreset(
        name="Constructive",
        description="Disagree or add context without attacking the person.",
        comment_variations=(
            "agreeable", "sympathetic", "humane", "appreciation",
        ),
        reply_variations=(
            "agree_and_add", "sympathetic", "humane", "appreciation",
        ),
        dials=(("humor", "none"), ("aggression", "never")),
        length="medium",
        builtin=True,
    ),
    WritingPreset(
        name="Dry and sharp",
        description="Compact deadpan, sarcasm, and blunt correction.",
        comment_variations=(
            "dry_joke", "dry_observation", "sardonic", "deadpan",
        ),
        reply_variations=(
            "dry_one_liner", "blunt_correction", "sardonic", "deadpan",
        ),
        dials=(
            ("hedging", "none"),
            ("ending", "flat"),
            ("humor", "sarcasm"),
            ("critique", "ranking"),
            ("final", "best_single"),
        ),
        length="short",
        builtin=True,
    ),
    WritingPreset(
        name="Balanced",
        description="A varied short set: concrete, analytical, corrective, and dry.",
        comment_variations=(
            "one_concrete_thing", "dry_observation", "correction", "question",
        ),
        reply_variations=(
            "one_concrete_detail", "dry_observation", "correction", "question",
        ),
        dials=(("final", "best_single"),),
        length="medium",
        builtin=True,
    ),
    WritingPreset(
        name="Skeptical",
        description="Test the claim, identify gaps, and surface the strongest doubt.",
        comment_variations=(
            "unanswered_gap", "devils_advocate", "cynical_read", "correction",
        ),
        reply_variations=(
            "unanswered_gap", "devils_advocate", "cynical_read", "correction",
        ),
        dials=(
            ("humor", "none"),
            ("critique", "full"),
            ("grounding", "summary"),
        ),
        length="medium",
        builtin=True,
    ),
    WritingPreset(
        name="Questions and gaps",
        description="Focus on what the video leaves unanswered or unresolved.",
        comment_variations=(
            "question", "unanswered_gap", "devils_advocate", "prediction",
        ),
        reply_variations=(
            "question", "unanswered_gap", "devils_advocate", "prediction",
        ),
        dials=(("humor", "none"), ("final", "best_single")),
        length="medium",
        builtin=True,
    ),
    WritingPreset(
        name="Direct rebuttal",
        description="Correct the central claim plainly and support the correction.",
        comment_variations=(
            "flat_claim", "blunt_correction", "numbers_only", "correction",
        ),
        reply_variations=(
            "flat_contradiction", "blunt_correction", "numbers_only", "correction",
        ),
        dials=(
            ("hedging", "none"),
            ("ending", "flat"),
            ("humor", "none"),
            ("final", "best_single"),
        ),
        length="short",
        builtin=True,
    ),
    WritingPreset(
        name="Creative angles",
        description="Try analogy, prediction, dry humor, and one unusual premise.",
        comment_variations=(
            "analogy", "prediction", "dry_joke", "off_the_wall",
        ),
        reply_variations=(
            "analogy", "prediction", "dry_one_liner", "off_the_wall",
        ),
        dials=(("final", "best_single"),),
        length="short",
        builtin=True,
    ),
    WritingPreset(
        name="Human impact",
        description="Center the people affected while keeping the claim concrete.",
        comment_variations=(
            "humane", "sympathetic", "one_concrete_thing", "historical_parallel",
        ),
        reply_variations=(
            "humane", "sympathetic", "one_concrete_detail", "historical_parallel",
        ),
        dials=(("humor", "none"), ("aggression", "never")),
        length="medium",
        builtin=True,
    ),
    WritingPreset(
        name="Full analysis",
        description="A developed, evidence-grounded argument with alternatives.",
        comment_variations=(
            "full_argument", "one_concrete_thing", "correction",
            "devils_advocate", "historical_parallel",
        ),
        reply_variations=(
            "full_answer", "one_concrete_detail", "correction",
            "devils_advocate", "historical_parallel",
        ),
        dials=(
            ("humor", "none"),
            ("critique", "full"),
            ("final", "synthesis"),
            ("grounding", "summary"),
        ),
        length="long",
        builtin=True,
    ),
)


def built_in_by_name(name: str) -> WritingPreset | None:
    wanted = str(name).casefold()
    return next((preset for preset in BUILT_IN_PRESETS if preset.key == wanted), None)


def known_variations(preset: WritingPreset) -> bool:
    """A small explicit predicate useful to import/audit callers."""

    return all(
        key in VARIATION_LIBRARY
        for key in preset.comment_variations + preset.reply_variations
    )
