"""The guided workflow state machine.

One authoritative answer to "what happens next". The legacy application
inferred workflow state from scattered booleans, worker references and window
fields, which meant the answer depended on who asked and when. Here the phase
is a single value, transitions are a table, and the interfaces submit intents
rather than setting state.

Three invariants are load-bearing and each cost something to learn:

- **Copying never advances.** The operator copies a packet, pastes it into a
  model, and comes back. If copying advanced the workflow, a second copy
  would skip a person.
- **An unreadable answer never advances.** Rejecting into a state that still
  points at the same person is what lets him paste again. Advancing on a
  failed parse loses the person silently.
- **Packet text is never an answer.** The packet is on the clipboard and the
  answer is asked for on the same clipboard, so a stray copy submits the
  packet to itself — and the packet contains a literal "### Hardened final"
  heading, so extraction happily returns prompt text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Phase(str, Enum):
    IDLE = "idle"
    ACQUIRING_EVIDENCE = "acquiring_evidence"
    TRIAGE_PACKET_READY = "triage_packet_ready"
    AWAITING_TRIAGE_ANSWER = "awaiting_triage_answer"
    TARGETS_SELECTED = "targets_selected"
    PERSON_PACKET_READY = "person_packet_ready"
    AWAITING_PERSON_ANSWER = "awaiting_person_answer"
    ANSWER_REJECTED = "answer_rejected"
    DRAFT_ACCEPTED = "draft_accepted"
    REVIEW_READY = "review_ready"
    COMPLETE = "complete"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in (Phase.COMPLETE, Phase.CANCELLED, Phase.FAILED)


class WorkerLifecycle(str, Enum):
    """Kept separate from the phase on purpose.

    A workflow may be waiting for a human answer while no worker exists at
    all. Collapsing the two is what made the legacy application unable to
    say whether it was safe to close.
    """

    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMMITTING = "committing"
    FINISHED = "finished"


class Intent(str, Enum):
    START = "start"
    EVIDENCE_READY = "evidence_ready"
    COPY_CURRENT_PACKET = "copy_current_packet"
    SUBMIT_TRIAGE_ANSWER = "submit_triage_answer"
    SELECT_TARGETS = "select_targets"
    NEXT_PERSON = "next_person"
    SUBMIT_PERSON_ANSWER = "submit_person_answer"
    SKIP_PERSON = "skip_person"
    RETRY_CURRENT_PERSON = "retry_current_person"
    CANCEL = "cancel"
    SAVE = "save"
    OPEN_REVIEW = "open_review"
    FAIL = "fail"


class TransitionRefused(Exception):
    """An intent that is not legal in the current phase.

    Raised rather than ignored. A silently dropped intent looks to the
    operator exactly like a button that did nothing, and he presses it again.
    """

    def __init__(self, phase: Phase, intent: Intent, allowed) -> None:
        self.phase = phase
        self.intent = intent
        self.allowed = tuple(allowed)
        super().__init__(
            f"{intent.value} is not available while {phase.value}. "
            f"Available: {', '.join(i.value for i in self.allowed) or 'nothing'}."
        )


# Intents that never change the phase. Listed once, here, so that adding a
# read-only action cannot accidentally make it advance the workflow.
NON_ADVANCING = frozenset({Intent.COPY_CURRENT_PACKET, Intent.OPEN_REVIEW})

# The transition table. Absence is refusal: an intent not listed for a phase
# is illegal there, so a new phase starts closed rather than open.
TRANSITIONS: dict[Phase, dict[Intent, Phase]] = {
    Phase.IDLE: {
        Intent.START: Phase.ACQUIRING_EVIDENCE,
        Intent.CANCEL: Phase.CANCELLED,
    },
    Phase.ACQUIRING_EVIDENCE: {
        Intent.EVIDENCE_READY: Phase.TRIAGE_PACKET_READY,
        Intent.CANCEL: Phase.CANCELLING,
        Intent.FAIL: Phase.FAILED,
    },
    Phase.TRIAGE_PACKET_READY: {
        Intent.COPY_CURRENT_PACKET: Phase.TRIAGE_PACKET_READY,
        Intent.SUBMIT_TRIAGE_ANSWER: Phase.AWAITING_TRIAGE_ANSWER,
        Intent.SELECT_TARGETS: Phase.TARGETS_SELECTED,
        Intent.CANCEL: Phase.CANCELLING,
        Intent.FAIL: Phase.FAILED,
    },
    Phase.AWAITING_TRIAGE_ANSWER: {
        Intent.COPY_CURRENT_PACKET: Phase.AWAITING_TRIAGE_ANSWER,
        Intent.SELECT_TARGETS: Phase.TARGETS_SELECTED,
        Intent.SUBMIT_TRIAGE_ANSWER: Phase.AWAITING_TRIAGE_ANSWER,
        Intent.CANCEL: Phase.CANCELLING,
        Intent.FAIL: Phase.FAILED,
    },
    Phase.TARGETS_SELECTED: {
        Intent.NEXT_PERSON: Phase.PERSON_PACKET_READY,
        Intent.SAVE: Phase.REVIEW_READY,
        Intent.CANCEL: Phase.CANCELLING,
        Intent.FAIL: Phase.FAILED,
    },
    Phase.PERSON_PACKET_READY: {
        Intent.COPY_CURRENT_PACKET: Phase.PERSON_PACKET_READY,
        Intent.SUBMIT_PERSON_ANSWER: Phase.AWAITING_PERSON_ANSWER,
        Intent.SKIP_PERSON: Phase.TARGETS_SELECTED,
        Intent.CANCEL: Phase.CANCELLING,
        Intent.FAIL: Phase.FAILED,
    },
    Phase.AWAITING_PERSON_ANSWER: {
        Intent.COPY_CURRENT_PACKET: Phase.AWAITING_PERSON_ANSWER,
        Intent.SUBMIT_PERSON_ANSWER: Phase.AWAITING_PERSON_ANSWER,
        Intent.CANCEL: Phase.CANCELLING,
        Intent.FAIL: Phase.FAILED,
    },
    Phase.ANSWER_REJECTED: {
        Intent.COPY_CURRENT_PACKET: Phase.ANSWER_REJECTED,
        Intent.SUBMIT_PERSON_ANSWER: Phase.AWAITING_PERSON_ANSWER,
        Intent.RETRY_CURRENT_PERSON: Phase.PERSON_PACKET_READY,
        Intent.SKIP_PERSON: Phase.TARGETS_SELECTED,
        Intent.CANCEL: Phase.CANCELLING,
        Intent.FAIL: Phase.FAILED,
    },
    Phase.DRAFT_ACCEPTED: {
        Intent.NEXT_PERSON: Phase.PERSON_PACKET_READY,
        Intent.SAVE: Phase.REVIEW_READY,
        Intent.CANCEL: Phase.CANCELLING,
        Intent.FAIL: Phase.FAILED,
    },
    Phase.REVIEW_READY: {
        Intent.OPEN_REVIEW: Phase.REVIEW_READY,
        Intent.SAVE: Phase.COMPLETE,
        Intent.CANCEL: Phase.CANCELLED,
    },
    Phase.CANCELLING: {
        Intent.SAVE: Phase.CANCELLED,
        Intent.CANCEL: Phase.CANCELLING,
    },
    Phase.COMPLETE: {Intent.OPEN_REVIEW: Phase.COMPLETE},
    Phase.CANCELLED: {Intent.OPEN_REVIEW: Phase.CANCELLED},
    Phase.FAILED: {Intent.OPEN_REVIEW: Phase.FAILED},
}

# Phases in which losing the process would lose accepted work. The
# application must refuse to close while one of these is active.
COMMIT_CRITICAL_PHASES = frozenset({Phase.CANCELLING})


@dataclass
class WorkflowState:
    """One authoritative record of where a guided run is."""

    phase: Phase = Phase.IDLE
    worker: WorkerLifecycle = WorkerLifecycle.IDLE
    current_target_id: str = ""
    current_packet_id: str = ""
    current_index: int = 0
    total_targets: int = 0
    accepted_draft_count: int = 0
    skipped_count: int = 0
    last_warning: str = ""
    last_error: str = ""
    cancellation_requested: bool = False
    history: list[tuple[Phase, Intent, Phase]] = field(default_factory=list)

    @property
    def next_allowed_actions(self) -> tuple[Intent, ...]:
        """Exactly what may be done now, in a stable order.

        The interfaces render this rather than deciding for themselves which
        button to enable. Two implementations of "what is possible" is how
        the legacy window came to offer actions the runner would refuse.
        """

        return tuple(sorted(
            TRANSITIONS.get(self.phase, {}), key=lambda intent: intent.value
        ))

    @property
    def commit_critical(self) -> bool:
        """Whether losing the process now would lose accepted work."""

        return (
            self.worker is WorkerLifecycle.COMMITTING
            or self.phase in COMMIT_CRITICAL_PHASES
        )

    @property
    def may_close(self) -> bool:
        return not self.commit_critical

    def allows(self, intent: Intent) -> bool:
        return intent in TRANSITIONS.get(self.phase, {})

    def apply(self, intent: Intent) -> "WorkflowState":
        """Move to the phase this intent leads to, or refuse.

        Copying and opening the review resolve to the phase they started in,
        so they are recorded but never advance anything.
        """

        table = TRANSITIONS.get(self.phase, {})
        if intent not in table:
            raise TransitionRefused(self.phase, intent, self.next_allowed_actions)

        destination = table[intent]
        if intent in NON_ADVANCING and destination is not self.phase:
            raise AssertionError(
                f"{intent.value} is declared non-advancing but the table "
                f"moves {self.phase.value} to {destination.value}"
            )

        self.history.append((self.phase, intent, destination))
        self.phase = destination
        if intent is Intent.CANCEL:
            self.cancellation_requested = True
        return self


def accept_answer(state: WorkflowState, draft: str) -> WorkflowState:
    """Record an accepted draft and move on.

    Separate from ``apply`` because accepting is the only transition that
    changes counts, and a caller must not be able to increment the accepted
    count without also moving the phase.
    """

    if state.phase is not Phase.AWAITING_PERSON_ANSWER:
        raise TransitionRefused(
            state.phase, Intent.SUBMIT_PERSON_ANSWER, state.next_allowed_actions
        )
    if not draft.strip():
        raise ValueError("an accepted draft cannot be empty")

    state.history.append(
        (state.phase, Intent.SUBMIT_PERSON_ANSWER, Phase.DRAFT_ACCEPTED)
    )
    state.phase = Phase.DRAFT_ACCEPTED
    state.accepted_draft_count += 1
    state.last_error = ""
    return state


def reject_answer(state: WorkflowState, reason: str) -> WorkflowState:
    """Refuse an answer without losing the person it was for.

    The rejected phase still points at the same target, so the operator can
    paste again. Advancing here would drop somebody silently, which is the
    failure this whole state is for.
    """

    if state.phase is not Phase.AWAITING_PERSON_ANSWER:
        raise TransitionRefused(
            state.phase, Intent.SUBMIT_PERSON_ANSWER, state.next_allowed_actions
        )
    state.history.append(
        (state.phase, Intent.SUBMIT_PERSON_ANSWER, Phase.ANSWER_REJECTED)
    )
    state.phase = Phase.ANSWER_REJECTED
    state.last_error = reason
    return state


def skip(state: WorkflowState) -> WorkflowState:
    state.apply(Intent.SKIP_PERSON)
    state.skipped_count += 1
    state.current_target_id = ""
    return state
