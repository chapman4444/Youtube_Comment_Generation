"""The window's brain, with no window in it.

Submits intents to the guided session and turns the result into a view. No
tkinter import, so the whole of the GUI's behaviour can be tested without a
display.

The controller may not set workflow state. It submits an intent and asks what
happened — which is what stops the window becoming a second owner of the
state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...application.guided_session import GuidedSession
from ...domain.statuses import OperationStatus
from ...domain.workflow import Intent, Phase, TransitionRefused
from . import view_models


@dataclass
class GuidedController:
    """Drives one guided session on behalf of an interface."""

    session: GuidedSession
    equivalent_command: str = ""
    last_refusal: str = ""

    def view(self) -> view_models.WorkflowView:
        return view_models.build(
            self.session.state,
            person=self.session.current,
            accepted=len(self.session.accepted),
            equivalent_command=self.equivalent_command,
        )

    def submit(self, intent: Intent, text: str = "") -> view_models.WorkflowView:
        """Perform one intent, or record why it was refused.

        A refused intent is reported, never swallowed. A button that appears
        to do nothing is one the operator presses again.
        """

        self.last_refusal = ""
        if not self.session.state.allows(intent) and intent not in (
            Intent.SUBMIT_PERSON_ANSWER,
        ):
            self.last_refusal = str(TransitionRefused(
                self.session.state.phase, intent,
                self.session.state.next_allowed_actions,
            ))
            return self.view()

        try:
            self._perform(intent, text)
        except TransitionRefused as refusal:
            self.last_refusal = str(refusal)
        return self.view()

    def _perform(self, intent: Intent, text: str) -> None:
        if intent is Intent.START:
            self.session.start()
        elif intent is Intent.NEXT_PERSON:
            self.session.next_person()
        elif intent is Intent.COPY_CURRENT_PACKET:
            self.session.copy_packet()
        elif intent is Intent.SUBMIT_PERSON_ANSWER:
            self.session.submit(text or self._from_clipboard())
        elif intent is Intent.SKIP_PERSON:
            self.session.skip_person()
        elif intent is Intent.CANCEL:
            self.session.cancel()
        elif intent is Intent.SAVE:
            self.session.finish()
        elif intent is Intent.OPEN_REVIEW:
            self.session.state.apply(Intent.OPEN_REVIEW)
        else:
            self.session.state.apply(intent)

    def _from_clipboard(self) -> str:
        """Read the answer through the port, never through Tk.

        Tk's own clipboard is unreliable mid-run and, more importantly,
        reaching for it here would put an untestable dependency in the middle
        of the one path that decides what gets posted.
        """

        clipboard = self.session.clipboard
        return clipboard.read() if clipboard is not None else ""

    @property
    def may_close(self) -> bool:
        return self.session.state.may_close

    @property
    def close_refusal(self) -> str:
        return self.view().close_refusal
