"""Every option the window offers, decided without a window.

Taken from the old application's `youtube_packet_gui.py`, which is the only
place these choices have ever been written down. The new window had none of
them: it was a state machine with eleven buttons, and the operator could not
set a register, a dial, a length or a comment count from it at all.

Pure and separately testable, for the same reason `view_models` is. Tk
interpreter creation is flaky on this machine, so every rule that can be
checked without a display is checked without one — and these are the rules
that decide what gets built, which is the part worth being sure about.

Three things this module is careful about, each of which the old one got right
and is easy to lose in a rewrite:

**A blank is not a zero.** "Registers: none selected" means the defaults, not
"draft nothing". The old picker says so in its own label and the old config
honours it.

**The dials are per-run, the registers are per-mode.** A comment and a reply
are not answering the same thing, so they have separate register lists; how
the answer is *written* applies to whichever is being built.

**What is remembered is remembered by name.** The settings file is the
operator's, written by the old application and readable by it afterwards, so
the field names are its field names and not tidier ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

from ...domain.packets import (
    DEFAULT_PACKET_CHARACTERS,
    MINIMUM_PACKET_CHARACTERS,
)
from ...domain.section_profile import LENGTH_PRESETS
from ...domain.ids import extract_video_id
from ...domain.errors import ConfigurationError
from ...domain.writing_options import (
    DIAL_CHOICE_CLASSIFICATIONS,
    DEFAULT_REPLY_VARIATIONS,
    DEFAULT_VARIATIONS,
    DIALS,
    VARIATION_LIBRARY,
    dial_choice,
    dial_choice_label,
    resolved_variation_keys,
    variation_keys,
)
from ...domain.writing_presets import WritingPreset

#: The field names the old application writes into its settings file. Kept
#: exactly, so a settings file written by either is read by both.
REMEMBERED = (
    "my_handle", "output_directory", "since", "languages",
    "packet_characters", "max_top", "max_recent", "max_threads",
    "max_replies", "top_repliers", "include_replies", "per_thread",
    "include_answered", "use_triage", "length", "custom_length",
    "auto_run", "auto_watch", "editor_path", "reply_scan_comments",
    "guided_limit", "window_geometry", "transcribe_locally", "whisper_model",
)

#: The four length choices, and what the old window calls them.
LENGTH_CHOICES = (
    ("auto", "Match the room"),
    ("short", "Short"),
    ("medium", "Medium"),
    ("long", "Long"),
    ("exact", "Target words"),
)

LENGTH_HINTS = {
    "auto": (
        "Uses the supplied comment sample to estimate the room's normal "
        "length. The result is a target band, not a hard maximum."
    ),
    "short": (
        f"Targets {LENGTH_PRESETS['short'][0]}–{LENGTH_PRESETS['short'][1]} "
        "words. The packet may allow a small safety margin so a "
        "complete claim is not cut off; the same rule applies to variations "
        "and hardened finals."
    ),
    "medium": (
        f"Targets {LENGTH_PRESETS['medium'][0]}–"
        f"{LENGTH_PRESETS['medium'][1]} words. This is a preferred band "
        "rather than an exact "
        "count, with enough room to complete a short argument cleanly."
    ),
    "long": (
        f"Targets {LENGTH_PRESETS['long'][0]}–{LENGTH_PRESETS['long'][1]} "
        "words. Use it when the evidence needs a developed "
        "argument; critique length is not controlled by this setting."
    ),
    "exact": (
        "Uses the entered word count as a target, not a hard limit. The "
        "backend renders a measured band around it and still reports the "
        "source comment sample for context."
    ),
}

LENGTH_SUMMARIES = {
    "auto": "Uses the comments to estimate a natural target.",
    "short": "A compact comment.",
    "medium": "A short paragraph.",
    "long": "A developed argument.",
    "exact": "Aims for the word count entered above.",
}

MIN_TARGET_WORDS = 2

# The default dial values intentionally render no extra prompt text, but the
# interface still has to explain their real effect. This is the single source
# used by both persistent help and tooltips.
DEFAULT_DIAL_BEHAVIOR = {
    "person": (
        "Uses the natural point of view for the selected approach; it does "
        "not force first person, direct address, or an impersonal voice."
    ),
    "hedging": (
        "Allows at most one explicit qualifier, and only where the evidence "
        "requires it."
    ),
    "ending": (
        "Ends on a concrete consequence: what happens, who does it, or what "
        "it costs."
    ),
    "humor": (
        "Leaves humor available where a selected approach calls for it, "
        "without requiring jokes or sarcasm in every draft."
    ),
    "critique": (
        "Ranks every variation, explains each placement, and repairs the "
        "weakest reasoning before final assembly."
    ),
    "final": (
        "Builds one Hardened final by synthesizing the strongest repairable "
        "material."
    ),
    "grounding": (
        "Starts directly with the requested drafts; it does not add a "
        "separate summary-and-cast section before them."
    ),
    "aggression": (
        "Keeps criticism aimed at the claim and its consequences rather than "
        "attacking the person who made it."
    ),
}


@dataclass
class PacketOptionsModel:
    """Everything the window can set, with the old application's defaults."""

    # -- the video and where the output goes ----------------------------
    video: str = ""
    output_directory: str = ""
    editor_path: str = ""

    # -- retrieval -------------------------------------------------------
    max_top: int = 100
    max_recent: int = 100
    max_threads: int = 20
    max_replies: int = 8
    reply_scan_comments: int = 3000
    include_replies: bool = True
    overwrite: bool = False
    languages: str = "en"
    proxy_url: str = ""
    transcribe_locally: bool = False
    whisper_model: str = "small.en"

    # -- the packet -------------------------------------------------------
    packet_characters: int = DEFAULT_PACKET_CHARACTERS
    length: str = "auto"
    custom_length: str = ""

    # -- what to draft ----------------------------------------------------
    comment_variations: tuple[str, ...] = ()
    reply_variations: tuple[str, ...] = ()
    comment_approach_mode: str = "default"
    reply_approach_mode: str = "default"
    dials: dict[str, str] = field(default_factory=dict)

    # -- reply mode --------------------------------------------------------
    my_handle: str = ""
    since: str = ""
    top_repliers: int = 0
    reply_to: str = ""
    per_thread: bool = False
    include_answered: bool = False
    use_triage: bool = True
    guided_limit: int = 10
    auto_run: bool = False
    auto_watch: bool = False
    window_geometry: str = ""

    # -- derived ----------------------------------------------------------

    @property
    def transcript_languages(self) -> tuple[str, ...]:
        """The language list, from a comma-separated field.

        Empty stays empty rather than becoming ("",): a language code of the
        empty string matches no caption track and would turn "I did not set
        this" into "no transcript is acceptable".
        """

        return tuple(
            part.strip() for part in (self.languages or "").split(",")
            if part.strip()
        ) or ("en",)

    def registers_for(self, mode: str) -> tuple[str, ...]:
        """The chosen registers, or the defaults when none are chosen.

        None selected means the defaults. It does not mean draft nothing, and
        a window that treated an empty listbox as an empty answer would build
        a packet asking for no sections at all.
        """

        chosen = (self.reply_variations if mode == "reply"
                  else self.comment_variations)
        if not chosen:
            return tuple(DEFAULT_REPLY_VARIATIONS if mode == "reply"
                         else DEFAULT_VARIATIONS)
        # variation_keys validates and orders; both modes draw from the one
        # library, so there is one function rather than two that could drift.
        return variation_keys(chosen)

    def dial_values(self) -> dict[str, str]:
        """Every dial, including the ones left alone.

        Named in full rather than only the changed ones, because the run
        record has to say what the packet was built with and "absent" and "at
        its default" are indistinguishable afterwards.
        """

        return {name: dial_choice(name, self.dials) for name in DIALS}

    def explicit_length(self) -> tuple[int, int] | None:
        """A word range from the custom field, or None to use the radio.

        The old window lets a number override the radio buttons rather than
        adding a fifth radio, so a typed number always wins.
        """

        if self.length != "exact":
            return None
        text = (self.custom_length or "").strip()
        if not text:
            return None
        if not text.isdigit():
            return None
        middle = int(text)
        if middle < MIN_TARGET_WORDS:
            return None
        # The backend accepts a preferred range rather than promising an exact
        # count that prose cannot reliably hit.
        return (max(1, int(middle * 0.8)), max(2, int(middle * 1.25)))

    def length_hint(self) -> str:
        explicit = self.explicit_length()
        if explicit is not None:
            return f"{explicit[0]} to {explicit[1]} words, from the box."
        return LENGTH_HINTS.get(self.length, "")

    # -- validation --------------------------------------------------------

    def problems(self, *, mode: str = "comment") -> list[str]:
        """Everything wrong with this, in the operator's words.

        Returned as a list rather than raised one at a time: a window that
        reports the first problem, is corrected, then reports the second is
        how a form with four mistakes takes four attempts.
        """

        found: list[str] = []
        if not (self.video or "").strip():
            found.append("There is no video. Paste a URL or an ID.")
        else:
            try:
                extract_video_id(self.video)
            except ConfigurationError as failure:
                found.append(str(failure))
        if self.packet_characters < MINIMUM_PACKET_CHARACTERS:
            found.append(
                f"Packet characters is {self.packet_characters:,}, below the "
                f"{MINIMUM_PACKET_CHARACTERS:,} the smallest usable packet "
                "needs."
            )
        if mode == "reply" and not (self.my_handle or "").strip():
            found.append(
                "Reply mode needs your @username, so it knows which comments "
                "are yours."
            )
        if self.reply_scan_comments < 1:
            found.append("Reply scan comments must be at least 1.")
        if self.max_replies < 1:
            found.append("Replies per thread must be at least 1.")
        if self.guided_limit < 1:
            found.append("Reply limit must be at least 1.")
        for name, value in (self.dials or {}).items():
            if name not in DIALS:
                found.append(f"There is no dial called {name!r}.")
            elif value not in DIALS[name].choices:
                found.append(
                    f"{name} cannot be {value!r}. Choose one of: "
                    f"{', '.join(DIALS[name].choices)}."
                )
        for mode_name, keys in (("comment", self.comment_variations),
                                ("reply", self.reply_variations)):
            for key in keys:
                if key not in VARIATION_LIBRARY:
                    found.append(f"There is no {mode_name} register {key!r}.")
        for mode_name, selection_mode, keys in (
            ("comment", self.comment_approach_mode, self.comment_variations),
            ("reply", self.reply_approach_mode, self.reply_variations),
        ):
            if selection_mode not in ("default", "custom"):
                found.append(
                    f"{mode_name.title()} approach mode cannot be "
                    f"{selection_mode!r}."
                )
        if self.length not in dict(LENGTH_CHOICES):
            found.append(f"Length cannot be {self.length!r}.")
        if self.length == "exact":
            text = (self.custom_length or "").strip()
            if not text:
                found.append("Enter a target word count.")
            elif not text.isdigit():
                found.append("Target words must be a whole number.")
            elif int(text) < MIN_TARGET_WORDS:
                found.append(
                    f"Target words must be at least {MIN_TARGET_WORDS}."
                )
        return found

    # -- persistence -------------------------------------------------------

    def to_settings(self) -> dict[str, Any]:
        """The shape the old application's settings file uses."""

        payload: dict[str, Any] = {name: getattr(self, name)
                                   for name in REMEMBERED}
        payload["comment_variations"] = list(self.comment_variations)
        payload["reply_variations"] = list(self.reply_variations)
        payload["comment_approach_mode"] = self.comment_approach_mode
        payload["reply_approach_mode"] = self.reply_approach_mode
        payload["dials"] = dict(self.dials)
        payload["proxy_url"] = self.proxy_url
        return payload

    @classmethod
    def from_settings(cls, payload: Mapping[str, Any] | None) -> "PacketOptionsModel":
        """Read a settings file, ignoring anything it does not recognise.

        A settings file written by a newer version, or by hand, must not stop
        the window opening. Unknown keys are dropped and bad types fall back
        to the default rather than raising: the worst outcome of a malformed
        settings file should be that one field is not remembered.
        """

        model = cls()
        if not payload:
            return model

        for name in REMEMBERED + ("proxy_url",):
            if name not in payload:
                continue
            current = getattr(model, name)
            value = payload[name]
            try:
                if isinstance(current, bool):
                    setattr(model, name, bool(value))
                elif isinstance(current, int):
                    setattr(model, name, int(value))
                else:
                    setattr(model, name, str(value))
            except (TypeError, ValueError):
                continue

        model.comment_variations = _known(payload.get("comment_variations"))
        model.reply_variations = _known(payload.get("reply_variations"))
        for name, variations in (
            ("comment_approach_mode", model.comment_variations),
            ("reply_approach_mode", model.reply_variations),
        ):
            saved = str(payload.get(name, "") or "")
            setattr(
                model, name,
                saved if saved in ("default", "custom")
                else ("custom" if variations else "default"),
            )
        # The legacy GUI let a populated custom-length field override the
        # radio selection. Preserve that saved intent while making the new
        # UI's Exact mode explicit.
        if model.custom_length.strip() and model.length != "exact":
            model.length = "exact"
        dials = payload.get("dials")
        if isinstance(dials, Mapping):
            model.dials = {
                str(name): str(value) for name, value in dials.items()
                if name in DIALS and value in DIALS[str(name)].choices
            }
        return model

    def reset_output_options(self) -> "PacketOptionsModel":
        """Back to the packet this produced before the options existed.

        Registers and dials only. The old window's button is deliberately
        narrow: it does not clear the video, the handle or the output folder,
        because somebody reaching for "reset the writing options" has not
        asked to retype the address.
        """

        return replace(
            self,
            comment_variations=(),
            reply_variations=(),
            comment_approach_mode="default",
            reply_approach_mode="default",
            dials={},
        )

    def apply_writing_preset(
        self,
        preset: WritingPreset,
    ) -> "PacketOptionsModel":
        """Apply prose choices without touching personal or retrieval data."""

        return replace(
            self,
            comment_variations=tuple(preset.comment_variations),
            reply_variations=tuple(preset.reply_variations),
            comment_approach_mode=(
                "custom" if preset.comment_variations else "default"
            ),
            reply_approach_mode=(
                "custom" if preset.reply_variations else "default"
            ),
            dials=preset.dial_values,
            length=preset.length,
            custom_length=preset.custom_length,
        )

    def as_writing_preset(
        self,
        name: str,
        *,
        description: str = "",
    ) -> WritingPreset:
        """Capture only reusable writing choices, never personal settings."""

        return WritingPreset(
            name=name,
            description=description,
            comment_variations=self.comment_variations,
            reply_variations=self.reply_variations,
            dials=tuple(self.dials.items()),
            length=self.length,
            custom_length=self.custom_length,
        )


def _known(values: Any) -> tuple[str, ...]:
    """Only registers that still exist, in the order given."""

    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(str(v) for v in values if str(v) in VARIATION_LIBRARY)


def register_choices(mode: str) -> list[tuple[str, str]]:
    """(key, label) for one mode's register list, in library order.

    Two entries share the heading "One concrete thing" — one worded for a
    comment section, one for a thread. Both are the operator's prose and
    neither may be reworded, so the list disambiguates instead, exactly as the
    old picker does.
    """

    keys = [key for key in VARIATION_LIBRARY]
    headings = [VARIATION_LIBRARY[key].heading for key in keys]
    choices: list[tuple[str, str]] = []
    for key in keys:
        entry = VARIATION_LIBRARY[key]
        label = entry.heading
        if headings.count(entry.heading) > 1:
            pipeline = ("reply" if key in DEFAULT_REPLY_VARIATIONS
                        else "comment")
            label = f"{entry.heading}  ({pipeline} wording)"
        choices.append((key, label))
    return choices


def approach_choices(mode: str) -> list[tuple[str, str, str, str]]:
    """Authoritative approach metadata for a GUI or other interface."""

    labels = dict(register_choices(mode))
    return [
        (
            key,
            labels[key],
            entry.dimension.value,
            entry.spec,
        )
        for key, entry in VARIATION_LIBRARY.items()
    ]


def resolved_approaches(
    chosen: Sequence[str],
    dials: Mapping[str, str],
    *,
    mode: str,
) -> tuple[str, ...]:
    """The visible resolved selection, using the packet resolver itself."""

    default = DEFAULT_REPLY_VARIATIONS if mode == "reply" else DEFAULT_VARIATIONS
    return resolved_variation_keys(chosen, dict(dials), default)


def dial_help(name: str, value: str) -> str:
    """A concise authoritative tooltip without duplicated UI headings."""

    entry = DIALS[name]
    selected = value if value in entry.choices else entry.default
    behavior = entry.choices[selected] or DEFAULT_DIAL_BEHAVIOR[name]
    return behavior
