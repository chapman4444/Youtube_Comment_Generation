"""What the window shows, decided without a window.

Every rule about which control is enabled, what a button says, and what the
equivalent command line would be lives here, as plain data. Nothing in this
module imports tkinter, so all of it is testable without a display — which
matters because Tk interpreter creation is flaky on the operator's machine
and each test that needs one is another chance to fail for no reason.

The window renders these. It never decides them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from ...domain.workflow import Intent, Phase, WorkflowState

# What each intent's button says. Held here rather than in the window so the
# wording can be tested and so two windows could never disagree about it.
BUTTON_LABELS: dict[Intent, str] = {
    Intent.START: "Start",
    Intent.EVIDENCE_READY: "Continue",
    Intent.COPY_CURRENT_PACKET: "Copy packet",
    Intent.SUBMIT_TRIAGE_ANSWER: "Paste triage answer",
    Intent.SELECT_TARGETS: "Use everyone",
    Intent.NEXT_PERSON: "Next person",
    Intent.SUBMIT_PERSON_ANSWER: "Paste answer",
    Intent.SKIP_PERSON: "Skip this person",
    Intent.RETRY_CURRENT_PERSON: "Try again",
    Intent.CANCEL: "Stop",
    Intent.SAVE: "Save and finish",
    Intent.OPEN_REVIEW: "Open replies",
    Intent.FAIL: "",
}

# Intents the operator never triggers. FAIL is how the application reports
# its own failure; a button for it would be nonsense.
INTERNAL_INTENTS = frozenset({Intent.FAIL, Intent.EVIDENCE_READY})

PHASE_EXPLANATIONS: dict[Phase, str] = {
    Phase.IDLE: "Nothing running. Choose a video and start.",
    Phase.ACQUIRING_EVIDENCE: "Fetching comments. This spends quota.",
    Phase.TRIAGE_PACKET_READY: "Triage packet ready. Copy it, or use everyone.",
    Phase.AWAITING_TRIAGE_ANSWER: "Waiting for the triage answer.",
    Phase.TARGETS_SELECTED: "Ready to work through the queue.",
    Phase.PERSON_PACKET_READY: "Packet ready. Copy it and paste the answer back.",
    Phase.AWAITING_PERSON_ANSWER: "Waiting for this person's answer.",
    Phase.ANSWER_REJECTED: "That paste could not be used. The person is unchanged.",
    Phase.DRAFT_ACCEPTED: "Saved. Move to the next person, or finish.",
    Phase.REVIEW_READY: "Every reply is saved and ready to review.",
    Phase.COMPLETE: "Finished. Nothing has been posted.",
    Phase.CANCELLING: "Stopping. Saving what was accepted.",
    Phase.CANCELLED: "Stopped. What was accepted is saved.",
    Phase.FAILED: "The run failed. Nothing was posted.",
}


@dataclass(frozen=True)
class ActionView:
    """One button."""

    intent: Intent
    label: str
    enabled: bool
    primary: bool = False


@dataclass
class WorkflowView:
    """Everything the window needs in order to draw itself."""

    phase: Phase = Phase.IDLE
    explanation: str = ""
    actions: tuple[ActionView, ...] = ()
    progress: str = ""
    warning: str = ""
    error: str = ""
    person: str = ""
    person_status: str = ""
    person_said: str = ""
    may_close: bool = True
    close_refusal: str = ""
    equivalent_command: str = ""

    @property
    def enabled_actions(self) -> tuple[Intent, ...]:
        return tuple(a.intent for a in self.actions if a.enabled)

    @property
    def primary_action(self) -> Intent | None:
        for action in self.actions:
            if action.primary:
                return action.intent
        return None


# The one action to point the operator at in each phase. Exactly one next
# step is exposed at a time; the legacy window offered several and the
# operator had to work out which one it wanted.
PRIMARY_BY_PHASE: dict[Phase, Intent] = {
    Phase.IDLE: Intent.START,
    Phase.TRIAGE_PACKET_READY: Intent.COPY_CURRENT_PACKET,
    Phase.AWAITING_TRIAGE_ANSWER: Intent.SUBMIT_TRIAGE_ANSWER,
    Phase.TARGETS_SELECTED: Intent.NEXT_PERSON,
    Phase.PERSON_PACKET_READY: Intent.COPY_CURRENT_PACKET,
    Phase.AWAITING_PERSON_ANSWER: Intent.SUBMIT_PERSON_ANSWER,
    Phase.ANSWER_REJECTED: Intent.SUBMIT_PERSON_ANSWER,
    Phase.DRAFT_ACCEPTED: Intent.NEXT_PERSON,
    Phase.REVIEW_READY: Intent.OPEN_REVIEW,
    Phase.COMPLETE: Intent.OPEN_REVIEW,
    Phase.CANCELLED: Intent.OPEN_REVIEW,
    Phase.FAILED: Intent.OPEN_REVIEW,
}


def build(
    state: WorkflowState,
    *,
    person: Any = None,
    accepted: int = 0,
    equivalent_command: str = "",
    labels: dict[Intent, str] | None = None,
    explanations: dict[Phase, str] | None = None,
) -> WorkflowView:
    """Turn workflow state into what the window draws.

    The enabled set comes from ``state.next_allowed_actions`` and nowhere
    else. A window that decided for itself which buttons to enable is how the
    legacy one came to offer actions the runner would then refuse.

    ``labels`` and ``explanations`` override the wording only. The comment
    flow has no queue, so "Next person" and "Skip this person" are the wrong
    words for the same transitions — but they are the same transitions, and
    letting a second flow redefine which are *allowed* would put two owners on
    the state machine, which is the thing this module exists to prevent.
    """

    allowed = set(state.next_allowed_actions)
    primary = PRIMARY_BY_PHASE.get(state.phase)
    if primary not in allowed:
        primary = None

    wording = {**BUTTON_LABELS, **(labels or {})}
    actions = tuple(
        ActionView(
            intent=intent,
            label=wording[intent],
            enabled=intent in allowed,
            primary=intent is primary,
        )
        for intent in Intent
        if intent not in INTERNAL_INTENTS
    )

    progress = ""
    if state.total_targets:
        progress = (f"{state.current_index} of {state.total_targets}, "
                    f"{accepted} saved")

    return WorkflowView(
        phase=state.phase,
        explanation={**PHASE_EXPLANATIONS, **(explanations or {})}.get(
            state.phase, ""),
        actions=actions,
        progress=progress,
        warning=state.last_warning,
        error=state.last_error,
        person=getattr(person, "author", "") if person else "",
        person_status=(person.status.value if person else ""),
        person_said=(
            " ".join(str(person.reply.get("text", "")).split())[:400]
            if person else ""
        ),
        may_close=state.may_close,
        close_refusal=(
            "" if state.may_close else
            "This run is saving accepted replies. Closing now would lose them."
        ),
        equivalent_command=equivalent_command,
    )


def equivalent_command_for(
    video: str,
    *,
    handle: str = "",
    registers: Sequence[str] = (),
    dials: dict[str, str] | None = None,
    guided: bool = True,
) -> str:
    """The command line that would do what the window is about to do.

    Shown so a run is reproducible, reportable, and scriptable. It is also
    the cheapest possible check that the window and the CLI really do build
    the same command: if this string is wrong, the parity is a fiction.
    """

    parts = ["ytcomment", "reply", "guided" if guided else "build", video or "VIDEO"]
    if handle:
        parts += ["--my-handle", handle.lstrip("@")]
    if registers:
        parts += ["--registers", ",".join(registers)]
    for name, value in sorted((dials or {}).items()):
        parts += ["--dial", f"{name}={value}"]
    return " ".join(parts)
