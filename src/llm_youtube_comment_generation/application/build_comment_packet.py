"""Build a comment packet and commit its artifacts.

Retrieval is reused from the inspect use case rather than reimplemented: the
two commands must agree about what "the comments for this video" means, and
two implementations would eventually disagree.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..domain.packet_builder import (
    PacketEvidence,
    PacketOptions,
    build,
    summarized_retrieval_notes,
)
from ..domain.packets import select_packet_sections
from ..domain.statuses import (
    OperationResult,
    OperationStatus,
    WarningCode,
)
from ..domain.video import format_timestamp
from ..domain.writing_options import (
    dial_choice,
    variation_keys,
    VARIATION_LIBRARY,
    DIALS,
)
from ..ports.events import EventKind, ProgressEvent
from .commands import InspectVideoCommand
from .inspect_video import handle as inspect_handle

PACKET_FILENAME = "packet.md"


@dataclass(frozen=True)
class BuildCommentPacketCommand:
    video: str
    variations: tuple[str, ...] = ()
    dials: dict[str, str] = field(default_factory=dict)
    max_comments: int = 500
    max_replies_per_thread: int = 100
    packet_characters: int = 280_000
    explicit_length: tuple[int, int] | None = None
    allow_no_transcript: bool = False
    dry_run: bool = False

    video_id: str = field(init=False, default="")

    def __post_init__(self) -> None:
        from ..domain.ids import extract_video_id

        object.__setattr__(self, "video_id", extract_video_id(self.video))


def transcript_timestamped(entries) -> str:
    return "\n".join(
        f"[{format_timestamp(entry.get('start'))}] {entry.get('text', '')}"
        for entry in entries
    )


def handle(
    command: BuildCommentPacketCommand,
    *,
    youtube,
    transcripts,
    events,
    artifacts,
    templates: dict[str, str],
    prompt_version: str = "",
    stopwords: frozenset[str] = frozenset(),
) -> OperationResult:
    inspection_result = inspect_handle(
        InspectVideoCommand(
            video=command.video,
            max_comments=command.max_comments,
            max_replies_per_thread=command.max_replies_per_thread,
            include_replies=True,
            dry_run=command.dry_run,
        ),
        youtube=youtube, transcripts=transcripts, events=events,
    )
    result = OperationResult(warnings=list(inspection_result.warnings))
    if inspection_result.status is not OperationStatus.SUCCEEDED:
        result.status = inspection_result.status
    inspection = inspection_result.value

    if command.dry_run:
        result.value = {"dry_run": True}
        result.metrics = {"api_operations": 0}
        return result

    transcript = inspection.transcript
    if transcript is None:
        raise RuntimeError(
            "video inspection completed without its transcript result"
        )
    timestamped = transcript_timestamped(transcript.entries)

    events.emit(ProgressEvent(EventKind.STEP, step="packet",
                              message="Assembling the packet"))

    selection = select_packet_sections(
        inspection.relevance_comments, inspection.recent_comments,
        inspection.comments, inspection.replies,
    )
    evidence = PacketEvidence(
        video=inspection.video,
        comments=inspection.comments,
        replies=inspection.replies,
        transcript_text=timestamped,
        transcript_available=transcript.available,
        register=inspection.register,
        retrieval=inspection.retrieval,
        stopwords=stopwords,
    )
    options = PacketOptions(
        variations=command.variations,
        dials=dict(command.dials),
        maximum_characters=command.packet_characters,
        explicit_length=command.explicit_length,
        allow_no_transcript=command.allow_no_transcript,
    )

    packet = build(
        evidence, selection, options,
        workflow_template=templates["comment_workflow.md"],
        final_check_template=templates["comment_final_check.md"],
    )

    if not transcript.available:
        result.warn(
            WarningCode.TRANSCRIPT_UNAVAILABLE,
            "the packet was built without a transcript and says so",
        )
    elif transcript.source == "saved-transcript":
        # A warning rather than a log line: it reaches the console the
        # operator is watching. He asked for a packet about a video, and he
        # is entitled to know the words in it were not fetched today.
        result.warn(
            WarningCode.TRANSCRIPT_UNAVAILABLE,
            # ASCII only: this is read in a Windows console, where an em dash
            # arrives as mojibake on a cp1252 code page.
            f"the transcript was reused, not fetched: {transcript.detail}",
        )

    run_record = {
        "kind": "comment",
        "artifact_contract_version": 2,
        "evidence_schema_version": 2,
        "video_id": inspection.video.get("video_id", ""),
        "video_title": inspection.video.get("title", ""),
        "prompt_version": prompt_version,
        "variations": list(packet.variations),
        "variation_headings": list(packet.headings),
        "dials": {name: dial_choice(name, command.dials) for name in DIALS},
        "packet_characters": len(packet),
        "budget": command.packet_characters,
        "allocation": {
            "comment_body": packet.allocation.comment_body,
            "reply_body": packet.allocation.reply_body,
            "transcript": packet.allocation.transcript,
            "transcript_reduced": packet.allocation.transcript_reduced,
        },
        "retrieval": {
            "status": inspection.retrieval.status.value,
            "may_conclude_absence": inspection.retrieval.may_conclude_absence,
            "retrieved": inspection.retrieval.retrieved,
            "reported_total": inspection.retrieval.reported_total,
            "notes": list(inspection.retrieval.notes),
        },
        "transcript": {
            "availability": transcript.availability.value,
            "language": transcript.language,
            "entries": len(transcript.entries),
            # Where it came from, not only whether there was one. A transcript
            # reused from an earlier run is a legitimate way to build a packet
            # and an illegitimate thing to leave unrecorded.
            "source": transcript.source,
            "detail": transcript.detail,
        },
        "counts": {
            "comments": len(inspection.comments),
            "replies": len(inspection.replies),
        },
        "api_operations_used": inspection.api_operations_used,
        "warnings": [
            {"code": w.code.value, "message": w.message} for w in result.warnings
        ],
    }

    artifacts.stage(PACKET_FILENAME, packet.text)
    artifacts.stage("transcript_timestamped.txt", timestamped or "")
    artifacts.stage("evidence.json", json.dumps({
        "schema_version": 2,
        "video": inspection.video,
        "comments": inspection.comments,
        "replies": inspection.replies,
        "relevance_comments": inspection.relevance_comments,
        "recent_comments": inspection.recent_comments,
    }, indent=2, ensure_ascii=False))
    artifacts.stage("report.md", render_report(run_record, packet))
    artifacts.stage("run.json", json.dumps(run_record, indent=2,
                                           ensure_ascii=False))

    events.emit(ProgressEvent(
        EventKind.STEP, step="commit",
        message="Publishing the completed run",
    ))
    published = artifacts.commit()
    events.emit(ProgressEvent(
        EventKind.FINISHED, step="packet",
        message=f"Wrote {len(published)} files, {len(packet):,} characters",
    ))

    result.value = {
        "packet": packet,
        "run": run_record,
        "transcript": transcript,
        "evidence": {
            "schema_version": 2,
            "video": inspection.video,
            "comments": inspection.comments,
            "replies": inspection.replies,
            "relevance_comments": inspection.relevance_comments,
            "recent_comments": inspection.recent_comments,
        },
    }
    result.artifacts = list(published)
    result.metrics = {
        "characters": len(packet),
        "comments": len(inspection.comments),
        "replies": len(inspection.replies),
        "api_operations": inspection.api_operations_used,
    }
    return result


def render_report(run: dict[str, Any], packet) -> str:
    """A human account of what this run did and what it is evidence of."""

    lines = [
        f"# Run report: {run['video_title'] or run['video_id']}",
        "",
        f"- video: {run['video_id']}",
        f"- prompt version: {run['prompt_version']}",
        f"- packet: {run['packet_characters']:,} of {run['budget']:,} characters",
        f"- comments: {run['counts']['comments']:,}",
        f"- replies: {run['counts']['replies']:,}",
        f"- logical YouTube API operations: {run['api_operations_used']}",
        "",
        "## Registers asked for",
        "",
    ]
    for key in run["variations"]:
        lines.append(f"- {VARIATION_LIBRARY[key].heading}  (`{key}`)")

    changed = {name: value for name, value in run["dials"].items()
               if value != DIALS[name].default}
    lines.extend(["", "## Dials", ""])
    lines.append(
        "\n".join(f"- {name}: {value}" for name, value in changed.items())
        if changed else "- every dial at its default, so the packet is the "
                        "one this tool produces with no options set"
    )

    retrieval = run["retrieval"]
    lines.extend([
        "",
        "## What this evidence covers",
        "",
        f"- retrieval status: {retrieval['status']}",
        f"- top-level comments retained: {run['counts']['comments']:,}",
        f"- replies retained: {run['counts']['replies']:,}",
    ])
    if retrieval.get("reported_total") is not None:
        lines.append(
            f"- comments reported by YouTube: "
            f"{retrieval['reported_total']:,}"
        )
    if not retrieval["may_conclude_absence"]:
        lines.append(
            "- **this sample is incomplete.** It cannot be used to conclude "
            "that a view is absent from the comment section."
        )
    for note in summarized_retrieval_notes(retrieval["notes"]):
        lines.append(f"- {note}")

    transcript = run["transcript"]
    lines.extend(["", "## Transcript", ""])
    if transcript["availability"] == "available":
        lines.append(
            f"- {transcript['language']}, {transcript['entries']:,} lines"
        )
        if run["allocation"]["transcript_reduced"]:
            lines.append("- the transcript was reduced to fit the budget")
    else:
        lines.append(
            f"- **none.** ({transcript['availability']}) This packet was built "
            "without a transcript and says so in its own instructions."
        )

    if run["warnings"]:
        lines.extend(["", "## Warnings", ""])
        for warning in run["warnings"]:
            lines.append(f"- {warning['code']}: {warning['message']}")

    return "\n".join(lines) + "\n"
