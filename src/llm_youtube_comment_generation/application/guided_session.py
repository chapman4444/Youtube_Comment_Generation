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

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from ..domain.candidates import ReplyCandidate
from ..domain.errors import ConfigurationError
from ..domain.extraction import extract_batch_replies, looks_like_packet_text
from ..domain.reply_packet import (
    ReplyEvidence,
    ReplyTarget,
    build_reply_packet,
)
from ..domain.section_profile import measure_comment_register
from ..domain.statuses import (
    OperationResult,
    OperationStatus,
    RetrievalOutcome,
    TranscriptResult,
    transcript_provenance,
)
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


def named_selection(candidates, named: str = ""):
    """Keep the people a comma list or a pasted triage answer names.

    The legacy `--reply-to`. Accepts either shape because both are what the
    operator actually has to hand: a handful of handles he typed, or the
    triage answer still on his clipboard. Parsing runs through the same
    `parse_triage_selection` the GUI uses, so a SKIP line cannot leak in.

    A thread is answered whole, so naming anybody keeps their thread-mates
    too — the caller states that, and `whole_thread_selection` enforces it.
    Naming nobody who is present raises rather than silently emptying the
    queue: an empty queue reads as "nobody is waiting", which is the one
    thing it must never say by accident.
    """

    text = str(named or "").strip()
    if not text:
        return list(candidates)

    from ..domain.extraction import parse_triage_selection
    wanted = {handle.lstrip("@").casefold()
              for handle in parse_triage_selection(text)}
    if not wanted:
        raise ConfigurationError(
            f"No handles were found in {text!r}. Give a comma-separated "
            "list like @alice,@bob, or paste the triage answer."
        )
    kept = [c for c in candidates
            if str(getattr(c, "author", "")).lstrip("@").casefold() in wanted]
    if not kept:
        raise ConfigurationError(
            f"None of the {len(wanted)} named people are in this queue. Run "
            "`reply scan-mine` to see who is."
        )
    return kept


def top_replier_selection(candidates, top: int = 0):
    """The N people whose message the room liked most, one entry each.

    The legacy `--top-repliers N`. Ranking is by the like count on the
    message the candidate is holding, then by the scan's own score, so a
    tie between two unliked replies still resolves the way the queue does.
    Zero means "no ranking", which is the setting's own default.
    """

    if not top:
        return list(candidates)

    def likes(candidate):
        try:
            return int(candidate.reply.get("like_count") or 0)
        except (AttributeError, TypeError, ValueError):
            return 0

    ranked = sorted(
        candidates,
        key=lambda c: (likes(c), float(getattr(c, "score", 0.0) or 0.0)),
        reverse=True,
    )[:top]
    # Back into scan order: the queue is read top to bottom, and re-ordering
    # it by likes would silently re-rank people the scan already ranked.
    chosen = {id(candidate) for candidate in ranked}
    return [c for c in candidates if id(c) in chosen]


def every_thread_selection(candidates, threads):
    """One entry per owner thread that drew any audience response.

    The legacy "also write a separate packet for each of my comments". The
    default queue holds only people still owed an answer, so a thread whose
    replies were all handled disappears — and with it the chance to answer
    the newcomers in it. This adds a placeholder candidate for any thread
    that has responses but no outstanding person, leaving threads that
    nobody replied to alone.
    """

    covered = {str(getattr(c, "thread_id", "") or "") for c in candidates}
    extra = []
    for thread in threads:
        thread_id = str(getattr(thread, "comment_id", "") or "")
        if not thread_id or thread_id in covered:
            continue
        if not getattr(thread, "replies", ()):
            continue
        newest = thread.replies[-1]
        extra.append(ReplyCandidate(
            author=str(newest.get("author") or ""),
            reply=dict(newest),
            thread_id=thread_id,
            answered=True,
        ))
    return list(candidates) + extra


def whole_thread_selection(candidates, limit=None):
    """Keep whole threads, in candidate order, bounded by a thread count.

    One packet answers everybody in a thread, so a selection that splits a
    thread's candidates would still produce replies for the dropped people —
    the second review reproduced exactly that with a one-candidate session
    whose packet answered two. Selecting anybody therefore selects their
    whole thread, and a limit counts threads, never people.
    """

    thread_ids: list[str] = []
    selected = []
    for candidate in candidates:
        thread_id = str(getattr(candidate, "thread_id", "") or "")
        if thread_id not in thread_ids:
            if limit is not None and len(thread_ids) >= limit:
                continue
            thread_ids.append(thread_id)
        selected.append(candidate)
    return selected


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
    transcript: TranscriptResult | None = None
    templates: dict[str, str] = field(default_factory=dict)
    # The scan's own completeness verdict, carried so a guided packet makes
    # the same disclosure a direct CLI build does. The second review caught
    # guided packets substituting the default outcome.
    retrieval: RetrievalOutcome = field(default_factory=RetrievalOutcome)
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
    current_targets: tuple[ReplyTarget, ...] = ()
    _thread_queue: list[str] = field(default_factory=list)
    _cursor: int = 0

    # -- lifecycle -------------------------------------------------------

    def thread_queue(self) -> list[str]:
        """The owner threads to process, each exactly once, in queue order.

        Several candidates can point at the same thread. One packet now
        answers everybody in a thread, so building a packet per candidate
        would ask the model the same question twice and hand the operator
        two conflicting sheets to post from.
        """

        return list(dict.fromkeys(
            candidate.thread_id for candidate in self.targets
        ))

    def start(self) -> WorkflowState:
        self._thread_queue = self.thread_queue()
        self.state.total_targets = len(self._thread_queue)
        self.state.apply(Intent.START)
        self.state.worker = WorkerLifecycle.RUNNING
        self.state.apply(Intent.EVIDENCE_READY)
        self.state.apply(Intent.SELECT_TARGETS)
        self.state.worker = WorkerLifecycle.IDLE
        self._emit(EventKind.STARTED, "guided",
                   f"{len(self._thread_queue)} threads to work through")
        return self.state

    def next_person(self) -> ReplyCandidate | None:
        """Advance to the next owner thread and build its batch packet.

        Keeps its name because the state machine's intent is NEXT_PERSON;
        the unit of work is now one thread, represented by the first
        candidate found in it. Returns None when the queue is exhausted,
        leaving the phase where it was so the caller can save.
        """

        if self._cursor >= len(self._thread_queue):
            self.current = None
            return None

        thread_id = self._thread_queue[self._cursor]
        self._cursor += 1
        self.current = next(
            (c for c in self.targets if c.thread_id == thread_id), None
        )
        self.state.apply(Intent.NEXT_PERSON)
        self.state.current_index = self._cursor
        self.state.current_target_id = thread_id

        thread = self.threads.get(thread_id)
        packet = build_reply_packet(
            ReplyEvidence(
                thread=thread or OwnerThread(),
                selected=self.current,
                owner_channel_id=self.owner_channel_id,
                video=self.video,
                transcript_text=self.transcript_text,
                register=measure_comment_register(
                    thread.replies if thread else []
                ),
                retrieval=self.retrieval,
            ),
            workflow_template=self.templates["reply_workflow.md"],
            final_check_template=self.templates["reply_final_check.md"],
            variations=self.variations,
            dials=self.dials,
            maximum_characters=self.packet_characters,
        )
        self.current_packet = packet.text
        self.current_targets = packet.targets
        self.state.current_packet_id = packet.thread_comment_id
        self._emit(
            EventKind.STEP, "thread",
            f"thread {self._cursor} of {len(self._thread_queue)}: "
            f"{len(packet.targets)} responses to answer",
        )
        return self.current

    def review_path(self) -> str:
        """Where the review file lives, for whoever wants to open it.

        The session is the only writer of that file, so it is also the only
        thing that names it; a window that knew the filename would be a
        second place the output layout is defined.
        """

        root = str(getattr(self.artifacts, "root", "") or "")
        return os.path.join(root, REVIEW_FILENAME) if root else ""

    def copy_packet(self) -> str:
        """Put the current packet on the clipboard. Never advances."""

        self.state.apply(Intent.COPY_CURRENT_PACKET)
        if self.clipboard is not None:
            self.clipboard.write(self.current_packet)
        return self.current_packet

    def submit(self, text: str) -> OperationResult:
        """Take a batch answer, or refuse it without losing the thread.

        Refusal order matters. Packet detection runs before parsing, because
        the packet describes the sheet format in its own instructions — an
        answer that looks like an answer, about to be posted under the
        operator's own name.

        A batch is accepted whole or refused whole. Accepting the parseable
        half would post some people's replies and silently drop the rest,
        and the dropped ones would look answered.
        """

        result = OperationResult()
        self.state.apply(Intent.SUBMIT_PERSON_ANSWER)

        if looks_like_packet_text(text, self.current_packet):
            reject_answer(self.state, "that is the packet, not an answer to it")
            result.status = OperationStatus.REFUSED
            result.value = self.state
            self._emit(EventKind.WARNING, "thread",
                       "that paste was the packet itself")
            return result

        expected = [target.comment_id for target in self.current_targets]
        replies, problems = extract_batch_replies(text, expected)
        if problems:
            shown = "; ".join(problems[:3])
            if len(problems) > 3:
                shown += f"; and {len(problems) - 3} more"
            reject_answer(self.state, shown)
            result.status = OperationStatus.REFUSED
            result.value = self.state
            self._emit(EventKind.WARNING, "thread",
                       f"batch refused: {shown}")
            return result

        accept_answer(self.state, text)
        for target in self.current_targets:
            self.accepted.append(AcceptedDraft(
                author=target.author_display_name,
                comment_id=target.comment_id,
                thread_id=target.thread_parent_comment_id,
                status=target.relationship,
                their_text=target.text,
                draft=replies[target.comment_id],
            ))

        # Immediately, not at the end. This is the line that makes an
        # interrupted run survivable.
        self._save_review()

        result.value = self.state
        self._emit(
            EventKind.STEP, "thread",
            f"accepted {len(self.current_targets)} replies, "
            f"{len(self.accepted)} saved so far",
        )
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
        if self.transcript is not None:
            self.artifacts.stage("run.json", self._run_record())
        self.artifacts.commit()

    def _run_record(self) -> str:
        return json.dumps({
            "kind": "guided",
            "artifact_contract_version": 3,
            "video_id": str(self.video.get("video_id", "")),
            "video_title": str(self.video.get("title", "")),
            "prompt_version": self.prompt_version,
            "transcript": transcript_provenance(self.transcript),
            "accepted": len(self.accepted),
            "skipped": len(self.skipped),
            "targets_offered": len(self.targets),
            "thread_packets": len(self._thread_queue),
            "retrieval": {
                "status": getattr(self.retrieval.status, "value",
                                  str(self.retrieval.status)),
                "notes": [str(note) for note in self.retrieval.notes],
            },
            "final_phase": self.state.phase.value,
            "variations": list(self.variations),
            "drafts": [
                {
                    "author": draft.author,
                    "comment_id": draft.comment_id,
                    "status": draft.status,
                    "words": len(draft.draft.split()),
                }
                for draft in self.accepted
            ],
        }, indent=2, ensure_ascii=False)

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
