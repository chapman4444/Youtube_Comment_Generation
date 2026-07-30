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
from typing import Any, Callable

from ...application import build_comment_packet
from ...application.build_comment_packet import BuildCommentPacketCommand
from ...domain.section_profile import parse_length
from ...ports.events import EventKind, ProgressEvent
from .options import PacketOptionsModel
from .worker import BackgroundJob

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommentRun:
    """The packet plus the canonical run context that produced it."""

    packet: Any
    video: dict[str, Any]
    artifacts: Any
    packet_path: str
    run_record: dict[str, Any]

    @property
    def text(self) -> str:
        """Compatibility surface used by the window's packet preview."""

        return str(getattr(self.packet, "text", "") or "")


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

    def __init__(self, job: BackgroundJob) -> None:
        self.job = job

    def emit(self, event: ProgressEvent) -> None:
        self.job.say(event.message, self.FRACTIONS.get(event.step))
        # Between events is exactly where a cancel can be honoured: the
        # application is between two units of work whenever it reports one.
        if event.kind is not EventKind.FINISHED:
            self.job.check_cancelled()


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

    job.say("Starting.", 0.02)
    job.check_cancelled()

    command = BuildCommentPacketCommand(
        video=options.video,
        variations=options.registers_for("comment"),
        dials=options.dial_values(),
        max_comments=max(options.max_top, options.max_recent) or 500,
        max_replies_per_thread=options.max_replies,
        packet_characters=options.packet_characters,
        explicit_length=_length(options),
        allow_no_transcript=True,
    )

    events = JobEvents(job)
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

    packet = result.value["packet"]
    run_record = dict(result.value.get("run") or {})
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
    session = session_factory(
        found=found,
        waiting=found.waiting[:options.guided_limit],
        transcript=transcript,
        templates=templates,
        artifacts=artifacts,
        events=events,
        registers=options.registers_for("reply"),
        dials=options.dial_values(),
        packet_characters=options.packet_characters,
    )
    # Built from the same list the session was given, so the triage packet and
    # the queue can never name different people.
    triage = ""
    if triage_for is not None and found.waiting:
        triage = triage_for(
            candidates=found.waiting,
            maximum_characters=options.packet_characters,
        )

    job.say(f"Ready: {len(found.waiting)} people.", 1.0)
    return ReplyRun(
        session=session,
        triage_packet=triage,
        people=tuple(getattr(c, "author", "") for c in found.waiting),
        receipt={
            "video": dict(found.video),
            "total": found.total,
            "waiting": len(found.waiting),
            "api_operations_used": int(
                getattr(found, "api_operations_used", 0) or 0
            ),
            "transcript": {
                "availability": getattr(
                    getattr(transcript, "availability", "available"),
                    "value",
                    str(getattr(transcript, "availability", "available")),
                ),
                "source": str(getattr(transcript, "source", "") or ""),
                "language": str(getattr(transcript, "language", "") or ""),
                "entries": len(getattr(transcript, "entries", ()) or ()),
                "detail": str(getattr(transcript, "detail", "") or ""),
            },
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
