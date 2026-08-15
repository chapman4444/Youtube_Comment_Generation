"""The reply path, and what the clipboard is offering at each point.

The old window drew four numbered rows, two copy buttons, a status line, a
"what this person said" box, three more buttons and a manual-controls panel,
all at once. It was taller than a 1080p screen. This is the same path with one
step in front of you and the rest as a rail beside it.

Nothing here creates a Tk interpreter.
"""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.interfaces.gui.sequence import (
    Holding,
    ReplySequence,
    Step,
    read_clipboard,
)

ANSWER = (
    "# Copy/Paste Replies\n\n"
    "**Post beneath comment ID:** AAA.111\n\n"
    "```text\nThe reply I would send.\n```\n"
)
PACKET = (
    "## BEGIN UNTRUSTED SOURCE MATERIAL\nstuff\n"
    "### Hardened final\nwrite one here\n"
)


def sequence(**kwargs) -> ReplySequence:
    return ReplySequence(people=("@alice", "@bob"), **kwargs)


# -- the rail --------------------------------------------------------------


def test_the_whole_path_is_always_visible():
    """That is the point of a rail: you can see where this ends."""

    rail = sequence().view().rail

    assert [entry.label for entry in rail] == [
        "Build", "Triage", "People", "Finish"]


def test_the_rail_says_where_you_are_and_where_you_have_been():
    running = sequence(step=Step.PEOPLE)

    rail = {entry.step: entry for entry in running.view().rail}

    assert rail[Step.BUILD].done and not rail[Step.BUILD].current
    assert rail[Step.PEOPLE].current and not rail[Step.PEOPLE].done
    assert not rail[Step.FINISH].done


def test_the_markers_are_ascii():
    """A missing glyph draws as a hollow box in a Tk label on Windows."""

    for entry in sequence(step=Step.TRIAGE).view().rail:
        entry.marker.encode("ascii")


# -- nothing advances on its own -------------------------------------------


def test_an_answer_on_the_clipboard_is_offered_never_taken():
    """He asked for auto-advance gone. Watching stays -- it is the best part
    of the window -- so it reports and offers, and he presses."""

    running = sequence(step=Step.PEOPLE)

    view = running.view(clipboard=ANSWER)

    assert view.offer.offered
    assert view.primary_enabled
    # Looking did not move anything.
    assert running.step is Step.PEOPLE


def test_the_step_only_moves_when_something_moves_it():
    running = sequence(step=Step.TRIAGE)

    for _ in range(3):
        running.view(clipboard=ANSWER)

    assert running.step is Step.TRIAGE
    running.advance_to(Step.PEOPLE)
    assert running.step is Step.PEOPLE


# -- what the clipboard is holding -----------------------------------------


def test_our_own_packet_is_recognised_before_it_is_read_as_an_answer():
    """A packet contains a literal "### Hardened final" heading, so
    extraction would hand it back as an answer to itself. This is the same
    order the guided session applies."""

    offer = read_clipboard(PACKET, step=Step.TRIAGE, packet=PACKET)

    assert offer.holding is Holding.OUR_PACKET
    assert not offer.offered


def test_a_sheet_is_recognised_by_shape_not_validated_here():
    """The session owns validation against the packet's target ids; this
    only decides whether to offer."""

    offer = read_clipboard(ANSWER, step=Step.PEOPLE)

    assert offer.holding is Holding.ANSWER
    assert offer.offered


def test_the_untouched_clipboard_is_kept_for_whoever_acts_on_it():
    """Extracting here and submitting the result once meant the session
    parsed a second time, from text already consumed -- two implementations
    of one rule, and they disagreed. The sheet must survive intact for the
    session to parse."""

    offer = read_clipboard(ANSWER, step=Step.PEOPLE)

    # Surrounding whitespace goes; nothing that carries meaning does. The
    # id lines are what the session parses, so they have to survive.
    assert offer.raw == ANSWER.strip()
    assert "Post beneath comment ID" in offer.raw


def test_a_triage_answer_is_a_list_of_handles_not_a_hardened_final():
    """The two steps want different shapes. Classifying every answer the same
    way left the chip calling a perfectly good triage answer "something
    else", and the queue could never be narrowed."""

    offer = read_clipboard(
        "@alice | 1 | worth answering\n@bob | 2 | maybe\n", step=Step.TRIAGE
    )

    assert offer.holding is Holding.TRIAGE_ANSWER
    assert offer.offered


def test_the_chip_counts_the_people_the_triage_answer_named():
    one = read_clipboard("@alice | 1 | yes\n", step=Step.TRIAGE)
    two = read_clipboard("@alice | 1 | yes\n@bob | 2 | yes\n", step=Step.TRIAGE)

    assert "1 person chosen" in one.label
    assert "2 people chosen" in two.label


def test_a_comment_answer_is_still_recognised():
    """A comment answer carries a Hardened final, not Post-beneath lines.
    The batch change dropped this branch and the chip called a perfectly
    good comment answer "something else"."""

    answer = "Reasoning.\n\n### Hardened final\nThe comment I would post.\n"
    offer = read_clipboard(answer, step=Step.PEOPLE)

    assert offer.holding is Holding.ANSWER
    assert offer.offered
    assert offer.raw == answer.strip()


def test_a_reply_sheet_is_not_a_triage_answer():
    """Even at the triage step, and even though a sheet's own headings can
    carry @handles: the sheet shape wins."""

    offer = read_clipboard(ANSWER, step=Step.TRIAGE)

    assert offer.holding is Holding.ANSWER
    assert not offer.offered


def test_a_list_of_handles_is_not_an_answer_for_one_person():
    offer = read_clipboard("@alice | 1 | yes\n", step=Step.PEOPLE)

    assert offer.holding is Holding.OTHER
    assert not offer.offered


def test_triage_is_skippable_because_everyone_is_a_valid_answer():
    """"Work through everyone" answers "which of these are worth answering",
    and should not need a model run to say."""

    assert sequence(step=Step.TRIAGE).view().can_skip


def test_a_video_link_is_only_useful_on_the_first_step():
    on_build = read_clipboard("https://youtu.be/gC-J7zwYMAM", step=Step.BUILD)
    on_people = read_clipboard("https://youtu.be/gC-J7zwYMAM", step=Step.PEOPLE)

    assert on_build.offered
    assert on_people.holding is Holding.VIDEO
    assert not on_people.offered


def test_an_answer_arriving_at_the_wrong_moment_says_so():
    offer = read_clipboard(ANSWER, step=Step.BUILD)

    assert offer.holding is Holding.ANSWER
    assert not offer.usable
    assert "not waiting for one" in offer.label


def test_an_empty_clipboard_is_not_an_error():
    assert read_clipboard("   ", step=Step.TRIAGE).holding is Holding.NOTHING


def test_anything_else_is_named_rather_than_guessed_at():
    offer = read_clipboard("a screenshot caption", step=Step.TRIAGE)

    assert offer.holding is Holding.OTHER
    assert not offer.offered


def test_the_chip_always_says_something():
    """It is the loudest thing in the top bar; blank would be worse than
    useless."""

    for text in ("", ANSWER, PACKET, "https://youtu.be/gC-J7zwYMAM", "junk"):
        assert read_clipboard(text, step=Step.TRIAGE, packet=PACKET).label


# -- what each step offers -------------------------------------------------


def test_the_primary_action_is_dead_until_the_clipboard_can_feed_it():
    waiting = sequence(step=Step.PEOPLE)

    assert not waiting.view(clipboard="junk").primary_enabled
    assert waiting.view(clipboard=ANSWER).primary_enabled


def test_building_disables_the_button_that_starts_a_build():
    assert not sequence().view(building=True).primary_enabled
    assert "Scanning" in sequence().view(building=True).detail


def test_each_step_names_its_own_copy_button():
    assert sequence(step=Step.TRIAGE).view().copy_label == "Copy triage template"
    assert sequence(step=Step.PEOPLE).view().copy_label == \
        "Copy this person's packet"


def test_there_is_nothing_to_copy_on_the_last_step():
    assert not sequence(step=Step.FINISH).view().copy_enabled


def test_the_counts_describe_the_queue_they_sit_beside():
    """A count printed beside a list must describe that list. This project has
    broken that three times."""

    running = sequence(step=Step.PEOPLE, index=1, accepted=1)

    assert running.view().progress == "2 of 2, 1 saved"


def test_an_empty_queue_says_so_rather_than_counting_to_zero():
    empty = ReplySequence(step=Step.PEOPLE, people=())

    assert empty.view().progress == "nobody is waiting"


# -- moving through people -------------------------------------------------


def test_the_last_person_leads_to_the_finish():
    running = sequence(step=Step.PEOPLE, index=1)

    running.next_person()

    assert running.step is Step.FINISH


def test_an_earlier_person_leads_to_the_next_one():
    running = sequence(step=Step.PEOPLE, index=0)

    running.next_person()

    assert running.index == 1 and running.step is Step.PEOPLE
    assert running.view().person == "@bob"


def test_skipping_is_only_offered_where_there_is_something_to_skip():
    """Triage and a person are both skippable; there is nothing to skip
    before a scan has found anybody, or after the last one."""

    assert sequence(step=Step.TRIAGE).view().can_skip
    assert sequence(step=Step.PEOPLE).view().can_skip
    assert not sequence(step=Step.BUILD).view().can_skip
    assert not sequence(step=Step.FINISH).view().can_skip
    assert not ReplySequence(step=Step.PEOPLE, people=()).view().can_skip


def test_going_back_is_offered_everywhere_except_the_start():
    assert not sequence().view().can_go_back
    for step in (Step.TRIAGE, Step.PEOPLE, Step.FINISH):
        assert sequence(step=step).view().can_go_back
