"""The guided workflow state machine.

Every legal transition, every illegal one, and the invariants that each cost
something to learn in the current application.
"""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.domain.workflow import (
    COMMIT_CRITICAL_PHASES,
    NON_ADVANCING,
    TRANSITIONS,
    Intent,
    Phase,
    TransitionRefused,
    WorkerLifecycle,
    WorkflowState,
    accept_answer,
    reject_answer,
    skip,
)


def at(phase: Phase, **kwargs) -> WorkflowState:
    return WorkflowState(phase=phase, **kwargs)


# --------------------------------------------------------------------------
# Every legal transition
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phase, intent, destination",
    [(phase, intent, destination)
     for phase, table in TRANSITIONS.items()
     for intent, destination in table.items()],
    ids=lambda value: value.value if hasattr(value, "value") else str(value),
)
def test_every_declared_transition_is_taken(phase, intent, destination):
    state = at(phase)

    assert state.allows(intent)
    assert state.apply(intent).phase is destination


@pytest.mark.parametrize("phase", list(Phase))
def test_every_phase_appears_in_the_table(phase):
    """A phase missing from the table would silently accept nothing.

    Absence is refusal here, so a phase nobody added transitions for becomes
    a dead end rather than an error, which is much harder to notice.
    """

    assert phase in TRANSITIONS


@pytest.mark.parametrize(
    "phase, intent",
    [(phase, intent)
     for phase in TRANSITIONS
     for intent in Intent
     if intent not in TRANSITIONS[phase]],
    ids=lambda value: value.value if hasattr(value, "value") else str(value),
)
def test_every_undeclared_transition_is_refused(phase, intent):
    """Absence is refusal, and refusal is loud.

    A silently dropped intent looks to the operator exactly like a button
    that did nothing, so he presses it again.
    """

    with pytest.raises(TransitionRefused):
        at(phase).apply(intent)


def test_a_refusal_says_what_is_available_instead():
    with pytest.raises(TransitionRefused) as caught:
        at(Phase.IDLE).apply(Intent.SUBMIT_PERSON_ANSWER)

    message = str(caught.value)
    assert "not available while idle" in message
    assert "start" in message


# --------------------------------------------------------------------------
# The invariants
# --------------------------------------------------------------------------


@pytest.mark.parametrize("phase", [
    Phase.TRIAGE_PACKET_READY,
    Phase.AWAITING_TRIAGE_ANSWER,
    Phase.PERSON_PACKET_READY,
    Phase.AWAITING_PERSON_ANSWER,
    Phase.ANSWER_REJECTED,
])
def test_copying_never_advances_the_workflow(phase):
    """A second copy would otherwise skip a person."""

    state = at(phase)

    assert state.apply(Intent.COPY_CURRENT_PACKET).phase is phase
    assert state.apply(Intent.COPY_CURRENT_PACKET).phase is phase


def test_every_non_advancing_intent_really_does_not_advance():
    """Stated once in NON_ADVANCING, checked against the whole table.

    Adding a read-only action cannot accidentally make it move the workflow.
    """

    for phase, table in TRANSITIONS.items():
        for intent in NON_ADVANCING & set(table):
            assert table[intent] is phase, (
                f"{intent.value} moves {phase.value} to {table[intent].value}"
            )


def test_an_unreadable_answer_never_advances_the_sequence():
    """Rejecting keeps the same person, so the operator can paste again."""

    state = at(Phase.AWAITING_PERSON_ANSWER, current_target_id="alice")

    reject_answer(state, "no Hardened final section was found")

    assert state.phase is Phase.ANSWER_REJECTED
    assert state.current_target_id == "alice"
    assert state.accepted_draft_count == 0
    assert state.last_error


def test_a_rejected_answer_can_be_pasted_again_without_losing_the_person():
    state = at(Phase.AWAITING_PERSON_ANSWER, current_target_id="alice")
    reject_answer(state, "unreadable")

    state.apply(Intent.SUBMIT_PERSON_ANSWER)
    accept_answer(state, "the finished reply")

    assert state.phase is Phase.DRAFT_ACCEPTED
    assert state.current_target_id == "alice"
    assert state.accepted_draft_count == 1


def test_an_accepted_draft_is_counted_exactly_once():
    state = at(Phase.AWAITING_PERSON_ANSWER)

    accept_answer(state, "a reply")

    assert state.accepted_draft_count == 1
    assert state.phase is Phase.DRAFT_ACCEPTED


def test_an_empty_draft_is_never_accepted():
    """Accepting nothing would put an empty reply in the review file."""

    state = at(Phase.AWAITING_PERSON_ANSWER)

    with pytest.raises(ValueError, match="cannot be empty"):
        accept_answer(state, "   ")

    assert state.accepted_draft_count == 0
    assert state.phase is Phase.AWAITING_PERSON_ANSWER


def test_accepting_outside_the_awaiting_phase_is_refused():
    """The count cannot be incremented without the phase moving with it."""

    for phase in (Phase.IDLE, Phase.PERSON_PACKET_READY, Phase.DRAFT_ACCEPTED):
        with pytest.raises(TransitionRefused):
            accept_answer(at(phase), "a reply")


def test_rejecting_outside_the_awaiting_phase_is_refused():
    with pytest.raises(TransitionRefused):
        reject_answer(at(Phase.PERSON_PACKET_READY), "why")


def test_exactly_one_set_of_next_actions_is_exposed():
    state = at(Phase.PERSON_PACKET_READY)

    assert state.next_allowed_actions == tuple(sorted(
        TRANSITIONS[Phase.PERSON_PACKET_READY], key=lambda i: i.value
    ))
    assert Intent.SUBMIT_PERSON_ANSWER in state.next_allowed_actions
    assert Intent.SUBMIT_TRIAGE_ANSWER not in state.next_allowed_actions


def test_the_next_actions_are_stable_across_calls():
    """An interface renders these; an unstable order reorders buttons."""

    state = at(Phase.ANSWER_REJECTED)

    assert state.next_allowed_actions == state.next_allowed_actions


# --------------------------------------------------------------------------
# Cancellation and closing
# --------------------------------------------------------------------------


def test_cancelling_is_recorded_as_requested():
    state = at(Phase.PERSON_PACKET_READY)

    state.apply(Intent.CANCEL)

    assert state.phase is Phase.CANCELLING
    assert state.cancellation_requested is True


def test_cancelling_preserves_the_work_already_accepted():
    """Partial progress is the whole point of saving after every draft."""

    state = at(Phase.DRAFT_ACCEPTED, accepted_draft_count=3)

    state.apply(Intent.CANCEL)
    state.apply(Intent.SAVE)

    assert state.phase is Phase.CANCELLED
    assert state.accepted_draft_count == 3


def test_the_application_cannot_close_while_committing():
    """Losing the process here loses accepted work."""

    state = at(Phase.DRAFT_ACCEPTED, worker=WorkerLifecycle.COMMITTING)

    assert state.commit_critical is True
    assert state.may_close is False


def test_the_application_cannot_close_while_cancelling():
    state = at(Phase.CANCELLING)

    assert state.phase in COMMIT_CRITICAL_PHASES
    assert state.may_close is False


def test_waiting_for_a_human_is_not_commit_critical():
    """A workflow may wait for an answer with no worker at all.

    Collapsing the two is what made the legacy application unable to say
    whether it was safe to close.
    """

    state = at(Phase.AWAITING_PERSON_ANSWER, worker=WorkerLifecycle.IDLE)

    assert state.commit_critical is False
    assert state.may_close is True


def test_a_terminal_phase_is_terminal():
    for phase in (Phase.COMPLETE, Phase.CANCELLED, Phase.FAILED):
        assert phase.terminal
    for phase in (Phase.IDLE, Phase.PERSON_PACKET_READY):
        assert not phase.terminal


def test_a_terminal_phase_only_allows_looking_at_the_result():
    for phase in (Phase.COMPLETE, Phase.CANCELLED, Phase.FAILED):
        assert at(phase).next_allowed_actions == (Intent.OPEN_REVIEW,)


# --------------------------------------------------------------------------
# A whole scripted run
# --------------------------------------------------------------------------


def test_a_complete_multi_person_run_walks_end_to_end():
    state = WorkflowState(total_targets=3)

    state.apply(Intent.START)
    state.apply(Intent.EVIDENCE_READY)
    state.apply(Intent.COPY_CURRENT_PACKET)
    state.apply(Intent.SUBMIT_TRIAGE_ANSWER)
    state.apply(Intent.SELECT_TARGETS)

    for _ in range(3):
        state.apply(Intent.NEXT_PERSON)
        state.apply(Intent.COPY_CURRENT_PACKET)
        state.apply(Intent.SUBMIT_PERSON_ANSWER)
        accept_answer(state, "a finished reply")

    state.apply(Intent.SAVE)
    state.apply(Intent.SAVE)

    assert state.phase is Phase.COMPLETE
    assert state.accepted_draft_count == 3


def test_a_run_survives_a_skip_in_the_middle():
    state = WorkflowState(total_targets=3)
    state.apply(Intent.START)
    state.apply(Intent.EVIDENCE_READY)
    state.apply(Intent.SELECT_TARGETS)

    state.apply(Intent.NEXT_PERSON)
    state.apply(Intent.SUBMIT_PERSON_ANSWER)
    accept_answer(state, "first reply")

    state.apply(Intent.NEXT_PERSON)
    skip(state)

    state.apply(Intent.NEXT_PERSON)
    state.apply(Intent.SUBMIT_PERSON_ANSWER)
    accept_answer(state, "third reply")

    state.apply(Intent.SAVE)

    assert state.phase is Phase.REVIEW_READY
    assert state.accepted_draft_count == 2
    assert state.skipped_count == 1


def test_skipping_every_person_still_finishes():
    state = WorkflowState(total_targets=2)
    state.apply(Intent.START)
    state.apply(Intent.EVIDENCE_READY)
    state.apply(Intent.SELECT_TARGETS)

    for _ in range(2):
        state.apply(Intent.NEXT_PERSON)
        skip(state)

    state.apply(Intent.SAVE)

    assert state.phase is Phase.REVIEW_READY
    assert state.accepted_draft_count == 0
    assert state.skipped_count == 2


def test_a_rejected_answer_mid_run_does_not_lose_the_rest():
    state = WorkflowState(total_targets=2)
    state.apply(Intent.START)
    state.apply(Intent.EVIDENCE_READY)
    state.apply(Intent.SELECT_TARGETS)

    state.apply(Intent.NEXT_PERSON)
    state.apply(Intent.SUBMIT_PERSON_ANSWER)
    reject_answer(state, "that was the packet, not an answer")
    state.apply(Intent.SUBMIT_PERSON_ANSWER)
    accept_answer(state, "the real reply")

    state.apply(Intent.NEXT_PERSON)
    state.apply(Intent.SUBMIT_PERSON_ANSWER)
    accept_answer(state, "second reply")

    assert state.accepted_draft_count == 2


def test_the_history_records_what_actually_happened():
    """For diagnosing a run afterwards without re-deriving it."""

    state = WorkflowState()
    state.apply(Intent.START)
    state.apply(Intent.EVIDENCE_READY)

    assert state.history == [
        (Phase.IDLE, Intent.START, Phase.ACQUIRING_EVIDENCE),
        (Phase.ACQUIRING_EVIDENCE, Intent.EVIDENCE_READY,
         Phase.TRIAGE_PACKET_READY),
    ]


def test_triage_can_be_skipped_entirely():
    """Selecting targets directly is legal; triage is optional."""

    state = WorkflowState()
    state.apply(Intent.START)
    state.apply(Intent.EVIDENCE_READY)
    state.apply(Intent.SELECT_TARGETS)

    assert state.phase is Phase.TARGETS_SELECTED
