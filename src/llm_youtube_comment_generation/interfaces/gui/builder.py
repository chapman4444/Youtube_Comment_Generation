"""What the window's Build button actually does.

The window holds the options and the worker holds the thread; this is the one
piece that knows how to turn the first into a packet. It lives apart from both
so the window stays free of application imports and the worker stays free of
knowing what it is running.

Runs on the worker thread. Everything it says goes back through
``job.say(...)``, which puts it on a queue the window drains from its own
``after`` loop — nothing here may touch a widget, because Tk is not
thread-safe and the failure is a hang an hour later rather than an exception
now.

Cancelling is cooperative. ``job.check_cancelled()`` is called between the
units of work that are actually separable — before the scan, before the
transcript, before assembly — so Cancel means "stop at the next safe point"
rather than pretending a thread can be torn out of the air.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from ...application import build_comment_packet
from ...application.build_comment_packet import BuildCommentPacketCommand
from ...application.guided_session import (
    every_thread_selection,
    top_replier_selection,
    whole_thread_selection,
)
from ...application.debug_build import TemplateLogicAuditContext
from ...domain.errors import OperationCancelled
from ...domain.section_profile import parse_length
from ...domain.statuses import transcript_provenance
from ...ports.events import EventKind, ProgressEvent
from .options import PacketOptionsModel
from .worker import BackgroundJob, Cancelled

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommentRun:
    """The packet plus the canonical run context that produced it."""

    packet: Any
    video: dict[str, Any]
    artifacts: Any
    packet_path: str
    run_record: dict[str, Any]
    transcript: Any = None
    evidence: dict[str, Any] | None = None
    debug_packet: str = ""
    debug_settings: dict[str, Any] | None = None
    # Carried from the build rather than rebuilt from widgets later: the
    # session completes the audit artifact after a response arrives, and the
    # options the operator sees by then may no longer be the ones that
    # produced this packet.
    template_logic_audit_context: TemplateLogicAuditContext | None = None

    @property
    def text(self) -> str:
        """Compatibility surface used by the window's packet preview."""

        return str(getattr(self.packet, "text", "") or "")

    @property
    def model_text(self) -> str:
        """The packet copied to the model for this run."""

        return self.debug_packet or self.text


class JobEvents:
    """An event sink that reports to the window instead of the console.

    The application layer emits progress through a port; this is the window's
    implementation of it. Without this the operator watches a progress bar
    that never moves while the console it cannot see fills up.
    """

    #: Rough fractions for the steps a comment build actually goes through.
    #: Not measured -- a progress bar that is honest about being an estimate
    #: is better than one that sits at zero until it finishes.
    FRACTIONS = {
        "video": 0.15,
        "comments": 0.45,
        "replies": 0.65,
        "transcript": 0.8,
        "packet": 0.92,
    }

    def __init__(
        self,
        job: BackgroundJob,
        *,
        video_id: str = "",
        preset: str = "",
        started_at: str = "",
    ) -> None:
        self.job = job
        self.video_id = video_id
        self.preset = preset
        self.started_at = started_at
        self._boundary_required = bool(video_id)
        self._boundary_written = False
        self._pending: list[
            tuple[str, float | None, dict[str, Any]]
        ] = []

    def emit(self, event: ProgressEvent) -> None:
        message = event.message
        if (
            not message.strip()
            and event.current is not None
            and event.total is not None
            and event.step in ("comments", "replies", "threads")
        ):
            label = {
                "comments": "Comments",
                "replies": "Reply threads",
                "threads": "Your threads",
            }.get(event.step, event.step.replace("_", " ").title())
            message = f"{label}: {event.current:,} of {event.total:,}"
        fraction = self.FRACTIONS.get(event.step)
        if event.step == "transcribe" and event.fraction is not None:
            fraction = 0.72 + (0.2 * event.fraction)
        payload = {"step": event.step, "data": dict(event.data)}
        if (
            self._boundary_required
            and not self._boundary_written
            and event.step == "video_identity"
        ):
            self.ensure_boundary(
                title=str(event.data.get("video_title") or "")
            )
        elif self._boundary_required and not self._boundary_written:
            self._pending.append((message, fraction, payload))
            if event.kind is EventKind.FINISHED:
                self.ensure_boundary()
        else:
            self.job.say(message, fraction, payload=payload)
        # Between events is exactly where a cancel can be honoured: the
        # application is between two units of work whenever it reports one.
        if event.kind is not EventKind.FINISHED:
            self.job.check_cancelled()

    def ensure_boundary(self, *, title: str = "") -> None:
        """Write one run separator, then release its buffered opening events."""

        if not self._boundary_required or self._boundary_written:
            return
        self.job.say(activity_run_separator(
            video_id=self.video_id,
            title=title or "Title unavailable",
            started_at=self.started_at,
            preset=self.preset,
        ))
        self._boundary_written = True
        for message, fraction, payload in self._pending:
            self.job.say(message, fraction, payload=payload)
        self._pending.clear()


def activity_run_separator(
    *,
    video_id: str,
    title: str,
    started_at: str,
    preset: str,
) -> str:
    """A visible boundary that identifies one Activity-tab build."""

    rule = "=" * 72
    return "\n".join((
        rule,
        f"Build: {video_id} | {title}",
        f"Started: {started_at} | Preset: {preset or 'Current settings'}",
        rule,
    ))


def build_comment(
    options: PacketOptionsModel,
    job: BackgroundJob,
    *,
    ports_factory: Callable[..., dict[str, Any]],
    templates: dict[str, str],
    artifacts_for: Callable[[str, str], Any],
    stopwords: frozenset[str] = frozenset(),
    prompt_version: str = "",
) -> Any:
    """Build one comment packet from what the window is showing.

    ``templates``, ``artifacts_for`` and ``stopwords`` arrive from the caller
    rather than being loaded here. The gui package does not name output files
    or read resources — a window that knew a filename would be a second place
    the output layout is defined, and the two would drift.
    ``tests/gui/test_gui_boundaries.py`` enforces it and caught this module
    getting it wrong.

    Returns the packet. The window keeps it for its Copy button, so nothing
    re-reads it off disk and the two cannot disagree about what was built.
    """

    command = BuildCommentPacketCommand(
        video=options.video,
        variations=options.registers_for("comment"),
        dials=options.dial_values(),
        max_comments=max(options.max_top, options.max_recent) or 500,
        max_relevance_comments=options.max_top,
        max_recent_comments=options.max_recent,
        max_reply_threads=options.max_threads,
        max_replies_per_thread=options.max_replies,
        include_replies=options.include_replies,
        transcript_languages=options.transcript_languages,
        packet_characters=options.packet_characters,
        explicit_length=_length(options),
        allow_no_transcript=True,
        debug=options.debug_build,
        debug_settings={
            "mode": "comment",
            "selected_approaches": list(options.registers_for("comment")),
            "dials": options.dial_values(),
            "length": options.length,
            "target_words": options.custom_length if options.length == "exact" else "",
            "retrieval_limits": {
                "relevance_comments": options.max_top,
                "recent_comments": options.max_recent,
                "reply_threads": options.max_threads,
                "replies_per_thread": options.max_replies,
            },
            "transcript": {
                "languages": list(options.transcript_languages),
                "route": options.transcript_route,
                "whisper_policy": options.whisper_policy,
                "whisper_model": options.whisper_model,
                "maximum_minutes": options.whisper_maximum_minutes,
                "maximum_audio_mib": options.whisper_maximum_audio_mib,
            },
        },
    )

    events = JobEvents(
        job,
        video_id=command.video_id,
        preset=str(getattr(options, "_activity_preset", "") or ""),
        started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )

    try:
        events.emit(ProgressEvent(
            EventKind.STARTED,
            step="build",
            message="Starting.",
        ))
        ports = ports_factory(events)
        job.check_cancelled()
        artifacts = artifacts_for(command.video_id, options.output_directory)
        result = build_comment_packet.handle(
            command,
            youtube=ports["youtube"],
            transcripts=ports["transcripts"],
            events=events,
            artifacts=artifacts,
            templates=templates,
            prompt_version=prompt_version,
            stopwords=stopwords,
        )
    except OperationCancelled as failure:
        events.ensure_boundary()
        # Infrastructure uses the application-level cancellation exception;
        # the GUI worker uses its own exception to emit a cancelled event
        # rather than presenting an intentional stop as a failure.
        raise Cancelled() from failure
    except BaseException:
        events.ensure_boundary()
        raise

    packet = result.value["packet"]
    run_record = dict(result.value.get("run") or {})
    events.ensure_boundary(
        title=str(run_record.get("video_title") or "")
    )
    root = getattr(artifacts, "root", "")
    packet_path = str(root / build_comment_packet.PACKET_FILENAME) if hasattr(
        root, "__truediv__"
    ) else (
        f"{str(root).rstrip('/')}/{build_comment_packet.PACKET_FILENAME}"
        if root else build_comment_packet.PACKET_FILENAME
    )
    for warning in result.warnings:
        job.say(f"{warning.code.value}: {warning.message}")
    job.say(
        f"Wrote {len(packet):,} characters to "
        f"{getattr(artifacts, 'root', 'the run directory')}", 1.0
    )
    return CommentRun(
        packet=packet,
        video={
            "video_id": str(run_record.get("video_id") or command.video_id),
            "title": str(run_record.get("video_title") or ""),
        },
        artifacts=artifacts,
        packet_path=packet_path,
        run_record=run_record,
        transcript=result.value.get("transcript"),
        evidence=dict(result.value.get("evidence") or {}),
        debug_packet=str(result.value.get("debug_packet") or ""),
        debug_settings=dict(result.value.get("debug_settings") or {}),
        template_logic_audit_context=result.value.get(
            "template_logic_audit_context"
        ),
    )


@dataclass
class ReplyRun:
    """What a reply scan produces: a session, and the triage packet for it.

    Two objects rather than one because they answer different questions. The
    session knows who is waiting and what each of them gets; the triage packet
    asks which of them are worth answering at all, and is built once from the
    same list so the two cannot disagree about who is on it.
    """

    session: Any
    triage_packet: str = ""
    people: tuple[str, ...] = ()
    receipt: dict[str, Any] | None = None
    transcript: Any = None


def prepare_replies(
    options: PacketOptionsModel,
    job: BackgroundJob,
    *,
    ports_factory: Callable[..., dict[str, Any]],
    templates: dict[str, str],
    artifacts_for: Callable[[str, str], Any],
    session_factory: Callable[..., Any],
    scan: Callable[..., Any],
    triage_for: Callable[..., str] | None = None,
    clock: Any = None,
) -> "ReplyRun":
    """Scan for people owed a reply and hand back a session over them.

    A `GuidedSession` already owns every rule about the reply flow — which
    packet a person gets, what counts as an answer, when a draft is saved.
    The window drives that rather than reimplementing it, so the window and
    `ytcomment reply guided` cannot come to disagree about what a reply run
    is.
    """

    job.say("Scanning for people who replied to you.", 0.05)
    job.check_cancelled()

    events = JobEvents(job)
    ports = ports_factory(events)

    found = scan(
        video=options.video,
        handle=options.my_handle,
        max_comments=options.reply_scan_comments,
        # The window fields wrote these to the model and nothing
        # read them back; the CLI passed both all along
        # (harsh-critic review, finding 10).
        since=options.since,
        only_unanswered=not options.include_answered,
        youtube=ports["youtube"],
        events=events,
        clock=clock,
    )
    job.check_cancelled()

    job.say(
        f"{len(found.waiting)} of {found.total} people are waiting.", 0.6,
    )

    transcript = ports["transcripts"].fetch(found.video_id)
    job.check_cancelled()

    artifacts = artifacts_for(found.video_id, options.output_directory)
    # The limit is resolved exactly once, and it keeps whole threads. The
    # session, the triage packet and the visible run must all describe the
    # same people: the first review caught triage ranking candidates the
    # limit had withheld, and the second caught a person-count limit
    # splitting a thread whose dropped people still got replies.
    waiting = list(found.waiting)
    if options.per_thread:
        # Every thread that drew a response, not only the ones with somebody
        # still owed an answer.
        waiting = every_thread_selection(waiting, found.threads)
    if options.top_repliers:
        waiting = top_replier_selection(waiting, options.top_repliers)
        job.say(
            f"Top repliers: {len(waiting)} of {len(found.waiting)} by likes.",
            0.7,
        )
    selected = whole_thread_selection(waiting, options.guided_limit)
    session = session_factory(
        found=found,
        waiting=selected,
        transcript=transcript,
        templates=templates,
        artifacts=artifacts,
        events=events,
        registers=options.registers_for("reply"),
        dials=options.dial_values("reply"),
        packet_characters=options.packet_characters,
    )
    triage = ""
    if triage_for is not None and selected:
        triage = triage_for(
            candidates=selected,
            maximum_characters=options.packet_characters,
            # The triage template promises the owner's comment and the video;
            # a packet listing replies with neither is undecidable. The scan
            # already fetched the video record, so no second API call.
            video=found.video,
            threads=found.threads,
        )

    job.say(
        f"Ready: {len(selected)} of {len(found.waiting)} people.", 1.0,
    )
    return ReplyRun(
        session=session,
        triage_packet=triage,
        people=tuple(getattr(c, "author", "") for c in selected),
        transcript=transcript,
        receipt={
            "video": dict(found.video),
            "total": found.total,
            "waiting": len(found.waiting),
            "retrieval": {
                "status": getattr(
                    getattr(getattr(found, "retrieval", None), "status", None),
                    "value", "unknown"),
                "notes": [str(note) for note in getattr(
                    getattr(found, "retrieval", None), "notes", ()) or ()],
            },
            "api_operations_used": int(
                getattr(found, "api_operations_used", 0) or 0
            ),
            "transcript": transcript_provenance(transcript),
            "registers": list(options.registers_for("reply")),
            "dials": options.dial_values(),
            "output": str(getattr(artifacts, "root", "") or ""),
        },
    )


def _length(options: PacketOptionsModel):
    """A typed word count wins; otherwise the radio does.

    ``parse_length`` already resolves every named value, including "auto" to
    None, so the window does not get its own opinion about what "short"
    means. Only the custom box is decided here, because "or words: 120" is a
    target rather than an exact count and that rule lives with the options.
    """

    explicit = options.explicit_length()
    if explicit is not None:
        return explicit
    return parse_length(options.length or "auto")
