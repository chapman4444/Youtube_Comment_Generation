"""The allocator must ration against measured evidence, not against its caps.

A real Debug build exposed the defect these tests pin down: a 280,000-character
budget produced a 141,162-character packet that had discarded half its
transcript, shortened seven comment bodies and dropped thirty replies. Nothing
was short of room. ``comment_cost`` charged every rendered comment the full
``CAPS.comment_body`` while the median body was 116 characters, so the
allocator computed an evidence requirement twice the budget it actually had and
rationed against that fiction.

The sharpest statement of the bug is
``test_allocation_responds_to_how_much_evidence_there_actually_is``: before the
fix, evidence measuring 9,570 characters and evidence measuring 990,000
characters produced byte-identical allocations. A function whose output cannot
move when its input changes by two orders of magnitude is not measuring
anything.

Both directions are proved. Evidence that fits must survive intact, and
evidence that genuinely does not fit must still shrink through the existing
floors, keep its section coverage, and report the reduction honestly. A fix
that merely stopped reducing would pass the first half and break the second.

Everything is synthetic: no network, no YouTube, and no rendered trial packets.
"""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.domain.errors import PacketTooLargeError
from llm_youtube_comment_generation.domain.packet_builder import (
    PacketEvidence,
    PacketOptions,
    allocate,
    build,
)
from llm_youtube_comment_generation.domain.packets import (
    CAPS,
    FLOORS,
    select_packet_sections,
)
from llm_youtube_comment_generation.domain.section_profile import (
    measure_comment_register,
)
from llm_youtube_comment_generation.domain.statuses import (
    RetrievalOutcome,
    RetrievalStatus,
)
from llm_youtube_comment_generation.infrastructure import prompt_resources

BUDGET = 280_000
INSTRUCTIONS = 30_000

# Shaped like the run that exposed this: a couple of hundred comments whose
# bodies sit far below the cap, and a transcript that fits several times over.
ORDINARY_BODY = "a short reaction to the video, about this long in practice"
OVERSIZED_BODY = "x" * 6_000
TRANSCRIPT = "\n".join(
    f"[00:{minute:02}:00] a line of spoken transcript for this minute"
    for minute in range(800)
)


@pytest.fixture(scope="module")
def templates():
    return {
        "workflow": prompt_resources.load("comment_workflow.md").text,
        "final": prompt_resources.load("comment_final_check.md").text,
    }


def evidence_for(body=ORDINARY_BODY, *, count=200, per_thread=12):
    comments = [
        {
            "comment_id": f"c{index:04}",
            "author": f"@user{index}",
            "author_channel_id": "UC" + str(index).ljust(22, "z")[:22],
            "text": body,
            "like_count": 300 - index,
            "total_reply_count": per_thread,
            "published_at": "2026-07-01T00:00:00Z",
            "updated_at": "2026-07-01T00:00:00Z",
        }
        for index in range(count)
    ]
    replies = [
        {
            "comment_id": f"{parent['comment_id']}.r{index}",
            "parent_comment_id": parent["comment_id"],
            "author": f"@replier{index}",
            "author_channel_id": "UCr" + str(index).ljust(21, "z")[:21],
            "text": body,
            "like_count": 0,
            "published_at": "2026-07-01T00:00:00Z",
            "updated_at": "2026-07-01T00:00:00Z",
        }
        for parent in comments[:25]
        for index in range(per_thread)
    ]
    return PacketEvidence(
        video={
            "video_id": "gC-J7zwYMAM",
            "title": "A video",
            "channel_title": "A channel",
            "description": "a description",
            "comment_count": count,
        },
        comments=comments,
        replies=replies,
        transcript_text=TRANSCRIPT,
        transcript_available=True,
        register=measure_comment_register(comments),
        retrieval=RetrievalOutcome(
            status=RetrievalStatus.COMPLETE,
            retrieved=count,
            reported_total=count,
        ),
    )


def selection_for(evidence):
    return select_packet_sections(
        evidence.comments, evidence.comments, evidence.comments, evidence.replies
    )


def allocation_for(evidence, *, budget=BUDGET, instructions=INSTRUCTIONS):
    return allocate(
        evidence,
        selection_for(evidence),
        PacketOptions(maximum_characters=budget),
        instructions,
    )


def covered(selection):
    return (
        len(selection.most_liked) + len(selection.most_replied)
        + len(selection.relevant) + len(selection.recent)
    )


# -- the allocator must look at the evidence -------------------------------


def test_allocation_responds_to_how_much_evidence_there_actually_is():
    small = allocation_for(evidence_for(ORDINARY_BODY))
    large = allocation_for(evidence_for(OVERSIZED_BODY))

    assert small != large


# -- evidence that fits must survive ---------------------------------------


def test_a_transcript_that_fits_is_kept_whole_and_not_called_reduced():
    evidence = evidence_for()

    allocation = allocation_for(evidence)

    assert allocation.transcript >= len(evidence.transcript_text)
    assert allocation.transcript_reduced is False


def test_bodies_keep_their_caps_while_the_budget_has_room():
    allocation = allocation_for(evidence_for())

    assert allocation.comment_body == CAPS.comment_body
    assert allocation.reply_body == CAPS.reply_body


def test_retrieved_replies_are_kept_when_they_fit():
    evidence = evidence_for()
    selection = selection_for(evidence)

    allocation = allocation_for(evidence)

    assert allocation.replies_per_thread == CAPS.replies_per_thread
    assert allocation.reply_threads == min(
        CAPS.reply_threads, len(selection.threads)
    )


def test_the_assembled_packet_keeps_the_whole_transcript(templates):
    """The end-to-end proof: the allocator can be right in isolation and the
    packet still lose the transcript if assembly rations separately."""

    evidence = evidence_for()

    packet = build(
        evidence,
        selection_for(evidence),
        PacketOptions(maximum_characters=BUDGET),
        workflow_template=templates["workflow"],
        final_check_template=templates["final"],
    )

    assert "transcript middle omitted" not in packet.text
    assert "Transcript: complete" in packet.text
    assert len(packet.text) <= BUDGET


# -- evidence that genuinely cannot fit must still be rationed --------------


def test_oversized_bodies_still_shrink_towards_the_floor():
    allocation = allocation_for(evidence_for(OVERSIZED_BODY))

    assert allocation.comment_body < CAPS.comment_body
    assert allocation.comment_body >= FLOORS.comment_body


def test_a_transcript_without_room_is_cut_to_its_floor_and_reported():
    evidence = evidence_for(OVERSIZED_BODY)

    allocation = allocation_for(evidence)

    assert allocation.transcript >= FLOORS.transcript
    assert allocation.transcript < len(evidence.transcript_text)
    assert allocation.transcript_reduced is True


def test_section_coverage_is_never_traded_away_to_make_room():
    """Body size gives; the number of comments shown does not."""

    roomy = selection_for(evidence_for(ORDINARY_BODY))
    cramped = selection_for(evidence_for(OVERSIZED_BODY))

    assert covered(roomy) == covered(cramped)
    assert covered(cramped) == (
        CAPS.most_liked_comments + CAPS.most_replied_comments
        + CAPS.relevant_comments + CAPS.recent_comments
    )


def test_evidence_that_cannot_fit_even_at_the_floor_is_still_refused():
    """Refusal now depends on the evidence rather than on the count alone.

    The allocator used to reject any budget under MINIMUM_PACKET_CHARACTERS
    because it billed every comment the floor body size whatever the comment
    said. Measuring instead means a small budget really can hold two hundred
    short comments, so this proves the refusal survives where it belongs: bodies
    that do not fit even reduced to the floor, with no replies left to drop.
    That constant still guards the entry points -- application/configuration.py
    and interfaces/gui/options.py reject a sub-minimum budget before assembly
    is ever reached.
    """

    with pytest.raises(PacketTooLargeError):
        allocation_for(
            evidence_for(OVERSIZED_BODY),
            budget=100_000,
            instructions=1_000,
        )


def test_a_small_budget_now_holds_evidence_that_genuinely_fits_in_it():
    """The other half of the same change: short comments are no longer billed
    as though every one of them ran to the body cap."""

    allocation = allocation_for(
        evidence_for(), budget=120_000, instructions=1_000
    )

    assert allocation.comment_body == CAPS.comment_body
    assert allocation.transcript_reduced is False
