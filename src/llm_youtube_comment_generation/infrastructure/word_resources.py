"""The operator's word lists, shipped with the package.

Copied from his `parse_words` project, which is not modified. They are data
rather than code and they are the part worth reusing: `omit_words.txt` took
somebody a long time to assemble and no library ships its equivalent, because
the spoken filler in it — yeah, ok, hey, gonna — is exactly what a written
corpus does not contain.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..domain.errors import ConfigurationError
from ..domain.transcript_words import load_word_list

WORDLISTS = Path(__file__).resolve().parent.parent / "resources" / "wordlists"

# The default filter for a transcript. omit_words.txt is a strict superset of
# custom_stopwords.txt — every one of the 346 spoken-filler words is already
# in it — so loading both would be loading one twice.
#
# spoken_extra.txt is ours: the conversational filler a real transcript put at
# the top of the table that omit_words.txt does not carry. It is a separate
# file so omit_words.txt stays byte identical to the parse_words copy.
TRANSCRIPT_STOPWORDS = ("omit_words.txt", "spoken_extra.txt")


@lru_cache(maxsize=None)
def load(name: str) -> frozenset[str]:
    path = WORDLISTS / name
    if not path.is_file():
        raise ConfigurationError(
            f"No word list called {name}. Available: "
            f"{', '.join(sorted(p.name for p in WORDLISTS.glob('*.txt')))}"
        )
    return frozenset(load_word_list(path.read_text(encoding="utf-8")))


def stopwords(names: tuple[str, ...] = TRANSCRIPT_STOPWORDS) -> frozenset[str]:
    """The union of the named lists."""

    combined: set[str] = set()
    for name in names:
        combined |= load(name)
    return frozenset(combined)


def available() -> list[str]:
    return sorted(path.name for path in WORDLISTS.glob("*.txt"))
