"""What the comment section is about, when there is no transcript.

A packet built without a transcript still carries the title, the description
and every comment retrieved. That is a large pile of text with no index, and
the model reading it has to notice on its own that forty of five hundred
comments say the same word. This counts them instead.

**It adds no information.** Every term below already appears in the evidence
region; this is arithmetic over text the reader can check. That is the whole
reason it is allowed into a packet whose design premise is that unverified
claims stay out.

Three rules keep it that way.

**No claim about the video.** There is no transcript. Nothing here says what
was said, only what was written about it underneath.

**Absence is asserted only about the author's own text.** "Raised only in the
comments" means the word does not appear in the title or the description —
both of which are short, and both of which are printed in this packet. The
reverse claim, that something is absent from the comments, is never made: the
comment sample is incomplete by construction and ``render_retrieval_note``
already says so.

**One tokenizer on both sides.** The author text and the comment text go
through ``transcript_words.tokenize``, so the diff compares like with like. A
substring or word-boundary check across differently-normalized text is how
"New York Times" comes to match "watched this 3 times".

Ranking is by how many distinct comments carry a term, not by how often it
occurs. One long rant repeating a word twenty times is one person; twenty
comments using it once are a subject. ``tools/measure_filler.py`` reached the
same conclusion about transcripts for the same reason.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .sanitize import neutralize, truncate
from .transcript_words import tokenize
from .video import as_int

# Bounded so the section cannot displace evidence. It renders only when there
# is no transcript, and in that case allocate() has already reserved
# FLOORS.transcript (20,000) for a transcript that turned out to be one line.
MAXIMUM_CHARACTERS = 6_000

QUESTION_LENGTH = 240
MINIMUM_QUESTION_WORDS = 4

# A question is a run of text ending in '?' that does not cross a sentence
# boundary or a line break.
QUESTION = re.compile(r"[^.!?\n]*\?")


@dataclass(frozen=True)
class Term:
    """One word, and where it was found."""

    word: str
    comments: int          # distinct comments containing it
    uses: int              # total occurrences
    in_author_text: bool   # appears in the title or the description


@dataclass
class CommentSignals:
    """The counts, and enough context to tell whether they mean anything."""

    terms: list[Term] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    scanned: int = 0            # comments and replies counted
    terms_found: int = 0        # before the display cap
    questions_found: int = 0    # before the display cap

    @property
    def empty(self) -> bool:
        return not self.terms and not self.questions


def author_tokens(video: dict[str, Any]) -> set[str]:
    """Every word the channel itself wrote about this video."""

    return set(tokenize(
        f"{video.get('title', '')}\n{video.get('description', '')}"
    ))


def analyse(
    video: dict[str, Any],
    comments: Sequence[dict[str, Any]],
    replies: Sequence[dict[str, Any]] = (),
    stopwords: Iterable[str] = (),
    *,
    terms: int = 25,
    questions: int = 12,
    minimum_length: int = 3,
    minimum_comments: int = 2,
) -> CommentSignals:
    """Count the comment section. Pure; nothing here reaches the network.

    ``minimum_comments`` defaults to 2 because a term one person used is not
    a subject, it is a person. Raising the display cap without raising this
    fills the table with hapax legomena and buries the signal.
    """

    unwanted = {word.lower() for word in stopwords}
    # transcript_words strips apostrophes when tokenizing, so a list entry
    # that kept one can never match. Deriving the stripped form removes the
    # whole class rather than the entries somebody remembered to patch.
    unwanted |= {word.replace("'", "") for word in unwanted}

    authored = author_tokens(video)
    everything = list(comments) + list(replies)

    per_comment: Counter[str] = Counter()   # how many comments carry the word
    uses: Counter[str] = Counter()          # how many times in total
    for item in everything:
        found = [
            token for token in tokenize(item.get("text", ""))
            if len(token) >= minimum_length and token not in unwanted
        ]
        uses.update(found)
        per_comment.update(set(found))

    ranked = [
        Term(word=word, comments=count, uses=uses[word],
             in_author_text=word in authored)
        for word, count in per_comment.items()
        if count >= minimum_comments
    ]
    # Descending by spread, then by total, then alphabetical, so the same
    # comment section always produces the same table.
    ranked.sort(key=lambda term: (-term.comments, -term.uses, term.word))

    asked = _questions(everything)

    return CommentSignals(
        terms=ranked[:terms],
        questions=asked[:questions],
        scanned=len(everything),
        terms_found=len(ranked),
        questions_found=len(asked),
    )


def _questions(items: Sequence[dict[str, Any]]) -> list[str]:
    """Questions the audience asked, most-liked first.

    Deduplicated case-insensitively: "what channel is this?" arrives twenty
    times under a popular video and twenty identical rows say nothing that one
    row does not.
    """

    seen: set[str] = set()
    found: list[tuple[int, int, str]] = []
    for position, item in enumerate(items):
        likes = as_int(item.get("like_count")) or 0
        for raw in QUESTION.findall(item.get("text", "") or ""):
            question = " ".join(raw.split())
            if len(question.split()) < MINIMUM_QUESTION_WORDS:
                continue
            key = question.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append((-likes, position, question))
    found.sort()
    return [question for _, _, question in found]


def render(signals: CommentSignals) -> str:
    """The section as it appears in the packet.

    Untrusted throughout: the questions are comment text, and some of them
    come from comments the packet had no room to print in full. They are
    neutralized and truncated exactly like any other quoted evidence.
    """

    lines = [
        "### What the comment section is about",
        "",
        "No transcript was available, so this is a word count over the comment",
        "text in this packet, not a summary of the video. Nothing here says",
        "what was said in the video. Every term below appears literally in the",
        "comments and can be checked against them.",
        "",
    ]

    if signals.empty:
        lines.append(
            f"_{signals.scanned:,} comments and replies were scanned and "
            "nothing recurred often enough to count. Treat the comment "
            "section as having no shared subject._"
        )
        return "\n".join(lines) + "\n"

    lines.append(
        f"- {signals.scanned:,} comments and replies scanned"
    )
    # The count beside a list must describe that list. A table of 25 rows
    # above the words "41 recurring terms" has broken here before.
    lines.append(
        f"- {signals.terms_found:,} terms recur across two or more of them; "
        f"the {len(signals.terms):,} most widespread are shown"
    )
    lines.append("")

    if signals.terms:
        width = max(len(term.word) for term in signals.terms)
        lines.append("```")
        for term in signals.terms:
            where = ("also in the title or description" if term.in_author_text
                     else "raised only in the comments")
            lines.append(
                f"{term.word.ljust(width)}  {term.comments:>4,} comments  "
                f"{term.uses:>5,} uses   {where}"
            )
        lines.append("```")
        lines.append("")

    if signals.questions:
        lines.extend([
            "#### Questions the audience asked",
            "",
            f"{len(signals.questions):,} of {signals.questions_found:,} "
            "distinct questions, the most-liked first.",
            "",
        ])
        for question in signals.questions:
            text = truncate(neutralize(question), QUESTION_LENGTH,
                            label="question")
            lines.append(f"- {text}")
        lines.append("")

    return truncate("\n".join(lines), MAXIMUM_CHARACTERS, label="comment signals")
