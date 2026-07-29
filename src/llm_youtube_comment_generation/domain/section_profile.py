"""What this comment section actually looks like, measured rather than assumed.

The hardcoded 80-140 word band the packet used to state was roughly six times
too long for every comment section ever measured. On one video the section
median was 14 words and the most-liked comments ran 9, while every generated
variation landed between 85 and 119 because the prompt told it to. The script
already counts the sample, so it states the real numbers instead of a guess.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .errors import ConfigurationError
from .video import as_int

STOP_WORDS = frozenset("""
a about above after again against all also am an and any are aren as at be
because been before being below between both but by can could couldn d did
didn do does doesn doing don down during each few for from further had hadn
has hasn have haven having he her here hers herself him himself his how i if
in into is isn it its itself just ll m ma me might more most must my myself
need no nor not now o of off on once only or other our ours ourselves out
over own re s same shan she should shouldn so some such t than that the their
theirs them themselves then there these they this those through to too under
until up ve very was wasn we were weren what when where which while who whom
why will with won would wouldn y you your yours yourself yourselves
""".split())

EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿←-⇿️⬀-⯿]"
)
DIRECT_ADDRESS_PATTERN = re.compile(r"(?i)\b(you|your|you're|youre|u)\b")


def tokenize(text: str) -> list[str]:
    return [
        token.casefold()
        for token in re.findall(
            r"[^\W\d_]+(?:['’-][^\W\d_]+)*", text, flags=re.UNICODE
        )
        if len(token) >= 3
    ]


def keyword_counts(text: str, maximum: int = 20) -> list[dict[str, Any]]:
    counts = Counter(
        token for token in tokenize(text) if token not in STOP_WORDS
    )
    return [
        {"term": term, "count": count}
        for term, count in counts.most_common(maximum)
    ]


def percentile(values: Sequence[int], fraction: float) -> int:
    """Nearest-rank percentile. Small samples make interpolation pointless."""

    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[index]


@dataclass
class CommentRegister:
    """The measured shape of one video's comment section.

    Every generated comment is calibrated against these numbers. A fixed word
    band cannot work: observed medians across real videos range from about 8
    words on a fast-moving drama channel to about 21 on a tutorial channel.

    This holds measurements only. The legacy version also carried a render()
    method that produced the packet's markdown; rendering is not a domain
    concern and moves to the packet builder.
    """

    sample_size: int = 0
    median_words: int = 0
    p75_words: int = 0
    p90_words: int = 0
    top_liked_median_words: int = 0
    under_10_words: float = 0.0
    under_40_words: float = 0.0
    no_terminal_punctuation: float = 0.0
    emoji: float = 0.0
    direct_address: float = 0.0
    multi_paragraph: float = 0.0
    ends_with_question: float = 0.0
    em_dash: float = 0.0
    semicolon: float = 0.0


def measure_comment_register(
    comments: Sequence[dict[str, Any]],
    replies: Sequence[dict[str, Any]] = (),
) -> CommentRegister:
    """Measure the length distribution and style markers of a comment sample."""

    records = [
        record
        for record in list(comments) + list(replies)
        if str(record.get("text", "")).strip()
    ]
    if not records:
        return CommentRegister()

    bodies = [str(record.get("text", "")).strip() for record in records]
    words = [len(body.split()) for body in bodies]
    total = len(bodies)

    def share(predicate: Callable[[str], bool]) -> float:
        return sum(1 for body in bodies if predicate(body)) / total

    top_liked = sorted(
        records,
        key=lambda record: as_int(record.get("like_count")) or 0,
        reverse=True,
    )[:25]
    top_words = [len(str(record.get("text", "")).split()) for record in top_liked]

    return CommentRegister(
        sample_size=total,
        median_words=percentile(words, 0.50),
        p75_words=percentile(words, 0.75),
        p90_words=percentile(words, 0.90),
        top_liked_median_words=percentile(top_words, 0.50),
        under_10_words=sum(1 for count in words if count <= 10) / total,
        under_40_words=sum(1 for count in words if count < 40) / total,
        no_terminal_punctuation=share(lambda b: b.rstrip()[-1:] not in ".!?"),
        emoji=share(lambda b: EMOJI_PATTERN.search(b) is not None),
        direct_address=share(lambda b: DIRECT_ADDRESS_PATTERN.search(b) is not None),
        multi_paragraph=share(lambda b: b.count("\n") >= 2),
        ends_with_question=share(lambda b: b.rstrip().endswith("?")),
        em_dash=share(lambda b: "—" in b),
        semicolon=share(lambda b: ";" in b),
    )


DEFAULT_LENGTH_RULE = (
    "Preferred length is 80-140 words for a standard video and 45-100 words "
    "for a\nshort clip or simple contradiction. Never exceed 160 words unless "
    "necessary."
)

LENGTH_PRESETS: dict[str, tuple[int, int]] = {
    "short": (5, 20),
    "medium": (20, 50),
    "long": (50, 100),
}
LENGTH_CHOICES = ("auto", "short", "medium", "long")


def parse_length(value: str) -> tuple[int, int] | None:
    """Read a length setting. None means "match this video's comment section".

    Accepts a preset name, an explicit "min-max" word range, or a single
    number treated as the upper bound.
    """

    text = str(value or "").strip().lower()
    if not text or text in ("auto", "match", "measured"):
        return None
    if text in LENGTH_PRESETS:
        return LENGTH_PRESETS[text]

    match = re.fullmatch(r"(\d+)\s*[-to ]+\s*(\d+)", text)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            low, high = high, low
        return max(1, low), max(low + 1, high)

    if text.isdigit():
        high = max(2, int(text))
        return max(1, high // 3), high

    raise ConfigurationError(
        f"Unrecognised length: {value!r}. Use auto, short, medium, long, "
        "a range like 20-60, or a single number."
    )


def length_rule_for(
    register: CommentRegister | None,
    scale: float = 1.0,
    explicit: tuple[int, int] | None = None,
) -> str:
    """Write the packet's length rule from the measured comment section.

    Falls back to the original wording when nothing was measured.
    """

    if explicit is not None:
        low, high = explicit
        ceiling = max(high + 10, round(high * 1.3))
        measured = ""
        if register is not None and register.sample_size:
            measured = (
                f" For reference, this video's own comment section runs "
                f"{register.median_words} words at the median and "
                f"{register.top_liked_median_words} for its most-liked comments."
            )
        # An explicit band still has to warn about the dead zone, or setting
        # a length in the options quietly discards the one finding that most
        # affects whether a comment is ever seen.
        warning = (
            "\n\nFavour the short end of that band. Length is not what earns "
            "a comment its likes,\nso do not pad toward the upper figure."
        )
        return (
            f"Preferred length is {low}-{high} words, set deliberately for this "
            f"run.\nNever exceed {ceiling} words.{measured}{warning}"
        )

    if register is None or not register.sample_size:
        return DEFAULT_LENGTH_RULE

    # Band runs from the section median to its 90th percentile. An earlier
    # version anchored on the top-liked median and the 75th percentile, which
    # was accurate to what wins but left too little room to make an argument.
    # scale widens or narrows the whole band for callers who want more space.
    # One video is one video. The earlier version of this stated a hard dead
    # zone from a difference of two comments (2 of 331 versus 17 of 788), with
    # overlapping confidence intervals, no second video, and no control for
    # comment age or position. That is a direction, not a boundary, so it is
    # phrased as one. The reliable part is the section's own distribution,
    # which is measured here directly.
    short = max(6, min(20, round(register.top_liked_median_words * scale)))
    ceiling = max(short + 20, round(register.p90_words * scale * 1.4))
    return (
        f"Aim for about {short} words. That is roughly what the most-liked "
        f"comments in this\nsection run, and its median comment is "
        f"{register.median_words} words.\n\n"
        f"Go longer only when the argument genuinely needs the room, and never "
        f"past {ceiling}\nwords. Length is not what earns a comment its likes, "
        f"so do not pad toward a target.\nA longer comment has to justify every "
        f"extra sentence."
    )
