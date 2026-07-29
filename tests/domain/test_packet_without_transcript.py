"""A packet built with no transcript still has to be worth reading.

Before this, the no-transcript packet was the metadata, a one-line apology and
several hundred unindexed comments. The comment section is the only account of
the video that exists in that case, so it gets counted.
"""

from __future__ import annotations

from llm_youtube_comment_generation.domain.packet_builder import (
    PacketEvidence,
    PacketOptions,
    build,
)
from llm_youtube_comment_generation.domain.packets import select_packet_sections
from llm_youtube_comment_generation.domain.sanitize import SOURCE_BOUNDARY_OPEN
from llm_youtube_comment_generation.infrastructure import prompt_resources

SECTION = "### What the comment section is about"

# The operator's real templates, like every other packet test. A stub would
# pass while the shipped packet failed its own heading contract.
WORKFLOW = prompt_resources.load("comment_workflow.md").text
FINAL_CHECK = prompt_resources.load("comment_final_check.md").text

VIDEO = {
    "video_id": "PbzXXcApttw",
    "title": "Reacting to the Keizer press conference",
    "description": "My reaction.",
}


def comments(count=8):
    return [
        {"comment_id": f"c{n}", "text": "bodycam footage please keizer",
         "like_count": n, "author": "someone", "total_reply_count": 0}
        for n in range(count)
    ]


def evidence(*, transcript: str = "", stopwords=frozenset({"the", "and"})):
    items = comments()
    return PacketEvidence(
        video=VIDEO,
        comments=items,
        replies=[],
        transcript_text=transcript,
        transcript_available=bool(transcript),
        stopwords=stopwords,
    ), select_packet_sections(items, items, items, [])


def assemble(**kwargs):
    ev, selection = evidence(**kwargs)
    return build(
        ev, selection,
        PacketOptions(allow_no_transcript=True),
        workflow_template=WORKFLOW,
        final_check_template=FINAL_CHECK,
    )


def test_a_packet_without_a_transcript_counts_the_comment_section():
    packet = assemble()

    assert SECTION in packet.text
    assert "bodycam" in packet.text


def test_a_packet_with_a_transcript_does_not():
    """With the words themselves in hand, a frequency table is noise."""

    packet = assemble(transcript="[00:00:00] he actually said this")

    assert SECTION not in packet.text


def test_the_count_lands_inside_the_evidence_boundary():
    """It is derived from comment text, so it is evidence, not instruction."""

    packet = assemble()

    assert SECTION in packet.evidence
    assert SECTION not in packet.instructions
    assert packet.text.index(SOURCE_BOUNDARY_OPEN) < packet.text.index(SECTION)


def test_it_still_says_it_has_no_transcript():
    """The count must not read as a substitute for having heard the video."""

    packet = assemble()

    assert "No transcript was available for this video" in packet.text
    assert "not a summary of the video" in packet.text


def test_no_stopwords_still_builds_a_packet():
    """The domain default is an empty set, so a caller that forgets to pass
    the word lists must degrade rather than fail."""

    packet = assemble(stopwords=frozenset())

    assert SECTION in packet.text
