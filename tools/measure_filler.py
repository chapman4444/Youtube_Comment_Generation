"""Decide which words are filler by measuring, not by opinion.

`spoken_extra.txt` started as a judgement call: I read one frequency table and
wrote down the words that looked like noise. That is exactly how a stopword
list ends up deleting "people" from a video about how police treat people.

The measurable definition: filler is a word that appears at a similar rate in
every video regardless of subject. A topic word spikes in the videos about
that topic and is absent from the rest. So the signal is document frequency —
in how many of the corpus's videos does the word appear at all — combined with
how evenly its rate is spread.

    python tools/measure_filler.py --corpus <dir> [--corpus <dir>] [--min-df 0.9]

Prints three lists: words in spoken_extra.txt the corpus does not justify,
words the corpus says are filler that no list carries, and the words removed
for being topical, with the evidence for or against each. Nothing is written;
the operator's lists are his.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from llm_youtube_comment_generation.domain.transcript_words import (  # noqa: E402
    strip_markup,
    tokenize,
)
from llm_youtube_comment_generation.infrastructure import word_resources  # noqa: E402

VIDEO_ID = re.compile(r"(?:youtube_(?:replies_)?)?([A-Za-z0-9_-]{11})(?:_\d|$)")


def find_transcripts(roots: list[Path]) -> dict[str, Path]:
    """One transcript per video, the largest copy of each.

    Several directories hold the same video from different runs, and a
    duplicate would count that video's vocabulary twice and make its topic
    words look like filler.
    """

    found: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in list(root.rglob("transcript_timestamped.txt")) + \
                list(root.rglob("transcript_plain.txt")):
            match = VIDEO_ID.search(path.parent.name)
            key = match.group(1) if match else path.parent.name
            if key not in found or path.stat().st_size > found[key].stat().st_size:
                found[key] = path
    return found


def measure(
    paths: dict[str, Path], minimum_tokens: int,
) -> tuple[Counter, dict[str, float], int]:
    """Document frequency, and each word's peak share of any one video.

    Transcripts below ``minimum_tokens`` are skipped. A 200-word clip does not
    contain "think" for reasons of length rather than topic, and counting it
    drags every common word below the threshold.
    """

    document_frequency: Counter = Counter()
    rates: dict[str, list[float]] = {}
    counted = 0

    for path in paths.values():
        tokens = tokenize(strip_markup(path.read_text(encoding="utf-8")))
        if len(tokens) < minimum_tokens:
            continue
        counted += 1
        counts = Counter(tokens)
        for word, count in counts.items():
            document_frequency[word] += 1
            rates.setdefault(word, []).append(count / len(tokens))

    return document_frequency, rates, counted


def spikiness(word_rates: list[float]) -> float:
    """How much the word's busiest video outweighs its typical one.

    Document frequency alone cannot tell filler from a topic word when the
    corpus is about one topic: on sixteen videos covering the same story,
    "ben" and "money" appear in fourteen apiece and look exactly like "one".

    A filler word is used at roughly the same rate everywhere, so its peak is
    close to its median. A topic word is concentrated in the videos about that
    topic, so its peak towers over its median even when it appears everywhere.
    """

    if not word_rates:
        return 0.0
    ordered = sorted(word_rates)
    middle = len(ordered) // 2
    median = (ordered[middle] if len(ordered) % 2
              else (ordered[middle - 1] + ordered[middle]) / 2)
    return max(ordered) / median if median else float("inf")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", action="append", required=True, type=Path)
    parser.add_argument("--min-df", type=float, default=0.9,
                        help="share of videos a word must appear in to count "
                             "as filler")
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--min-tokens", type=int, default=1000,
                        help="skip transcripts shorter than this")
    arguments = parser.parse_args()

    paths = find_transcripts(arguments.corpus)
    document_frequency, rates, videos = measure(paths, arguments.min_tokens)
    if videos < 5:
        print(f"Only {videos} transcripts long enough. Document frequency "
              "over so few videos says nothing; this needs a corpus.")
        return 2
    threshold = arguments.min_df * videos
    print(f"{videos} videos, {len(document_frequency):,} distinct words. "
          f"Filler threshold: appears in {threshold:.0f} of {videos}.\n")

    extra = word_resources.load("spoken_extra.txt")
    carried = set(word_resources.load("omit_words.txt") | extra)
    # The matcher derives the apostrophe-stripped form of every entry, so
    # "thats" is already covered by "that's". Without this the report keeps
    # recommending words the filter already removes.
    carried |= {word.replace("'", "") for word in carried}

    print("=== in spoken_extra.txt, but the corpus does not call it filler ===")
    unjustified = sorted(
        (word for word in extra
         if document_frequency.get(word, 0) < threshold),
        key=lambda w: -document_frequency.get(w, 0),
    )
    for word in unjustified[:arguments.top]:
        print(f"  {word:<12} in {document_frequency.get(word, 0):>2}/{videos} videos")
    print(f"  ({len(unjustified)} of {len(extra)} unjustified)\n")

    print("=== everywhere, and no list carries it ===")
    print("    spike is peak rate over median rate: near 1 means evenly")
    print("    spread, high means concentrated in a few videos.\n")
    missing = sorted(
        (word for word, count in document_frequency.items()
         if count >= threshold and word not in carried and len(word) >= 3),
        key=lambda w: spikiness(rates[w]),
    )
    for word in missing[:arguments.top]:
        spike = spikiness(rates[word])
        verdict = "filler" if spike <= 2.5 else "topic-bound"
        print(f"  {word:<12} in {document_frequency[word]:>2}/{videos}, "
              f"spike {spike:>5.1f}x  -> {verdict}")
    print(f"  ({len(missing)} candidates)\n")

    print("=== words removed for being topical: was that right? ===")
    for word in ("people", "real", "right", "part", "one", "time", "way",
                 "whole", "great", "huge", "little", "good"):
        count = document_frequency.get(word, 0)
        spike = spikiness(rates.get(word, []))
        everywhere = count >= threshold
        verdict = ("filler by evidence" if everywhere and spike <= 2.5
                   else "topic-bound")
        print(f"  {word:<8} in {count:>2}/{videos}, spike {spike:>5.1f}x"
              f"  -> {verdict}")

    print("\n=== sanity: known topic words should read as topic-bound ===")
    for word in ("ben", "money", "police", "lego", "legos", "criminal"):
        if word in rates:
            print(f"  {word:<8} in {document_frequency[word]:>2}/{videos}, "
                  f"spike {spikiness(rates[word]):>5.1f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
