"""Keyword frequencies from a transcript, once the filler is gone.

Adapted from the operator's `parse_words` project: the emoji range, the
punctuation strip and the `[a-z]+` tokenizer are `count_keywords2.py`, and the
stopword-filtering shape is `build_keyword_list.py`.

Two things from those modules were deliberately dropped.

NLTK is gone. `build_keyword_list.py` imports `word_tokenize` and never calls
it — the tokenizing is already a regular expression — so the only thing NLTK
supplied was `stopwords.words("english")`, and the operator's own
`omit_words.txt` is a superset of that plus the spoken filler. Keeping it would
have meant a dependency, a corpus download, and a test suite that reaches the
network to get one list of words we already have.

The target-word list is gone too. `count_keywords2.py` counts only words that
appear in a supplied list, which is the right shape for auditing a known
vocabulary and the wrong one for a transcript: the interesting word in a video
is the one nobody predicted. This counts everything the stopwords do not
remove.
"""

from __future__ import annotations

import re
import string
from collections import Counter
from typing import Iterable, NamedTuple, Sequence

# From count_keywords2.py, unchanged. Transcripts rarely carry emoji, but the
# same tokenizer runs over comment text, which is nothing but emoji.
EMOJI = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002500-\U00002BEF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001f926-\U0001f937"
    "‍♀-♂☀-⭕⏏⏩⌚〰️"
    "]+",
    flags=re.UNICODE,
)

# Our own transcripts, not the parse_words corpus: "[00:01:09]" per line and
# ">>" at every change of speaker. Counting "00" as a word would put it top.
#
# Everything bracketed goes, not only the timestamps. Auto-captioning writes
# "[music]", "[laughter]", "[snorts]" and "[ __ ]" for a bleep, and a real
# transcript put music at ninth place and laughter at thirty-ninth — nobody
# said either word. Captions do not otherwise use square brackets.
BRACKETED = re.compile(r"\[[^\]]*\]")
SPEAKER_MARKER = re.compile(r">>+")


class WordCount(NamedTuple):
    word: str
    count: int


def load_word_list(text: str) -> set[str]:
    """One word per line, '#' for comments, lower-cased.

    Blank lines and comments are dropped rather than becoming words, which is
    what the original loader did by accident: it kept everything truthy.
    """

    words = set()
    for line in (text or "").splitlines():
        word = line.strip()
        if word and not word.startswith("#"):
            words.add(word.lower())
    return words


def strip_markup(text: str) -> str:
    """Remove what the transcript format adds, before anything is counted."""

    without = BRACKETED.sub(" ", text or "")
    return SPEAKER_MARKER.sub(" ", without)


def tokenize(text: str) -> list[str]:
    """Lower-cased alphabetic tokens, emoji and punctuation removed."""

    stripped = EMOJI.sub("", text or "")
    stripped = stripped.translate(str.maketrans("", "", string.punctuation))
    return re.findall(r"[a-z]+", stripped.lower())


def keyword_frequencies(
    text: str,
    stopwords: Iterable[str] = (),
    *,
    minimum_length: int = 3,
    minimum_count: int = 1,
) -> list[WordCount]:
    """Every word the stopwords did not remove, most frequent first.

    ``minimum_length`` exists because a transcript is speech: "a", "im" and
    "ok" survive any stopword list you can write, and none of them is a
    keyword. Ties are broken alphabetically so the same transcript always
    produces the same table.
    """

    # The tokenizer strips punctuation, so "that's" arrives as "thats" and can
    # never match a list entry that kept its apostrophe. Twenty of the
    # stripped forms had been added to the list by hand and twenty-nine had
    # not, which is why "thats" was the most frequent keyword in a real
    # transcript. Deriving them removes the whole class.
    #
    # It also merges "she'll" into "shell" and "I'll" into "ill". The
    # tokenizer already made those identical; this only decides that the
    # collision is filtered rather than counted.
    counts = _counted(
        tokenize(strip_markup(text)), stopwords, minimum_length=minimum_length
    )
    return [
        WordCount(word, count)
        for word, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if count >= minimum_count
    ]


def _counted(
    tokens: Sequence[str], stopwords: Iterable[str], *, minimum_length: int,
) -> Counter:
    """The counting rule, in one place, over tokens somebody else produced."""

    unwanted = {word.lower() for word in stopwords}
    unwanted |= {word.replace("'", "") for word in unwanted}
    return Counter(
        token for token in tokens
        if len(token) >= minimum_length and token not in unwanted
    )


def render_table(
    rows: Sequence[WordCount], *, total_tokens: int = 0, removed: int = 0,
    distinct: int | None = None,
) -> str:
    """The frequency table, and what it took to get there.

    The counts before and after filtering are printed together on purpose. A
    table of a hundred words says nothing about whether the stopword list did
    its job; "4,812 tokens, 3,109 removed as filler" does.
    """

    if not rows:
        return ("No keywords survived filtering. Either the transcript is "
                "empty or every word in it is on the stopword list.")

    width = max(len(row.word) for row in rows)
    lines = [f"{row.word.ljust(width)}  {row.count:>6,}" for row in rows]

    if total_tokens:
        # ``distinct`` is the whole result, not the rows printed. Counting the
        # printed rows made a --top 15 run report "15 distinct keywords" three
        # lines above "Showing 15 of 436".
        share = 100 * removed / total_tokens
        lines.extend([
            "",
            f"{total_tokens:,} tokens, {removed:,} removed as filler "
            f"({share:.0f}%), "
            f"{len(rows) if distinct is None else distinct:,} distinct "
            "keywords",
        ])
    return "\n".join(lines)


def summarise(
    text: str,
    stopwords: Iterable[str] = (),
    *,
    minimum_length: int = 3,
    minimum_count: int = 1,
) -> tuple[list[WordCount], int, int]:
    """Rows, tokens seen, tokens removed — reconciling with each other.

    ``minimum_count`` is applied here rather than by the caller. When the CLI
    filtered the rows itself, the removed figure had been computed before that
    filter ran, so a --min-count 5 run printed "1,805 removed" beside a table
    whose counts summed to nothing like the remainder. Every token this
    function does not return in a row is counted as removed, whichever rule
    removed it.
    """

    tokens = tokenize(strip_markup(text))
    counts = _counted(tokens, stopwords, minimum_length=minimum_length)
    rows = [
        WordCount(word, count)
        for word, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if count >= minimum_count
    ]
    kept = sum(row.count for row in rows)
    return rows, len(tokens), len(tokens) - kept
