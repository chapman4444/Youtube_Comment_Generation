"""One comment packet, worked through in a window.

The window has only ever driven the reply queue, which needs a video the
operator commented on where somebody answered and he has not replied yet. The
comment flow — the one he actually runs every day — had no window at all, and
saying "the comment flow doesn't use it" was true and useless.

This is the same shape as `GuidedSession` with the queue taken out. There is
one packet, not a list of people, so the sequence is: the packet is ready, copy
it, paste the answer back, it is saved. The same state machine, the same
refusals, the same extraction, and drafts saved the moment they are accepted
rather than at the end.

**The packet is built before the window opens.** The window does no network
work — that is the rule that keeps it free of threading and cancellation — so
the CLI builds the packet and hands the finished text over.

**A comment draft is saved exactly like a reply draft.** Same filename shape
beside the run, same immediate write. An interrupted run has to survive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.extraction import extract_hardened_final, looks_like_packet_text
from ..domain.statuses import OperationResult, OperationStatus
from ..domain.workflow import (
    Intent,
    Phase,
    WorkerLifecycle,
    WorkflowState,
    accept_answer,
    reject_answer,
)
from ..ports.events import EventKind, ProgressEvent

DRAFT_FILENAME = "comment_drafts.md"


@dataclass
class AcceptedComment:
    """One draft the operator accepted, and what it was written against."""

    draft: str
    video_id: str = ""
    video_title: str = ""
    registers: tuple[str, ...] = ()


@dataclass
class CommentSession:
    """Drives one comment packet from ready to saved."""

    packet_text: str
    video: dict[str, Any] = field(default_factory=dict)
    registers: tuple[str, ...] = ()
    packet_path: str = ""
    artifacts: Any = None
    clipboard: Any = None
    events: Any = None

    state: WorkflowState = field(default_factory=WorkflowState)
    accepted: list[AcceptedComment] = field(default_factory=list)

    def start(self) -> WorkflowState:
        """Move to "the packet is ready", which is where this begins.

        There is nothing to acquire: the CLI already spent the requests and
        built the packet. The evidence phases are passed through rather than
        pretended at, because a window that showed "Fetching comments" while
        nothing was fetched would be lying about where the quota went.
        """

        self.state.apply(Intent.START)
        self.state.apply(Intent.EVIDENCE_READY)
        self.state.apply(Intent.SELECT_TARGETS)
        self.state.total_targets = 1
        self.state.apply(Intent.NEXT_PERSON)
        self.state.current_packet_id = str(self.video.get("video_id", ""))
        self._emit(EventKind.STEP, "comment",
                   f"packet ready, {len(self.packet_text):,} characters")
        return self.state

    def copy_packet(self) -> str:
        """Put the packet on the clipboard. Never advances the workflow.

        Copying is not progress. The legacy application treated it as though
        it were, so a stray click moved the run on without an answer.
        """

        self.state.apply(Intent.COPY_CURRENT_PACKET)
        if self.clipboard is not None:
            self.clipboard.write(self.packet_text)
        return self.packet_text

    def submit(self, text: str) -> OperationResult:
        """Take the model's answer, or refuse it and keep the packet.

        Refusal order matters and is the same as the reply flow's: packet
        detection runs before extraction, because the packet contains its own
        literal "### Hardened final" heading and extraction would happily hand
        back a line of prompt text as though it were a comment to post.
        """

        result = OperationResult()
        self.state.apply(Intent.SUBMIT_PERSON_ANSWER)

        if looks_like_packet_text(text, self.packet_text):
            reject_answer(self.state, "that is the packet, not an answer to it")
            result.status = OperationStatus.REFUSED
            result.value = self.state
            self._emit(EventKind.WARNING, "comment",
                       "that paste was the packet itself")
            return result

        draft = extract_hardened_final(text)
        if not draft:
            reject_answer(
                self.state,
                "no '### Hardened final' section was found, so there is "
                "nothing safe to take as the comment",
            )
            result.status = OperationStatus.REFUSED
            result.value = self.state
            self._emit(EventKind.WARNING, "comment", "no Hardened final found")
            return result

        accept_answer(self.state, draft)
        self.accepted.append(AcceptedComment(
            draft=draft,
            video_id=str(self.video.get("video_id", "")),
            video_title=str(self.video.get("title", "")),
            registers=tuple(self.registers),
        ))
        # Immediately, not at the end. This is the line that makes an
        # interrupted run survivable.
        self._save()

        result.value = self.state
        self._emit(EventKind.STEP, "comment", "draft accepted and saved")
        return result

    def skip_person(self) -> WorkflowState:
        """There is nobody to skip; this ends the run without a draft."""

        from ..domain.workflow import skip

        skip(self.state)
        self._save()
        return self.state

    def cancel(self) -> WorkflowState:
        self.state.apply(Intent.CANCEL)
        self.state.worker = WorkerLifecycle.COMMITTING
        self._save()
        self.state.worker = WorkerLifecycle.FINISHED
        self.state.apply(Intent.SAVE)
        self._emit(EventKind.CANCELLED, "comment",
                   f"stopped with {len(self.accepted)} drafts saved")
        return self.state

    def finish(self) -> WorkflowState:
        self.state.worker = WorkerLifecycle.COMMITTING
        self._save()
        self.state.worker = WorkerLifecycle.FINISHED
        if self.state.phase is not Phase.REVIEW_READY:
            self.state.apply(Intent.SAVE)
        self.state.apply(Intent.SAVE)
        self._emit(EventKind.FINISHED, "comment",
                   f"{len(self.accepted)} drafts ready to review")
        return self.state

    # -- internals -------------------------------------------------------

    def _save(self) -> None:
        if self.artifacts is None or not self.accepted:
            return
        self.artifacts.stage(DRAFT_FILENAME, render_drafts(self))
        self.artifacts.commit()

    def _emit(self, kind: EventKind, step: str, message: str) -> None:
        if self.events is not None:
            self.events.emit(ProgressEvent(kind, step=step, message=message))


def render_drafts(session: CommentSession) -> str:
    """The drafts, ready to read and paste. Nothing is ever posted."""

    video = session.video
    lines = [
        f"# Comment drafts: {video.get('title', '') or video.get('video_id', '')}",
        "",
        f"- video: {video.get('video_id', '')}",
        f"- registers: {', '.join(session.registers) or 'the default five'}",
        f"- packet: {session.packet_path or 'not written to disk'}",
        "",
        "Nothing here has been posted. Copy what you want and post it "
        "yourself.",
        "",
    ]
    if not session.accepted:
        lines.append("_No draft was accepted._")
        return "\n".join(lines) + "\n"

    for index, item in enumerate(session.accepted, 1):
        lines.extend([f"## Draft {index}", "", item.draft, ""])
    return "\n".join(lines) + "\n"
