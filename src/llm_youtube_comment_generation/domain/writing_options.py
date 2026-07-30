"""The selectable registers and dials.

These used to be prose inside the workflow template, which meant every run
asked for the same five variations whether or not they suited the video. They
are data now: a run chooses a set, the packet asks for exactly that set under
exactly these headings, and the validator checks the same list.

The spec text is the operator's own prompt wording and is ported verbatim.
Nothing here rewrites, tightens or reorders it.

Every dial's default choice maps to an empty string. Choosing it emits
nothing, so a run left alone produces the packet that existed before any of
this did. That property is what makes the option set safe, and
``default_output_options()`` is the tested way back to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple, Sequence

from .errors import ConfigurationError


class ApproachDimension(str, Enum):
    """The semantic axis a selectable rhetorical approach changes."""

    FORM = "form"
    STANCE = "stance"
    TONE = "tone"
    EVIDENCE = "evidence strategy"
    TEMPORAL = "temporal proposition"
    FUNCTION = "analytical function"
    SUBJECT = "subject"


@dataclass(frozen=True)
class VariationDefinition:
    """One rhetorical approach the packet can ask for.

    ``dimension`` makes the mixed library explicit: a stance is not treated
    as the same semantic kind as a tone, evidence strategy, temporal
    proposition, analytical function, subject choice, or surface form.

    ``waives_analysis`` marks the approaches whose whole purpose is something
    other than contributing an inference the video did not state. The analysis
    test is unconditional for every other approach; for these it is dropped,
    because applying it would fail the variation for doing its job.

    ``requires_humor`` is executable compatibility metadata. ``humor=none``
    resolves every approach carrying it before any prompt text is rendered.
    """

    heading: str
    spec: str
    dimension: ApproachDimension = ApproachDimension.FORM
    waives_analysis: bool = False
    requires_humor: bool = False


VARIATION_LIBRARY: dict[str, VariationDefinition] = {
    # The original five. Changing these keys changes saved settings.
    "short_hook": VariationDefinition(
        "Short hook",
        "One observation, inside the short limit. No preamble.",
    ),
    "flat_claim": VariationDefinition(
        "Flat claim",
        "State the position plainly, no hedging, no question.",
    ),
    "one_concrete_thing": VariationDefinition(
        "One concrete thing",
        "Built around a single specific detail: a number, a name, a "
        "timestamp, a mechanism. Abstract nouns make a comment forgettable.",
    ),
    "dry_joke": VariationDefinition(
        "Dry joke",
        "Understatement or wordplay that carries the point sideways. Jokes "
        "take the top spots in most comment sections, so write this one "
        "properly rather than treating it as filler.",
        dimension=ApproachDimension.TONE,
        requires_humor=True,
    ),
    "dry_observation": VariationDefinition(
        "Dry observation",
        "State one concrete inconsistency without joke, sarcasm, wordplay, "
        "or comic understatement.",
        dimension=ApproachDimension.TONE,
    ),
    "full_argument": VariationDefinition(
        "Full argument",
        "The complete case, at the longest length the rule allows. Where the "
        "rule allows no more room than the others have, make this one carry "
        "the most evidence rather than the most words.",
    ),
    # The reply pipeline's original five. Three of them have no comment
    # equivalent, and "One concrete thing" is worded for a thread rather than
    # a comment section, so it is a separate entry under the same heading.
    "dry_one_liner": VariationDefinition(
        "Dry one-liner",
        # The fixed "ten to twenty words" predates the measured length rule.
        # On a section whose comments run eleven words it ordered a comment
        # twice the local length, and the rule above already carries the real
        # number for this video.
        "Understatement or a light joke that lands the point sideways. The "
        "shortest of the set, at the bottom of the length rule above. This "
        "register earns the most likes in comment threads by a wide margin, "
        "so write it properly rather than treating it as the throwaway.",
        dimension=ApproachDimension.TONE,
        requires_humor=True,
    ),
    "flat_contradiction": VariationDefinition(
        "Flat contradiction",
        "Say plainly that the person you are answering is wrong and what is "
        "true instead. Aimed at their claim, not at the room. No softening, "
        "no preamble, no question at the end.",
    ),
    "one_concrete_detail": VariationDefinition(
        # Shares its heading with one_concrete_thing on purpose: this is the
        # reply pipeline's own wording and every reply packet has used it.
        # ``headings_by_key`` disambiguates the pair only when a selection
        # contains both, so the collision cannot reach a packet and the
        # default reply headings do not change.
        "One concrete thing",
        "Build the whole reply around a single specific detail: a number, a "
        "name, a timestamp, a document, a mechanism. Abstract nouns are what "
        "make a reply forgettable.",
    ),
    "agree_and_add": VariationDefinition(
        "Agree and add",
        "Concede their point in a few words and immediately add one fact or "
        "consequence they did not have. Agreement alone is worth nothing.",
        dimension=ApproachDimension.STANCE,
    ),
    "full_answer": VariationDefinition(
        "Full answer",
        # "of the five" was true when five was the only count. A three-register
        # run rendered a brief that named a number the packet did not ask for.
        "The complete reasoned reply, up to the length limit. This is the "
        "control, and it is usually the weakest of the set.",
    ),
    # Stance toward the audience.
    "agreeable": VariationDefinition(
        "Agreeable",
        "Grant what the room already accepts in a few words, then add the "
        "fact or consequence it does not have. Agreement alone is worth "
        "nothing.",
        dimension=ApproachDimension.STANCE,
    ),
    "hostile": VariationDefinition(
        "Hostile",
        # Was word-for-word flat_contradiction with "they" swapped for "the
        # prevailing read". Co-selected, the packet asked for two variations
        # that differ by register and handed them the same brief. The target
        # is what actually separates them, so the brief says so.
        "Say plainly that the room has it wrong and what is true instead. "
        "Aimed at the consensus in the comments rather than at any one "
        "person. No softening, no preamble, no question at the end.",
        dimension=ApproachDimension.TONE,
    ),
    "contemptuous": VariationDefinition(
        "Contemptuous",
        # Both this and off_the_wall claimed to be the highest-variance
        # register; co-selected, the packet said it twice about two things.
        "Treat the claim as beneath argument. Dismissal, not rebuttal. The "
        "riskiest of the stance registers: it either tops the section or "
        "reads as a sneer.",
        dimension=ApproachDimension.TONE,
    ),
    "sardonic": VariationDefinition(
        "Sardonic",
        "Mockery carried by understatement rather than insult. The facts do "
        "the damage; the tone only points at them.",
        dimension=ApproachDimension.TONE,
        requires_humor=True,
    ),
    "indignant": VariationDefinition(
        "Indignant",
        "Moral heat, aimed precisely. Name who is responsible and for what, "
        "and keep it to what the evidence carries.",
        dimension=ApproachDimension.TONE,
    ),
    "weary": VariationDefinition(
        "Weary",
        "We have been here before. Fatigue is the argument: name the pattern "
        "this is the latest instance of.",
        dimension=ApproachDimension.TONE,
    ),
    "sympathetic": VariationDefinition(
        "Sympathetic",
        "Assume good faith, correct the point gently, keep the reader on "
        "side. Warm, not soft: the correction still has to land.",
        dimension=ApproachDimension.TONE,
    ),
    "cold_analyst": VariationDefinition(
        "Cold analyst",
        "No attitude at all. Evidence, inference, conclusion. Nothing that "
        "signals how the writer feels about it.",
        dimension=ApproachDimension.TONE,
    ),
    "deadpan": VariationDefinition(
        "Deadpan",
        "State the damning fact and stop. No comment on it, no adjective "
        "doing the work the fact already does.",
        dimension=ApproachDimension.TONE,
    ),
    "blunt_correction": VariationDefinition(
        "Blunt correction",
        "One sentence. What is wrong, what is right, nothing else.",
    ),
    "endorsing": VariationDefinition(
        "Endorsing",
        "Come down on the video's side and strengthen it with the support "
        "it did not give itself. Backing without new material is filler.",
        dimension=ApproachDimension.STANCE,
    ),
    "dissenting": VariationDefinition(
        "Dissenting",
        "Take the opposite position outright and say what the evidence "
        "carries instead. Not a hedge, not a partial objection.",
        dimension=ApproachDimension.STANCE,
    ),
    "humane": VariationDefinition(
        "Humane",
        "Keep the people inside the story visible. Whatever the argument, "
        "it is happening to somebody, and the comment says who.",
        dimension=ApproachDimension.TONE,
    ),
    "furious": VariationDefinition(
        "Furious",
        "Plain anger, no moral scaffolding around it. Short sentences. It "
        "must still be anger at something specific the evidence shows.",
        dimension=ApproachDimension.TONE,
    ),
    "delighted": VariationDefinition(
        "Delighted",
        "Genuine enthusiasm for the thing the video got right or found. "
        "Specific about what, or it reads as empty praise.",
        dimension=ApproachDimension.TONE,
        waives_analysis=True,
    ),
    "scorched_earth": VariationDefinition(
        "Scorched earth",
        "Condemn the whole arrangement rather than this instance of it. "
        "Name the system and what it reliably produces. The claim is large, "
        "so the evidence under it has to be real.",
        dimension=ApproachDimension.STANCE,
    ),
    # Shape.
    "timestamp_callout": VariationDefinition(
        "Timestamp callout",
        "Anchored to one moment: name the time and what is said there, then "
        "the inference that follows from it.",
        dimension=ApproachDimension.EVIDENCE,
    ),
    "numbers_only": VariationDefinition(
        "Numbers only",
        "Carried entirely by figures and what they imply. No adjectives "
        "doing persuasive work.",
        dimension=ApproachDimension.EVIDENCE,
    ),
    "analogy": VariationDefinition(
        "Analogy",
        "One comparison that makes the mechanism obvious. It must survive "
        "scrutiny, not merely sound apt.",
        dimension=ApproachDimension.EVIDENCE,
    ),
    "prediction": VariationDefinition(
        "Prediction",
        "What happens next, stated concretely enough to be proved wrong. "
        "Name the actor and the consequence.",
        dimension=ApproachDimension.TEMPORAL,
    ),
    "question": VariationDefinition(
        "Question",
        "The specific question the video leaves unanswered, asked without "
        "implying the answer. Only worth writing when the gap is genuinely "
        "more interesting than any claim available.",
        dimension=ApproachDimension.FUNCTION,
        waives_analysis=True,
    ),
    "unanswered_gap": VariationDefinition(
        "Unanswered gap",
        "State the specific gap the video leaves unresolved as a flat "
        "observation. Do not ask a question or imply an answer.",
        dimension=ApproachDimension.FUNCTION,
        waives_analysis=True,
    ),
    # Mode.
    "summary": VariationDefinition(
        "Summary",
        "Restate the video's own point cleanly for someone who did not "
        "watch. This is deliberately a summary: do not stretch it into an "
        "inference the video did not make.",
        dimension=ApproachDimension.FUNCTION,
        waives_analysis=True,
    ),
    "off_the_wall": VariationDefinition(
        "Off the wall",
        "An absurd premise played entirely straight. Highest variance in "
        "the set. It still has to touch something the video actually shows.",
        dimension=ApproachDimension.TONE,
        waives_analysis=True,
        requires_humor=True,
    ),
    "correction": VariationDefinition(
        "Correction",
        "Name one thing the video gets wrong and what is actually true, "
        "with the support that settles it.",
        dimension=ApproachDimension.FUNCTION,
    ),
    "personal_anecdote": VariationDefinition(
        "Personal anecdote",
        "This happened to me, offered as evidence for or against the "
        "video's claim. Concrete, short, and not a story for its own sake.",
        dimension=ApproachDimension.EVIDENCE,
        waives_analysis=True,
    ),
    "domain_expertise": VariationDefinition(
        "Domain expertise",
        "The detail only somebody who does this for a living would flag. "
        "State the standard practice, then where this departs from it.",
        dimension=ApproachDimension.EVIDENCE,
    ),
    "devils_advocate": VariationDefinition(
        "Devil's advocate",
        "The strongest available case against the video's position, made "
        "honestly rather than as a straw man to knock down.",
        dimension=ApproachDimension.STANCE,
    ),
    "historical_parallel": VariationDefinition(
        "Historical parallel",
        "The earlier instance of the same thing, named specifically, and "
        "what happened that time.",
        dimension=ApproachDimension.EVIDENCE,
    ),
    "cynical_read": VariationDefinition(
        "Cynical read",
        "The unflattering motive the video is too polite to name. Offer it "
        "as a reading of the evidence, never as an established fact.",
        dimension=ApproachDimension.STANCE,
    ),
    "meta": VariationDefinition(
        "Meta",
        "An observation about the comment section or the audience rather "
        "than the video itself.",
        dimension=ApproachDimension.SUBJECT,
        waives_analysis=True,
    ),
    "quote_and_react": VariationDefinition(
        "Quote and react",
        "Pull one line from the video and respond to that line directly. "
        "Quote it short and exactly.",
        dimension=ApproachDimension.EVIDENCE,
        waives_analysis=True,
    ),
    "appreciation": VariationDefinition(
        "Appreciation",
        "Straight praise, specific enough that it could not be pasted under "
        "any other video.",
        dimension=ApproachDimension.STANCE,
        waives_analysis=True,
    ),
}


HUMOR_INCOMPATIBLE_REPLACEMENTS: dict[str, str] = {
    "dry_joke": "dry_observation",
    "dry_one_liner": "dry_observation",
    "sardonic": "dry_observation",
    "off_the_wall": "dry_observation",
}

DEFAULT_VARIATIONS: tuple[str, ...] = (
    "short_hook",
    "flat_claim",
    "one_concrete_thing",
    "dry_joke",
    "full_argument",
)

DEFAULT_REPLY_VARIATIONS: tuple[str, ...] = (
    "dry_one_liner",
    "flat_contradiction",
    "one_concrete_detail",
    "agree_and_add",
    "full_answer",
)

_COUNT_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten",
}


def count_word(count: int) -> str:
    """Spelled out up to ten, then digits. The prompt reads as prose."""

    return _COUNT_WORDS.get(count, str(count))


def join_headings(names: Sequence[str]) -> str:
    """Comma list with a trailing 'and'. Prose, because the prompt is prose."""

    names = list(names)
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def variation_keys(
    chosen: Sequence[str] | None = None,
    default: Sequence[str] = DEFAULT_VARIATIONS,
) -> tuple[str, ...]:
    """The chosen registers, in library order, with unknown keys dropped.

    An empty or unrecognised selection falls back to the pipeline's own five
    rather than producing a packet that asks for no variations at all.
    """

    if not chosen:
        return tuple(default)
    wanted = {key for key in chosen if key in VARIATION_LIBRARY}
    if not wanted:
        return tuple(default)
    return tuple(key for key in VARIATION_LIBRARY if key in wanted)


def headings_by_key(keys: Sequence[str]) -> dict[str, str]:
    """The heading each selected register shows, kept distinct.

    Two library entries deliberately share a heading: the comment pipeline's
    "One concrete thing" and the reply pipeline's, which is worded for a
    thread. Selected together they produced two identically named sections,
    which check 2 reads as two variations sharing a register and which makes
    validating the answer ambiguous.

    Disambiguating only on collision means the default selections keep the
    exact headings they have always had. A packet that never asks for both
    cannot tell this function exists.
    """

    seen: dict[str, int] = {}
    for key in keys:
        heading = VARIATION_LIBRARY[key].heading
        seen[heading] = seen.get(heading, 0) + 1
    return {
        key: (VARIATION_LIBRARY[key].heading
              if seen[VARIATION_LIBRARY[key].heading] == 1
              else f"{VARIATION_LIBRARY[key].heading} ({key})")
        for key in keys
    }


def headings_for(
    chosen: Sequence[str] | None = None,
    default: Sequence[str] = DEFAULT_VARIATIONS,
    selections: dict[str, str] | None = None,
) -> tuple[str, ...]:
    """Every heading the answer must contain, in order."""

    keys = resolved_variation_keys(chosen, selections, default)
    shown = headings_by_key(keys)
    numbered = tuple(
        f"### {index}. {shown[key]}" for index, key in enumerate(keys, 1)
    )
    before = (
        ("### What the video says",)
        if dial_choice("grounding", selections) == "summary"
        else ()
    )
    critique = (
        ()
        if dial_choice("critique", selections) == "none"
        else ("### Harsh critique",)
    )
    final = (
        ("### Hardened finals",)
        if dial_choice("final", selections) == "both"
        else ("### Hardened final",)
    )
    return before + numbered + critique + final


def analysis_waiver(keys: Sequence[str]) -> str:
    """The sentence exempting registers whose purpose is not an inference.

    Empty when every chosen register has to pass the analysis test, so the
    default set spends no words saying nothing.
    """

    shown = headings_by_key(keys)
    waived = [shown[key] for key in keys
              if VARIATION_LIBRARY[key].waives_analysis]
    if not waived:
        return ""
    if len(waived) == 1:
        subject = "That register was asked for on purpose and its value is"
        object_ = "it"
    else:
        subject = "Those registers were asked for on purpose and their value is"
        object_ = "them"
    return (
        f"The analysis test does not apply to {join_headings(waived)}. "
        f"{subject} not a conclusion the video failed to state, so do not "
        f"discard or downgrade {object_} for contributing none. Every other "
        "variation above must still pass it."
    )


def variation_specs(
    chosen: Sequence[str] | None = None,
    selections: dict[str, str] | None = None,
) -> str:
    """The heading list and the register brief that follows it."""

    keys = resolved_variation_keys(chosen, selections)
    total = count_word(len(keys))
    shown = headings_by_key(keys)
    lines = [
        f"### {index}. {shown[key]}" for index, key in enumerate(keys, 1)
    ]
    lines.append("")
    lines.append(
        "Each variation must be plain paste-ready paragraph text directly "
        f"under its heading. All {total} follow the current user direction "
        "and evidence boundary. A heading may change the stance, subject, "
        "evidence strategy, temporal proposition, analytical function, form, "
        "or tone; do not force different dimensions to share one conclusion. "
        f"When the rule gives a single narrow band, all {total} still sit "
        "inside it:"
    )
    lines.append("")
    for index, key in enumerate(keys, 1):
        entry = VARIATION_LIBRARY[key]
        lines.append(f"{index}. {shown[key]} "
                     f"[{key}; dimension={entry.dimension.value}]. "
                     f"{VARIATION_LIBRARY[key].spec}")

    waiver = analysis_waiver(keys)
    if waiver:
        lines.extend(["", waiver])
    return "\n".join(lines)


def reply_variation_specs(
    chosen: Sequence[str] | None = None,
    selections: dict[str, str] | None = None,
) -> str:
    """The reply pipeline's own rendering of the chosen registers.

    Same library as the comment pipeline, different surrounding prose: a
    reply answers a thread, so the brief talks about a challenge rather than
    an angle, and the headings are spaced apart the way this template has
    always spaced them.
    """

    keys = resolved_variation_keys(
        chosen, selections, DEFAULT_REPLY_VARIATIONS
    )
    total = count_word(len(keys))
    shown = headings_by_key(keys)
    lines = [f"Then output exactly these {total} variation sections, in this "
             "order:", ""]
    for index, key in enumerate(keys, 1):
        lines.extend([f"### {index}. {shown[key]}", ""])
    lines.extend([
        "Each finished reply appears as plain paste-ready text directly "
        "under its heading. Nothing else appears under a variation heading.",
        "",
        f"The {total} follow the current user direction and evidence boundary. "
        "A heading may change the stance, subject, evidence strategy, temporal "
        "proposition, analytical function, form, or tone. Do not force "
        "different dimensions to answer with the same point:",
        "",
    ])
    for index, key in enumerate(keys, 1):
        entry = VARIATION_LIBRARY[key]
        lines.append(f"{index}. {shown[key]} "
                     f"[{key}; dimension={entry.dimension.value}]. "
                     f"{entry.spec}")
    waiver = analysis_waiver(keys)
    if waiver:
        lines.extend(["", waiver])
    return "\n".join(lines)


DIAL_CHOICE_LABELS: dict[str, str] = {
    # What an interface shows instead of the stored key. Storage keys never
    # change, so an older settings file keeps working.
    "unset": "As the templates say",
    "as_me": "First person, as me",
    "impersonal": "Impersonal",
    "to_author": "Address the author",
    "to_commenter": "Address the commenter",
    "to_room": "Address the room",
    "none": "None",
    "one": "One qualifier",
    "two": "Up to two",
    "off": "Off",
    "summary": "Summarise the video first",
    "consequence": "Concrete consequence",
    "question": "Question allowed",
    "flat": "Flat statement",
    "sarcasm": "Sarcasm allowed",
    "full": "Full, with repairs",
    "ranking": "Ranking only",
    "synthesis": "Assemble from all",
    "best_single": "Best single, repaired",
    "both": "Both, labelled",
    "claim_only": "The claim, not the person",
    "never": "Nothing at all",
    "uncapped": "No cap",
}


def dial_choice_label(value: str) -> str:
    """What to show for a stored dial value. Falls back to the raw key."""

    return DIAL_CHOICE_LABELS.get(value, value)


class DialDefinition(NamedTuple):
    """One setting that applies to every variation rather than to one.

    ``choices`` maps a stored value to the sentence it puts in the packet. The
    default choice maps to an empty string: choosing it emits nothing, so a
    run left alone produces the prompt it produced before dials existed. That
    is what keeps the option set from costing words it does not earn.
    """

    label: str
    default: str
    choices: dict[str, str]


class DialChoiceClassification(str, Enum):
    """How a selected dial choice can be checked objectively.

    ``REQUIRED`` means the finished output must exhibit the behavior,
    ``FORBIDDEN`` means it must omit the behavior, and ``PERMITTED`` only
    grants latitude. Permitted behavior belongs in the instructions but must
    never be turned into a compliance requirement.
    """

    REQUIRED = "required"
    FORBIDDEN = "forbidden"
    PERMITTED = "permitted"


DIALS: dict[str, DialDefinition] = {
    "person": DialDefinition(
        "Whose voice",
        "unset",
        {
            "unset": "",
            "as_me": "Write in the first person as the commenter. \"I\" is "
                     "allowed and the opinion is owned.",
            "impersonal": "Write impersonally. No first person, no direct "
                          "address, the claim stands on its own.",
            "to_author": "Address the video's author directly as \"you\". "
                         "The comment is written to the person who made it.",
            "to_commenter": "Address the other commenters directly as "
                            "\"you\". The comment answers the section, not "
                            "the video.",
            "to_room": "Address the room. Speak to everybody reading, name "
                       "nobody in particular.",
        },
    ),
    "hedging": DialDefinition(
        "Hedging",
        "one",
        {
            "one": "",
            "none": "Use no explicit qualifier at all. Make a claim the "
                    "evidence carries outright, or make a smaller one.",
            "two": "Up to two explicit qualifiers are allowed where the "
                   "evidence genuinely needs them. Three is still never "
                   "right.",
        },
    ),
    "ending": DialDefinition(
        "How it ends",
        "consequence",
        {
            "consequence": "",
            "question": "A closing question is allowed in any variation, "
                        "not only where a consequence cannot be named.",
            "flat": "End on the claim itself. No closing question and no "
                    "gesture at consequences.",
        },
    ),
    "humor": DialDefinition(
        "Humor",
        "unset",
        {
            "unset": "",
            "none": "No jokes, no wordplay, no comic understatement in any "
                    "variation, including ones whose register invites it.",
            "sarcasm": "Sarcasm is allowed and does not need to be carried "
                       "by understatement, as long as the facts under it "
                       "hold.",
        },
    ),
    "critique": DialDefinition(
        "Critique depth",
        "full",
        {
            "full": "",
            "ranking": "Shorten the Harsh critique to the ranking and one "
                       "sentence per variation. Do not write repaired "
                       "versions.",
            "none": "Omit the Harsh critique section entirely. Judge the "
                    "variations silently and go straight to the Hardened "
                    "final.",
        },
    ),
    "final": DialDefinition(
        "Final assembly",
        "synthesis",
        {
            "synthesis": "",
            "best_single": "Do not assemble the Hardened final from several "
                           "drafts. Take the single best variation, repair "
                           "it, and ship that.",
            "both": "Produce two hardened finals, labelled \"Assembled:\" "
                    "and \"Single best:\", in that order.",
        },
    ),
    "grounding": DialDefinition(
        "Grounding pass",
        "off",
        {
            "off": "",
            "summary": "Before writing any variation, output a section "
                       "headed \"### What the video says\" containing, in "
                       "this order: at most six sentences describing only "
                       "what the video states; then a line \"Who is in it:\" "
                       "listing every person the evidence names, each with "
                       "the role the evidence gives them and the timestamp "
                       "of their earliest mention anywhere in the transcript, "
                       "including a cold open before the video's own "
                       "introduction. Where the evidence does not settle "
                       "somebody's role, which organisation or place they "
                       "belong to, or which of two names a speaker is, say "
                       "so rather than choosing. The "
                       "transcript marks a change of speaker and never says "
                       "who took over, so do not attribute a line to a name "
                       "from its position. No interpretation, no argument, "
                       "no comment drafts anywhere in this section. Every "
                       "later claim about the video or the people in it must "
                       "be traceable to it. If a draft asserts something "
                       "this section does not support, fix the draft rather "
                       "than the section.",
        },
    ),
    "aggression": DialDefinition(
        "Aggression",
        "claim_only",
        {
            "claim_only": "",
            "never": "Attack no one and nothing. Disagree with the claim "
                     "without any dismissive characterisation of whoever "
                     "made it.",
            "uncapped": "The person who made the claim may be criticised "
                        "directly, not only the claim. Insult still has to "
                        "be earned by the evidence.",
        },
    ),
}


# This table deliberately classifies every stored choice, including defaults.
# Structural required/forbidden choices are already asserted by the resolved
# structure, critique, and final checks. ``DIAL_FINAL_CHECK_ASSERTIONS`` below
# adds assertions only where the ordinary checks do not already say it.
DIAL_CHOICE_CLASSIFICATIONS: dict[str, dict[str, DialChoiceClassification]] = {
    "person": {
        "unset": DialChoiceClassification.PERMITTED,
        "as_me": DialChoiceClassification.REQUIRED,
        "impersonal": DialChoiceClassification.FORBIDDEN,
        "to_author": DialChoiceClassification.REQUIRED,
        "to_commenter": DialChoiceClassification.REQUIRED,
        "to_room": DialChoiceClassification.REQUIRED,
    },
    "hedging": {
        "one": DialChoiceClassification.PERMITTED,
        "none": DialChoiceClassification.FORBIDDEN,
        "two": DialChoiceClassification.PERMITTED,
    },
    "ending": {
        "consequence": DialChoiceClassification.REQUIRED,
        "question": DialChoiceClassification.PERMITTED,
        "flat": DialChoiceClassification.REQUIRED,
    },
    "humor": {
        "unset": DialChoiceClassification.PERMITTED,
        "none": DialChoiceClassification.FORBIDDEN,
        "sarcasm": DialChoiceClassification.PERMITTED,
    },
    "critique": {
        "full": DialChoiceClassification.REQUIRED,
        "ranking": DialChoiceClassification.REQUIRED,
        "none": DialChoiceClassification.FORBIDDEN,
    },
    "final": {
        "synthesis": DialChoiceClassification.REQUIRED,
        "best_single": DialChoiceClassification.REQUIRED,
        "both": DialChoiceClassification.REQUIRED,
    },
    "grounding": {
        "off": DialChoiceClassification.PERMITTED,
        "summary": DialChoiceClassification.REQUIRED,
    },
    "aggression": {
        "claim_only": DialChoiceClassification.FORBIDDEN,
        "never": DialChoiceClassification.FORBIDDEN,
        "uncapped": DialChoiceClassification.PERMITTED,
    },
}


def dial_choice_classification(
    dial: str,
    value: str,
) -> DialChoiceClassification:
    """Return the compliance semantics for one stored dial choice."""

    return DIAL_CHOICE_CLASSIFICATIONS[dial][value]


@dataclass(frozen=True)
class ResolvedPromptSpec:
    """The executable comment contract after every selected option wins.

    Templates, headings, checks, metadata, and validation all consume this
    value. Superseded instructions never reach the rendered packet.
    """

    variation_keys: tuple[str, ...]
    headings: tuple[str, ...]
    grounding_contract: str
    critique_contract: str
    final_contract: str
    ending_contract: str
    output_directives: str
    structure_check: str
    critique_check: str
    final_check: str
    option_checks: str


GROUNDING_SUMMARY_CONTRACT = """### What the video says

In at most six sentences, describe only what the video states. Then write a
line beginning "Who is in it:" and list every person named in the transcript,
with the role the evidence gives them and their earliest transcript timestamp.
People named only in comments, replies, metadata, or the
description may be listed without a timestamp; do not invent one. Where the
evidence does not settle a person's role, affiliation, or identity, say so.
Speaker changes are not attribution by themselves.

Do not put interpretation, argument, or comment drafts in this section. Every
later claim about the video or the people in it must be traceable to this
section. Attribution must survive the move into a draft: writing "the speaker
says" here does not license a later variation to present that disputed claim
as established fact. If a draft outruns this section,
fix the draft rather than the section."""

FULL_CRITIQUE_CONTRACT = """Then include:

### Harsh critique

Critique only the {check_count} generated variations as writing outputs
against these rules.

For each variation, first answer:

- Does this add analysis, or does it restate a conclusion already spoken in the
  video?
- What exact new inference does it contribute?
- Which transcript facts support that inference?
- Which part is direct evidence and which part is inference?
- Does the inference require an unstated premise about motive, control,
  investor belief, causation, or responsibility?
- Did the draft strip "the speaker says" or "according to the report" from a
  disputed claim and silently convert it into fact?
- Could the comment survive if the viewer already watched the full video?

Discard any variation whose main value is compression, emphasis, tone, humor,
or clearer wording applied to a point the video already made.

Do not excuse repetition merely because the supplied comment section has not
mentioned the point. The comment's central conclusion must be unstated in the
video unless its named approach is deliberately a summary or other waived
mode.

Compare the variations with one another. If two make substantially the same
inference, call the later one a duplicate and discard or rebuild it around a
different supported conclusion. Different length, tone, imagery, or examples
do not rescue a duplicated inference. Do not approve an inference merely
because the drafts all depend on it.

Then, for each, identify its main writing weakness and whether it should be
repaired or discarded. Check stance, repetition, attribution, qualification,
register, generated phrasing, openings, and closings. Say whether a stranger
would press like and rank all {check_count} from most to least likely to be
liked. Where repair is possible inside the same approach, write it under the
critique labelled "Repaired:". Be adversarial toward the writing, but do not
invent faults."""

RANKING_CRITIQUE_CONTRACT = """Then include:

### Harsh critique

Rank the {check_count} variations from most to least likely to be liked and
give one sentence explaining each placement. Do not write repaired versions."""

ENDING_CONSEQUENCE_CONTRACT = """End on the concrete consequence. Name the
specific thing that happens, who does it, or what it costs. Do not end on a
summary clause, a restatement of the angle, or a vague gesture at effects. A
closing question is allowed only when the specific unanswered thing is
stronger than any consequence you can name."""

ENDING_QUESTION_CONTRACT = """End on a concrete consequence or a specific
unanswered question. A closing question is permitted, but never required."""

ENDING_FLAT_CONTRACT = """End on the narrow claim itself. Do not append a
consequence, prediction, recap, rhetorical question, or gesture toward future
effects. The last sentence must state the claim the evidence directly carries."""

FINAL_COMMON_TESTS = """Before writing the final, apply both tests internally:

- Analysis test: what does this comment conclude that the video did not
  directly tell the viewer, unless its named approach deliberately waives that
  test?
- Like test: would a stranger scrolling this section stop and press like?

A draft that merely repeats the video without a deliberate waiver has failed.
A draft that adds analysis but sounds like an essay has also failed.

- Redundancy test: does each sentence contribute a different fact, inference,
  or consequence? Delete any sentence that restates another.
- Register test: would the wording sound natural beside the supplied comments?
  Replace abstract labels and professional jargon with the concrete point.
- Length test: the final must stay inside the preferred band for this run, not
  merely under the absolute maximum."""


def resolved_variation_keys(
    chosen: Sequence[str] | None = None,
    selections: dict[str, str] | None = None,
    default: Sequence[str] = DEFAULT_VARIATIONS,
) -> tuple[str, ...]:
    """Resolve incompatible register/dial pairs before rendering."""

    keys = list(variation_keys(chosen, default))
    if dial_choice("humor", selections) == "none":
        keys = [
            HUMOR_INCOMPATIBLE_REPLACEMENTS.get(key, key)
            for key in keys
        ]
    if dial_choice("ending", selections) == "flat":
        keys = ["unanswered_gap" if key == "question" else key for key in keys]
    # Substitution can collide with an explicitly selected replacement.
    return tuple(dict.fromkeys(keys))


def _resolved_directives(
    selections: dict[str, str] | None,
) -> str:
    """Non-structural option rules; structural choices render elsewhere."""

    structural = {"critique", "final", "grounding", "ending"}
    lines = []
    for name in DIALS:
        value = dial_choice(name, selections)
        text = DIALS[name].choices[value]
        # humor=none has replacement-aware wording below. Sarcasm is merely
        # permitted, but its directive still has to reach the packet once.
        if text and name not in structural and not (
            name == "humor" and value == "none"
        ):
            lines.append(f"- [{name}={value}] {text}")
    if dial_choice("humor", selections) == "none":
        lines.append(
            "- [humor=none] Use no jokes, sarcasm, wordplay, or comic "
            "understatement. Any humorous register has already been replaced."
        )
    if not lines:
        return ""
    return "\n".join(["", "## Output options", ""] + lines)


def resolve_prompt_spec(
    chosen: Sequence[str] | None = None,
    selections: dict[str, str] | None = None,
) -> ResolvedPromptSpec:
    """Compose one coherent comment prompt specification."""

    keys = resolved_variation_keys(chosen, selections)
    total = count_word(len(keys))
    grounding = (
        GROUNDING_SUMMARY_CONTRACT
        if dial_choice("grounding", selections) == "summary"
        else ""
    )
    critique_mode = dial_choice("critique", selections)
    critique = {
        "full": FULL_CRITIQUE_CONTRACT,
        "ranking": RANKING_CRITIQUE_CONTRACT,
        "none": "",
    }[critique_mode].replace("{check_count}", total)
    ending_mode = dial_choice("ending", selections)
    ending = {
        "consequence": ENDING_CONSEQUENCE_CONTRACT,
        "question": ENDING_QUESTION_CONTRACT,
        "flat": ENDING_FLAT_CONTRACT,
    }[ending_mode]
    final_mode = dial_choice("final", selections)
    critique_reference = {
        "full": "Use the ranking and repairs above.",
        "ranking": "Use the ranking above.",
        "none": "Judge and rank the variations silently.",
    }[critique_mode]
    if final_mode == "synthesis":
        final = f"""Finally include:

### Hardened final

{critique_reference} Build one new comment from the strongest repairable
material in the drafts. It may combine wording, evidence, and rhetorical moves
from more than one variation, but may introduce no unsupported approach.

{FINAL_COMMON_TESTS}

Fix the identified writing flaws, preserve the approach's classified dimension
and user direction, add interpretation rather than recap, and attribute
disputed claims.
{ending}

The Hardened final contains only the finished comment. Nothing follows it."""
    elif final_mode == "best_single":
        final = f"""Finally include:

### Hardened final

{critique_reference} Select the strongest one of the variations and repair
that variation inside its own approach. Do not combine wording, evidence, or
rhetorical moves from any other variation.

{FINAL_COMMON_TESTS}

Fix that draft's writing flaws, preserve its classified approach dimension and
user direction, add interpretation rather than recap, and attribute disputed
claims.
{ending}

The Hardened final contains only the repaired winning comment. Nothing follows
it."""
    else:
        final = f"""Finally include:

### Hardened finals

**Assembled:**
<one finished comment assembled from the strongest repairable material in
multiple drafts>

**Single best:**
<the strongest single variation, repaired without combining wording, evidence,
or rhetorical moves from any other variation>

{critique_reference} Apply the analysis and like tests to both finals.
{ending}

The Single best comment is the final content in the answer. Nothing follows
it."""

    headings = headings_for(keys, selections=selections)
    structure = (
        f"the section What the video says, then the {total} numbered headings"
        if grounding
        else f"the {total} numbered headings"
    )
    if critique_mode != "none":
        structure += ", then Harsh critique"
    structure += (
        ", then Hardened finals with Assembled followed by Single best"
        if final_mode == "both"
        else ", then Hardened final"
    )
    critique_check = {
        "full": (
            f"Critique: judges and ranks all {total} variations and includes "
            "repairs only inside the same approach."
        ),
        "ranking": (
            f"Critique: ranks all {total} variations with one sentence each "
            "and includes no repaired drafts."
        ),
        "none": (
            "Selection: variations are judged and ranked silently; no extra "
            "section appears."
        ),
    }[critique_mode]
    final_check = {
        "synthesis": (
            "Hardened final: one assembled comment built from the strongest "
            "repairable draft material, and it is the last content."
        ),
        "best_single": (
            "Hardened final: one repaired winning variation with no material "
            "from other drafts, and it is the last content."
        ),
        "both": (
            "Hardened finals: Assembled may combine drafts; Single best is a "
            "repaired non-hybrid winner and is the last content."
        ),
    }[final_mode]
    checks = [
        assertion
        for name in DIALS
        if (
            assertion := DIAL_FINAL_CHECK_ASSERTIONS.get(
                (name, dial_choice(name, selections))
            )
        )
    ]
    option_checks = "\n".join(
        f"{index}. {text}" for index, text in enumerate(checks, 9)
    )
    return ResolvedPromptSpec(
        variation_keys=keys,
        headings=headings,
        grounding_contract=grounding,
        critique_contract=critique,
        final_contract=final,
        ending_contract=ending,
        output_directives=_resolved_directives(selections),
        structure_check=structure,
        critique_check=critique_check,
        final_check=final_check,
        option_checks=option_checks,
    )


# Which final-check items each dial setting contradicts, and what the packet
# must say instead. A dial that changes the shape of the answer has to reach
# the final check, because the check is the last thing the model reads and it
# wins every disagreement. Only settings that genuinely contradict an item
# appear here; the rest need no reconciliation.
CHECK_OVERRIDES: dict[tuple[str, str], str] = {
    ("critique", "ranking"): (
        "Items 1 and 7: the Harsh critique is the ranking and one sentence "
        "per variation. Repaired versions are not required and item 7 is "
        "satisfied without them."
    ),
    ("critique", "none"): (
        "Items 1 and 7: no Harsh critique is required and none should be "
        "written. The headings are followed directly by the Hardened final. "
        "Do not add a critique to satisfy item 7."
    ),
    ("grounding", "summary"): (
        "Item 1: a section headed \"What the video says\" comes before the "
        "numbered headings. It is required, it is not a variation, and it "
        "does not count toward the heading list."
    ),
    ("hedging", "none"): (
        "Item 4: a disputed claim is still attributed — say who said it — but "
        "it carries no qualifier. Where the evidence will not support a claim "
        "without one, make the smaller claim it does support rather than "
        "hedging the larger one."
    ),
    ("ending", "flat"): (
        "The Hardened final ends on the claim itself, not on a consequence. "
        "The instruction to end on a concrete consequence does not apply to "
        "this run; naming a consequence and then flattening it is worse than "
        "either."
    ),
    ("final", "best_single"): (
        "Item 8: the Hardened final is the single best variation, repaired. "
        "Do not assemble it from several drafts; reprinting the one that won "
        "is what this run asked for."
    ),
    ("final", "both"): (
        "Items 1 and 8: two hardened finals are required, labelled "
        '"Assembled:" and "Single best:", in that order. They are the last '
        "content in the answer."
    ),
}


# Objectively testable dial semantics that are not already covered by the
# structure, critique, or final assertions. There are intentionally no entries
# for permissive choices such as humor=sarcasm or aggression=uncapped.
DIAL_FINAL_CHECK_ASSERTIONS: dict[tuple[str, str], str] = {
    ("person", "as_me"): (
        "Required — person=as_me: every finished comment uses the commenter's "
        "first-person voice and owns its opinion."
    ),
    ("person", "impersonal"): (
        "Forbidden — person=impersonal: no finished comment uses first person "
        "or direct address."
    ),
    ("person", "to_author"): (
        "Required — person=to_author: every finished comment addresses the "
        "video's author directly as \"you\"."
    ),
    ("person", "to_commenter"): (
        "Required — person=to_commenter: every finished comment addresses the "
        "other commenters directly as \"you\"."
    ),
    ("person", "to_room"): (
        "Required — person=to_room: every finished comment addresses the room "
        "without naming one person in particular."
    ),
    ("hedging", "none"): (
        "Forbidden — hedging=none: no finished comment uses an explicit "
        "qualifier."
    ),
    ("ending", "flat"): (
        "Required — flat ending: the last sentence states the narrow claim; "
        "no consequence, prediction, recap, or question follows."
    ),
    ("humor", "none"): (
        "Forbidden — humor: no joke, sarcasm, wordplay, or comic "
        "understatement appears."
    ),
    ("grounding", "summary"): (
        "Required — grounding: What the video says appears immediately "
        "before variation 1 and invents no timestamp."
    ),
    ("aggression", "never"): (
        "Forbidden — aggression=never: no finished comment attacks a person "
        "or thing, or dismissively characterises whoever made the claim."
    ),
}


def check_option_overrides(selections: dict[str, str] | None = None) -> str:
    """Reconcile the final check with the dials, or return "".

    Without this the packet could contradict itself at the last moment. A run
    with ``critique=none`` printed "Omit the Harsh critique section entirely"
    among its output options and then ended by requiring a Harsh critique in
    two separate checks. The check is read last, so it won, and the option the
    operator selected was silently discarded.

    Stated as amendments rather than by rewriting the items, so the checks
    stay the ones the operator wrote and the reader can see exactly which of
    them this run changed and why.
    """

    amendments = [
        text
        for name in DIALS
        if (text := CHECK_OVERRIDES.get((name, dial_choice(name, selections))))
    ]
    if not amendments:
        return ""
    return "\n".join(
        ["", "", "This run's output options amend the checks above:", ""]
        + [f"- {text}" for text in amendments]
    )


def render_final_check(
    template: str,
    chosen: Sequence[str] | None = None,
    default: Sequence[str] = DEFAULT_VARIATIONS,
    selections: dict[str, str] | None = None,
) -> str:
    """Fill the final check from the same selection as the output contract.

    The check used to be a constant saying "the five headings" and "none is
    primarily a summary". Once registers became selectable that made it the
    last thing the model reads and the wrong thing: a four-register packet
    that had deliberately asked for Summary ended by ordering the model to
    reject one. The two must be rendered from one selection or they drift
    again.
    """

    keys = (
        variation_keys(chosen, default)
        if default == DEFAULT_REPLY_VARIATIONS
        else resolved_variation_keys(chosen, selections, default)
    )
    total = count_word(len(keys))
    shown = headings_by_key(keys)
    waived = [shown[key] for key in keys
              if VARIATION_LIBRARY[key].waives_analysis]
    if waived:
        substance = (
            f"every variation except {join_headings(waived)} contributes "
            f"something the video did not state, and all {total} follow the "
            "user direction and evidence boundary,"
        )
        waiver = (
            f"\n9. Waivers: {join_headings(waived)} may be exactly what the "
            "heading says without contributing a new inference. Do not fail "
            f"{'them' if len(waived) > 1 else 'it'} for that."
        )
    else:
        substance = (
            f"none is primarily a summary, and all {total} follow the user "
            "direction and evidence boundary,"
        )
        waiver = ""
    rendered = (
        template.replace("{check_count}", total)
        .replace("{check_substance}", substance)
        .replace("{check_waiver}", waiver)
    )
    if default == DEFAULT_REPLY_VARIATIONS:
        return rendered.replace(
            "{check_option_overrides}", check_option_overrides(selections)
        )
    spec = resolve_prompt_spec(keys, selections)
    return (
        rendered.replace("{structure_check}", spec.structure_check)
        .replace("{critique_check}", spec.critique_check)
        .replace("{final_check}", spec.final_check)
        .replace("{option_checks}", spec.option_checks)
        .replace("{check_option_overrides}", "")
    )


def parse_registers(text: str) -> tuple[str, ...]:
    """Turn a comma-separated --registers value into library keys.

    Unknown names raise here rather than being dropped. A settings file is
    tolerated because a stale entry must not stop the window opening, but a
    typed argument is a request: silently building a different packet than
    the one asked for is how a run gets trusted when it should not be.
    """

    names = [part.strip() for part in text.split(",") if part.strip()]
    if not names:
        raise ConfigurationError(
            "--registers was given nothing. Omit it for the defaults, or see "
            "--list-registers."
        )
    keys, unknown = [], []
    lowered = {key.lower(): key for key in VARIATION_LIBRARY}
    headings = {
        entry.heading.lower(): key
        for key, entry in VARIATION_LIBRARY.items()
    }
    for name in names:
        found = lowered.get(name.lower()) or headings.get(name.lower())
        if found is None:
            unknown.append(name)
        elif found not in keys:
            keys.append(found)
    if unknown:
        raise ConfigurationError(
            f"Unknown register{'s' if len(unknown) > 1 else ''}: "
            f"{', '.join(unknown)}. Run --list-registers to see the names."
        )
    return tuple(key for key in VARIATION_LIBRARY if key in keys)


def parse_dials(values: Sequence[str]) -> dict[str, str]:
    """Turn repeated --dial name=value arguments into stored dial values."""

    chosen: dict[str, str] = {}
    for raw in values or ():
        name, separator, value = str(raw).partition("=")
        name, value = name.strip(), value.strip()
        if not separator or not name or not value:
            raise ConfigurationError(
                f"--dial wants name=value, not {raw!r}. Run --list-dials to "
                "see the names."
            )
        if name not in DIALS:
            raise ConfigurationError(
                f"Unknown dial: {name}. Run --list-dials to see the names."
            )
        if value not in DIALS[name].choices:
            allowed = ", ".join(DIALS[name].choices)
            raise ConfigurationError(
                f"{name} has no setting called {value}. Choose one of: "
                f"{allowed}."
            )
        chosen[name] = value
    return chosen


def format_register_listing(default: Sequence[str] = DEFAULT_VARIATIONS) -> str:
    """Everything --registers accepts. Without this the CLI is unusable."""

    lines = ["Registers. Pass a comma-separated list to --registers.", ""]
    for key, entry in VARIATION_LIBRARY.items():
        marks = []
        if key in default:
            marks.append("default")
        if entry.waives_analysis:
            marks.append("waives the analysis test")
        suffix = f"  [{'; '.join(marks)}]" if marks else ""
        lines.append(f"  {key:<20} {entry.heading}{suffix}")
    lines.extend([
        "",
        "Selecting none uses the defaults marked above.",
    ])
    return "\n".join(lines)


def format_dial_listing() -> str:
    """Everything --dial accepts, with the default marked."""

    lines = ["Dials. Pass name=value to --dial, once per dial.", ""]
    for name, entry in DIALS.items():
        lines.append(f"  {name}  ({entry.label})")
        for value in entry.choices:
            mark = "  [default]" if value == entry.default else ""
            lines.append(f"      {value}{mark}")
        lines.append("")
    return "\n".join(lines).rstrip()


def default_dials() -> dict[str, str]:
    """Every dial at its default. This is what "reset" writes back.

    Reset has to be an explicit, testable value rather than "clear the
    settings and hope", because the whole option set is only safe if there is
    a way back to the prompt that was in use before it existed.
    """

    return {name: entry.default for name, entry in DIALS.items()}


def default_output_options() -> tuple[tuple[str, ...], dict[str, str]]:
    """The registers and dials that reproduce the pre-options packet."""

    return DEFAULT_VARIATIONS, default_dials()


def dial_choice(dial: str, selections: dict[str, str] | None) -> str:
    """The stored value for one dial, falling back to its default."""

    entry = DIALS[dial]
    value = (selections or {}).get(dial, entry.default)
    return value if value in entry.choices else entry.default


# A dial can also contradict a register, but only when that register was
# actually asked for. "No closing question" and a Question variation cannot
# both be satisfied; neither can "attack no one" and Contemptuous. The dial
# wins — it is the narrower, later choice — and the packet says so instead of
# leaving the reader to notice.
REGISTER_CONFLICTS: dict[tuple[str, str], dict[str, str]] = {
    ("ending", "flat"): {
        "question": "Question is asked for and this run ends flat: ask it as "
                    "the closing sentence and add nothing after it.",
    },
    ("ending", "question"): {
        "flat_claim": "Flat claim forbids a question and this run allows one "
                      "everywhere: Flat claim keeps its own rule and stays a "
                      "statement.",
        "flat_contradiction": "Flat contradiction forbids a question and this "
                              "run allows one everywhere: Flat contradiction "
                              "keeps its own rule.",
        "hostile": "Hostile forbids a question and this run allows one "
                   "everywhere: Hostile keeps its own rule.",
    },
    ("aggression", "never"): {
        "contemptuous": "Contemptuous dismisses the claim as beneath argument "
                        "without characterising who made it.",
        "furious": "Furious is anger at what the evidence shows, never at the "
                   "person who said it.",
        "scorched_earth": "Scorched earth condemns the arrangement, and names "
                          "no individual as its author.",
        "hostile": "Hostile says the room has it wrong without any dismissive "
                   "characterisation of the people in it.",
    },
    ("person", "impersonal"): {
        "personal_anecdote": "Personal anecdote needs a first person and this "
                             "run forbids one: drop the register or drop the "
                             "dial. Written impersonally it is not an "
                             "anecdote.",
    },
}


def register_conflicts(
    chosen: Sequence[str] | None = None,
    selections: dict[str, str] | None = None,
) -> list[str]:
    """Reconciliations for dials that contradict a selected register.

    Empty unless both halves of the conflict are present in this run, so a
    packet never spends words on a clash it does not contain.
    """

    keys = set(variation_keys(chosen))
    lines = []
    for name in DIALS:
        conflicts = REGISTER_CONFLICTS.get((name, dial_choice(name, selections)))
        for key, text in (conflicts or {}).items():
            if key in keys:
                lines.append(text)
    return lines


def output_directives(
    selections: dict[str, str] | None = None,
    chosen: Sequence[str] | None = None,
) -> str:
    """The block appended to the workflow for every non-default dial.

    Returns an empty string when nothing was changed, so the packet is byte
    for byte what it was before any of this existed.
    """

    # Each directive carries the option that produced it. Without the label a
    # returned answer cannot be traced back to the run that asked for it, and
    # the operator reading a packet has no way to tell which of these lines he
    # chose and which are the defaults.
    lines = []
    for name in DIALS:
        value = dial_choice(name, selections)
        text = DIALS[name].choices[value]
        if text:
            lines.append(f"- [{name}={value}] {text}")
    conflicts = register_conflicts(chosen, selections)
    if not lines and not conflicts:
        return ""
    if conflicts:
        lines.append("")
        lines.append("Where an option and a register disagree, the option "
                     "wins and this is how:")
        lines.append("")
        lines.extend(f"- {text}" for text in conflicts)
    return "\n".join(["", "## Output options", ""] + lines)


def instruction_cost(
    chosen: Sequence[str] | None = None,
    selections: dict[str, str] | None = None,
) -> int:
    """Characters the selected options add to the packet's instruction region.

    Measured rather than estimated so the budget guard has a real number to
    compare against.
    """

    return len(variation_specs(chosen)) + len(output_directives(selections))


REQUIRED_OUTPUT_HEADINGS = headings_for()
REQUIRED_REPLY_OUTPUT_HEADINGS = headings_for(default=DEFAULT_REPLY_VARIATIONS)
