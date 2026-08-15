"""Everything the window does, tested without a window.

One test per guided intent, plus the close-while-committing refusal. None of
this needs a display.
"""

from __future__ import annotations

import pytest

from fakes import FakeArtifactStore, FakeClipboard, FakeEventSink
from llm_youtube_comment_generation.application.guided_session import (
    REVIEW_FILENAME,
    GuidedSession,
)
from llm_youtube_comment_generation.domain.candidates import (
    build_reply_candidates,
)
from llm_youtube_comment_generation.domain.threads import OwnerThread
from llm_youtube_comment_generation.domain.workflow import (
    Intent,
    Phase,
    WorkerLifecycle,
    WorkflowState,
)
from llm_youtube_comment_generation.infrastructure import prompt_resources
from llm_youtube_comment_generation.interfaces.gui import view_models
from llm_youtube_comment_generation.interfaces.gui.controllers import (
    GuidedController,
)

OWNER = "UC" + "o" * 22


def message(cid, author, text, when, *, channel=None, likes=0):
    return {
        "comment_id": cid, "author": author,
        "author_channel_id": channel or ("UC" + author.lstrip("@").ljust(22, "z"))[:24],
        "text": text, "like_count": likes,
        "published_at": when, "updated_at": when,
    }


def answer(controller, text="the finished reply"):
    """A well-formed reply sheet for whatever packet is in front of us."""

    parts = ["# Copy/Paste Replies", "", "## Direct replies to your comment",
             ""]
    for target in controller.session.current_targets:
        parts.extend([
            f"**Post beneath comment ID:** {target.comment_id}",
            "",
            "```text",
            text,
            "```",
            "",
        ])
    return "\n".join(parts)


@pytest.fixture
def controller():
    replies = [
        message("r1", "@alice", "actually you are wrong", "2026-07-02T00:00:00Z",
                likes=9),
        message("r2", "@bob", "a separate question", "2026-07-02T01:00:00Z"),
    ]
    thread = OwnerThread(
        comment=message("mine", "@owner", "my comment", "2026-07-01T00:00:00Z",
                        channel=OWNER),
        replies=replies,
    )
    session = GuidedSession(
        targets=build_reply_candidates(OWNER, "@owner", replies, "mine"),
        threads={"mine": thread},
        owner_channel_id=OWNER,
        video={"video_id": "gC-J7zwYMAM", "title": "A video"},
        templates={
            "reply_workflow.md": prompt_resources.load("reply_workflow.md").text,
            "reply_final_check.md":
                prompt_resources.load("reply_final_check.md").text,
        },
        artifacts=FakeArtifactStore(),
        clipboard=FakeClipboard(),
        events=FakeEventSink(),
    )
    return GuidedController(
        session=session,
        equivalent_command=view_models.equivalent_command_for(
            "gC-J7zwYMAM", handle="@owner"
        ),
    )


# --------------------------------------------------------------------------
# The view
# --------------------------------------------------------------------------


def test_only_the_allowed_actions_are_enabled():
    view = view_models.build(WorkflowState(phase=Phase.PERSON_PACKET_READY))

    assert Intent.SUBMIT_PERSON_ANSWER in view.enabled_actions
    assert Intent.SKIP_PERSON in view.enabled_actions
    assert Intent.SUBMIT_TRIAGE_ANSWER not in view.enabled_actions
    assert Intent.START not in view.enabled_actions


def test_exactly_one_action_is_the_next_step():
    """The legacy window offered several and left the operator to guess."""

    for phase in (Phase.IDLE, Phase.PERSON_PACKET_READY,
                  Phase.AWAITING_PERSON_ANSWER, Phase.DRAFT_ACCEPTED):
        view = view_models.build(WorkflowState(phase=phase))
        primaries = [a for a in view.actions if a.primary]
        assert len(primaries) == 1, phase
        assert primaries[0].enabled


def test_the_primary_action_is_never_a_disabled_one():
    for phase in Phase:
        view = view_models.build(WorkflowState(phase=phase))
        primary = view.primary_action
        if primary is not None:
            assert primary in view.enabled_actions, phase


def test_every_phase_explains_itself():
    for phase in Phase:
        assert view_models.build(WorkflowState(phase=phase)).explanation


def test_internal_intents_are_never_offered_as_buttons():
    """FAIL is how the application reports its own failure. A button for it
    would be nonsense."""

    view = view_models.build(WorkflowState(phase=Phase.IDLE))

    assert Intent.FAIL not in {a.intent for a in view.actions}


def test_progress_counts_people_and_saved_drafts():
    state = WorkflowState(phase=Phase.DRAFT_ACCEPTED, total_targets=5,
                          current_index=2)

    assert view_models.build(state, accepted=2).progress == "2 of 5, 2 saved"


def test_the_equivalent_command_is_shown():
    command = view_models.equivalent_command_for(
        "gC-J7zwYMAM", handle="@owner",
        registers=("hostile", "summary"), dials={"person": "as_me"},
    )

    assert command == (
        "ytcomment reply guided gC-J7zwYMAM --my-handle owner "
        "--registers hostile,summary --dial person=as_me"
    )


# --------------------------------------------------------------------------
# One test per guided intent
# --------------------------------------------------------------------------


def test_start_moves_the_run_to_the_queue(controller):
    controller.submit(Intent.START)

    assert controller.session.state.phase is Phase.TARGETS_SELECTED


def test_next_person_builds_that_persons_packet(controller):
    controller.submit(Intent.START)
    view = controller.submit(Intent.NEXT_PERSON)

    assert controller.session.current is not None
    assert view.person == controller.session.current.author
    assert view.person_said


def test_copy_puts_the_packet_on_the_clipboard_and_does_not_advance(controller):
    controller.submit(Intent.START)
    controller.submit(Intent.NEXT_PERSON)
    person = controller.session.current

    controller.submit(Intent.COPY_CURRENT_PACKET)
    controller.submit(Intent.COPY_CURRENT_PACKET)

    assert controller.session.clipboard.read() == controller.session.current_packet
    assert controller.session.current is person
    assert controller.session.state.phase is Phase.PERSON_PACKET_READY


def test_submitting_an_answer_accepts_and_saves_it(controller):
    controller.submit(Intent.START)
    controller.submit(Intent.NEXT_PERSON)

    controller.submit(Intent.SUBMIT_PERSON_ANSWER,
                      answer(controller, "a real reply"))

    assert controller.session.state.phase is Phase.DRAFT_ACCEPTED
    assert "a real reply" in controller.session.artifacts.read(REVIEW_FILENAME)


def test_submitting_reads_the_clipboard_when_no_text_is_given(controller):
    """The window passes nothing; the answer comes through the port."""

    controller.submit(Intent.START)
    controller.submit(Intent.NEXT_PERSON)
    controller.session.clipboard.write(answer(controller, "from the clipboard"))

    controller.submit(Intent.SUBMIT_PERSON_ANSWER)

    # One sheet, both targets in the thread: two drafts accepted.
    assert len(controller.session.accepted) == 2
    assert controller.session.accepted[0].draft == "from the clipboard"


def test_submitting_the_packet_itself_is_refused_and_keeps_the_person(controller):
    controller.submit(Intent.START)
    controller.submit(Intent.NEXT_PERSON)
    person = controller.session.current
    packet = controller.session.current_packet

    view = controller.submit(Intent.SUBMIT_PERSON_ANSWER, packet)

    assert view.phase is Phase.ANSWER_REJECTED
    assert controller.session.current is person
    assert controller.session.accepted == []
    assert view.error


def test_skip_moves_on_without_recording_a_draft(controller):
    controller.submit(Intent.START)
    controller.submit(Intent.NEXT_PERSON)

    controller.submit(Intent.SKIP_PERSON)

    assert controller.session.skipped
    assert controller.session.accepted == []


def test_cancel_stops_and_keeps_what_was_accepted(controller):
    controller.submit(Intent.START)
    controller.submit(Intent.NEXT_PERSON)
    controller.submit(Intent.SUBMIT_PERSON_ANSWER, answer(controller, "kept"))

    controller.submit(Intent.CANCEL)

    assert controller.session.state.phase is Phase.CANCELLED
    assert "kept" in controller.session.artifacts.read(REVIEW_FILENAME)


def test_save_finishes_the_run(controller):
    controller.submit(Intent.START)
    controller.submit(Intent.NEXT_PERSON)
    controller.submit(Intent.SUBMIT_PERSON_ANSWER, answer(controller))

    controller.submit(Intent.SAVE)

    assert controller.session.state.phase is Phase.COMPLETE


def test_open_review_never_advances_the_run(controller):
    controller.submit(Intent.START)
    controller.submit(Intent.NEXT_PERSON)
    controller.submit(Intent.SUBMIT_PERSON_ANSWER, answer(controller))
    controller.submit(Intent.SAVE)
    phase = controller.session.state.phase

    controller.submit(Intent.OPEN_REVIEW)

    assert controller.session.state.phase is phase


# --------------------------------------------------------------------------
# Refusals and closing
# --------------------------------------------------------------------------


def test_an_intent_that_is_not_available_is_reported_not_swallowed(controller):
    """A button that appears to do nothing is one the operator presses again."""

    controller.submit(Intent.SKIP_PERSON)

    assert controller.last_refusal
    assert "not available while idle" in controller.last_refusal


def test_a_successful_intent_clears_the_previous_refusal(controller):
    controller.submit(Intent.SKIP_PERSON)
    assert controller.last_refusal

    controller.submit(Intent.START)

    assert controller.last_refusal == ""


def test_the_window_may_not_close_while_accepted_work_is_being_written(controller):
    controller.session.state.worker = WorkerLifecycle.COMMITTING

    assert controller.may_close is False
    assert "would lose them" in controller.close_refusal


def test_the_window_may_close_while_merely_waiting_for_a_human(controller):
    controller.submit(Intent.START)
    controller.submit(Intent.NEXT_PERSON)

    assert controller.may_close is True
    assert controller.close_refusal == ""
