"""Driving a guided run across several people without losing progress.

The state machine owns transitions; this owns the work. The split matters:
every question about "what may happen next" has one answer, in the domain,
and this layer cannot contradict it because it asks rather than decides.

Two rules are absolute here:

- **Every accepted draft is saved immediately.** Not at the end. The operator
  walks away mid-run, the machine sleeps, the terminal is closed — and what
  he already accepted is on disk. A run that saves at the end is a run that
  loses everything to the first interruption.
- **The session is the only writer of the review file.** One writer means the
  file cannot be half-written by two paths that disagree about its shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from ..domain.candidates import ReplyCandidate
from ..domain.extraction import extract_hardened_final, looks_like_packet_text
from ..domain.reply_packet import ReplyEvidence, build_reply_packet
from ..domain.section_profile import measure_comment_register
from ..domain.statuses import OperationResult, OperationStatus
from ..domain.threads import OwnerThread
from ..domain.workflow import (
    Intent,
    Phase,
    WorkerLifecycle,
    WorkflowState,
    accept_answer,
    reject_answer,
    skip,
)
from ..ports.events import EventKind, ProgressEvent

REVIEW_FILENAME = "replies_to_review.md"


@dataclass
class AcceptedDraft:
    author: str = ""
    comment_id: str = ""
    thread_id: str = ""
    status: str = ""
    their_text: str = ""
    draft: str = ""
    posted_recorded: bool = False
    posted_at: str = ""


@dataclass
class GuidedSession:
    """One guided run."""

    targets: list[ReplyCandidate] = field(default_factory=list)
    threads: dict[str, OwnerThread] = field(default_factory=dict)
    owner_channel_id: str = ""
    video: dict[str, Any] = field(default_factory=dict)
    transcript_text: str = ""
    templates: dict[str, str] = field(default_factory=dict)
    variations: tuple[str, ...] = ()
    dials: dict[str, str] = field(default_factory=dict)
    packet_characters: int = 280_000
    prompt_version: str = ""
    run_id: str = ""

    artifacts: Any = None
    history: Any = None
    clipboard: Any = None
    events: Any = None

    state: WorkflowState = field(default_factory=WorkflowState)
    accepted: list[AcceptedDraft] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    current: ReplyCandidate | None = None
    current_packet: str = ""
    _cursor: int = 0

    # -- lifecycle -------------------------------------------------------

    def start(self) -> WorkflowState:
        self.state.total_targets = len(self.targets)
        self.state.apply(Intent.START)
        self.state.worker = WorkerLifecycle.RUNNING
        self.state.apply(Intent.EVIDENCE_READY)
        self.state.apply(Intent.SELECT_TARGETS)
        self.state.worker = WorkerLifecycle.IDLE
        self._emit(EventKind.STARTED, "guided",
                   f"{len(self.targets)} people to work through")
        return self.state

    def next_person(self) -> ReplyCandidate | None:
        """Advance to the next target and build their packet.

        Returns None when the queue is exhausted, leaving the phase where it
        was so the caller can save.
        """

        if self._cursor >= len(self.targets):
            self.current = None
            return None

        self.current = self.targets[self._cursor]
        self._cursor += 1
        self.state.apply(Intent.NEXT_PERSON)
        self.state.current_index = self._cursor
        self.state.current_target_id = str(self.current.reply.get("comment_id", ""))

        thread = self.threads.get(self.current.thread_id)
        packet = build_reply_packet(
            ReplyEvidence(
                thread=thread or OwnerThread(),
                target=self.current,
                owner_channel_id=self.owner_channel_id,
                video=self.video,
                transcript_text=self.transcript_text,
                register=measure_comment_register(
                    thread.replies if thread else []
                ),
            ),
            workflow_template=self.templates["reply_workflow.md"],
            final_check_template=self.templates["reply_final_check.md"],
            variations=self.variations,
            dials=self.dials,
            maximum_characters=self.packet_characters,
        )
        self.current_packet = packet.text
        self.state.current_packet_id = packet.target_comment_id
        self._emit(EventKind.STEP, "person",
                   f"{self.current.author} ({self._cursor} of {len(self.targets)})")
        return self.current

    def copy_packet(self) -> str:
        """Put the current packet on the clipboard. Never advances."""

        self.state.apply(Intent.COPY_CURRENT_PACKET)
        if self.clipboard is not None:
            self.clipboard.write(self.current_packet)
        return self.current_packet

    def submit(self, text: str) -> OperationResult:
        """Take an answer, or refuse it without losing the person.

        Refusal order matters. Packet detection runs before extraction,
        because the packet contains a literal "### Hardened final" heading
        and extraction would happily return a line of prompt text — an answer
        that looks like an answer, about to be posted under the operator's
        own name.
        """

        result = OperationResult()
        self.state.apply(Intent.SUBMIT_PERSON_ANSWER)

        if looks_like_packet_text(text, self.current_packet):
            reject_answer(self.state, "that is the packet, not an answer to it")
            result.status = OperationStatus.REFUSED
            result.value = self.state
            self._emit(EventKind.WARNING, "person",
                       "that paste was the packet itself")
            return result

        draft = extract_hardened_final(text)
        if not draft:
            reject_answer(
                self.state,
                "no '### Hardened final' section was found, so there is "
                "nothing safe to take as the reply",
            )
            result.status = OperationStatus.REFUSED
            result.value = self.state
            self._emit(EventKind.WARNING, "person", "no Hardened final found")
            return result

        accept_answer(self.state, draft)
        person = self.current
        self.accepted.append(AcceptedDraft(
            author=person.author if person else "",
            comment_id=str(person.reply.get("comment_id", "")) if person else "",
            thread_id=person.thread_id if person else "",
            status=person.status.value if person else "",
            their_text=str(person.reply.get("text", "")) if person else "",
            draft=draft,
        ))

        # Immediately, not at the end. This is the line that makes an
        # interrupted run survivable.
        self._save_review()

        result.value = self.state
        self._emit(EventKind.STEP, "person",
                   f"accepted, {len(self.accepted)} saved so far")
        return result

    def skip_person(self) -> WorkflowState:
        if self.current is not None:
            self.skipped.append(self.current.author)
        skip(self.state)
        self._save_review()
        return self.state

    def cancel(self) -> WorkflowState:
        """Stop, keeping everything already accepted."""

        self.state.apply(Intent.CANCEL)
        self.state.worker = WorkerLifecycle.COMMITTING
        self._save_review()
        self.state.worker = WorkerLifecycle.FINISHED
        self.state.apply(Intent.SAVE)
        self._emit(EventKind.CANCELLED, "guided",
                   f"stopped with {len(self.accepted)} replies saved")
        return self.state

    def finish(self) -> WorkflowState:
        self.state.worker = WorkerLifecycle.COMMITTING
        self._save_review()
        self.state.worker = WorkerLifecycle.FINISHED
        if self.state.phase is not Phase.REVIEW_READY:
            self.state.apply(Intent.SAVE)
        self.state.apply(Intent.SAVE)
        self._emit(EventKind.FINISHED, "guided",
                   f"{len(self.accepted)} replies ready to review")
        return self.state

    def record_posted(self, index: int = -1) -> int:
        """Record one reply only after the operator confirms posting it."""

        if self.history is None:
            raise RuntimeError("No engagement history store is configured.")
        if not self.accepted:
            raise RuntimeError("No accepted reply is available to record.")
        item = self.accepted[index]
        if item.posted_recorded:
            return 0
        posted_at = datetime.now(timezone.utc).isoformat()
        added = self.history.append([{
            "video_id": str(self.video.get("video_id") or ""),
            "video_title": str(self.video.get("title") or ""),
            "target": item.author,
            "target_comment_id": item.comment_id,
            "thread_id": item.thread_id,
            "workflow": "reply",
            "operator_channel_id": self.owner_channel_id,
            "draft": item.draft,
            "prompt_version": self.prompt_version,
            "registers": list(self.variations),
            "run_id": self.run_id,
            "posted_at": posted_at,
            "source": "native",
        }])
        item.posted_recorded = True
        item.posted_at = posted_at
        self._save_review()
        return added

    # -- internals -------------------------------------------------------

    def _save_review(self) -> None:
        if self.artifacts is None:
            return
        self.artifacts.stage(REVIEW_FILENAME, render_review(self))
        self.artifacts.commit()

    def _emit(self, kind: EventKind, step: str, message: str) -> None:
        if self.events is not None:
            self.events.emit(ProgressEvent(kind, step=step, message=message))


def render_review(session: GuidedSession) -> str:
    """The file the operator actually posts from.

    Each reply is a plain block that can be selected and pasted without
    editing. Anything decorative around it is a thing he has to delete
    before posting, so there is none.
    """

    lines = [
        "# Replies ready to post",
        "",
        f"- video: {session.video.get('title') or session.video.get('video_id', '')}",
        f"- accepted: {len(session.accepted)}",
        f"- skipped: {len(session.skipped)}",
        "",
        "Each reply below is ready to paste. Nothing here has been posted.",
        "",
    ]

    if not session.accepted:
        lines.extend([
            "_No replies were accepted in this run._",
            "",
        ])

    for index, draft in enumerate(session.accepted, 1):
        lines.extend([
            "---",
            "",
            f"## {index}. {draft.author}",
            "",
            f"- their comment id: `{draft.comment_id}`",
            f"- status when drafted: {draft.status}",
            f"- posting recorded: "
            f"{'yes' if draft.posted_recorded else 'no'}",
            "",
            "**They said:**",
            "",
            "> " + str(draft.their_text).replace("\n", "\n> "),
            "",
            "**Your reply:**",
            "",
            draft.draft,
            "",
        ])

    if session.skipped:
        lines.extend(["---", "", "## Skipped", ""])
        lines.extend(f"- {author}" for author in session.skipped)
        lines.append("")

    return "\n".join(lines)
