"""Rendering typed results for a terminal or for a script.

No domain logic here. A formatter that decided anything would be a second
implementation of the application, which is the failure mode the CLI/GUI
contract exists to prevent.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ...domain.statuses import OperationResult

IDENTITY_SETTINGS = frozenset({"my_channel_id", "my_handle"})
PATH_SETTINGS = frozenset({
    "editor", "output_directory", "state_directory",
})
WINDOWS_HOME = re.compile(
    r"(?i)\b([A-Z]:[\\/]+Users[\\/]+)[A-Za-z0-9._-]+"
)


def _safe_config_value(name: str, value: Any) -> Any:
    """Keep diagnostics useful without making them identifying."""

    if name in IDENTITY_SETTINGS:
        return "<redacted>" if value else ""
    if name == "proxy_url":
        text = str(value or "")
        if not text:
            return ""
        try:
            parsed = urlsplit(text)
            host = parsed.hostname or ""
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            port = f":{parsed.port}" if parsed.port is not None else ""
            return urlunsplit((parsed.scheme, host + port, "", "", ""))
        except (TypeError, ValueError):
            return "<redacted proxy URL>"
    if name in PATH_SETTINGS:
        text = str(value or "")
        if not text:
            return ""
        return WINDOWS_HOME.sub(r"\1<user>", text)
    return value


def inspection_as_dict(result: OperationResult) -> dict[str, Any]:
    """The JSON shape. Stable: a caller scripts against these keys.

    Adding a key is safe; renaming or removing one is a breaking change and
    a test asserts the shape so that has to be deliberate.
    """

    inspection = result.value
    payload: dict[str, Any] = {
        "status": result.status.value,
        "video": {
            "video_id": inspection.video.get("video_id", ""),
            "title": inspection.video.get("title", ""),
            "channel_title": inspection.video.get("channel_title", ""),
            "channel_id": inspection.video.get("channel_id", ""),
            "published_at": inspection.video.get("published_at", ""),
            "duration_seconds": inspection.video.get("duration_seconds"),
            "view_count": inspection.video.get("view_count"),
            "like_count": inspection.video.get("like_count"),
            "comment_count": inspection.video.get("comment_count"),
        },
        "retrieval": {
            "status": inspection.retrieval.status.value,
            "complete": inspection.retrieval.is_complete,
            "may_conclude_absence": inspection.retrieval.may_conclude_absence,
            "retrieved": inspection.retrieval.retrieved,
            "reported_total": inspection.retrieval.reported_total,
            "missing": inspection.retrieval.missing,
            "notes": list(inspection.retrieval.notes),
        },
        "counts": {
            "comments": len(inspection.comments),
            "replies": len(inspection.replies),
        },
        "transcript": {
            "availability": inspection.transcript_availability.value,
            "available": inspection.transcript_availability.is_available,
            "language": inspection.transcript_language,
            "entries": inspection.transcript_entries,
        },
        "register": {
            "sample_size": inspection.register.sample_size,
            "median_words": inspection.register.median_words,
            "p90_words": inspection.register.p90_words,
            "top_liked_median_words": inspection.register.top_liked_median_words,
        },
        "warnings": [
            {"code": warning.code.value, "message": warning.message}
            for warning in result.warnings
        ],
        "metrics": dict(result.metrics),
        "dry_run": inspection.dry_run,
    }
    return payload


def render_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


def render_inspection(result: OperationResult) -> str:
    """Human output.

    Retrieval completeness is stated on its own line whether or not it is
    complete. Reporting it only when something went wrong trains the reader
    to assume silence means success, which is precisely the habit that lets a
    truncated scan pass for a full one.
    """

    inspection = result.value
    if inspection.dry_run:
        return (
            f"Dry run for {inspection.video.get('video_id')}.\n"
            "No API request was sent, so no quota was spent."
        )

    video = inspection.video
    lines = [
        f"{video.get('title', '(untitled)')}",
        f"  video      {video.get('video_id', '')}",
        f"  channel    {video.get('channel_title', '')}",
        f"  published  {video.get('published_at', '')}",
    ]

    counts = [
        ("views", video.get("view_count")),
        ("likes", video.get("like_count")),
        ("comments reported", video.get("comment_count")),
    ]
    for label, value in counts:
        shown = "unavailable" if value is None else f"{value:,}"
        lines.append(f"  {label:<17}  {shown}")

    retrieval = inspection.retrieval
    lines.append("")
    lines.append(
        f"  retrieved  {len(inspection.comments):,} comments, "
        f"{len(inspection.replies):,} replies"
    )
    lines.append(f"  retrieval  {retrieval.status.value}")
    if retrieval.has_shortfall:
        lines.append(
            f"             {retrieval.missing:,} fewer than the "
            f"{retrieval.reported_total:,} YouTube reports"
        )
    if not retrieval.may_conclude_absence:
        lines.append(
            "             this scan cannot be used to conclude a comment "
            "is absent"
        )
    for note in retrieval.notes:
        lines.append(f"             {note}")

    transcript = inspection.transcript_availability
    detail = (f"{inspection.transcript_language or 'unknown language'}, "
              f"{inspection.transcript_entries:,} lines"
              if transcript.is_available else transcript.value)
    lines.append(f"  transcript {detail}")

    register = inspection.register
    if register.sample_size:
        lines.append("")
        lines.append(
            f"  measured register  median {register.median_words} words, "
            f"top-liked median {register.top_liked_median_words}, "
            f"90th percentile {register.p90_words}"
        )

    if result.warnings:
        lines.append("")
        for warning in result.warnings:
            lines.append(f"  warning    {warning.code.value}: {warning.message}")

    lines.append("")
    lines.append(
        f"  {inspection.api_operations_used} logical YouTube API "
        "operations used"
    )
    return "\n".join(lines)


def candidate_as_dict(candidate) -> dict[str, Any]:
    return {
        "author": candidate.author,
        "channel_id": candidate.channel_id,
        "comment_id": str(candidate.reply.get("comment_id", "")),
        "thread_id": candidate.thread_id,
        "status": candidate.status.value,
        "reason": candidate.reason,
        "outstanding": candidate.outstanding,
        "score": round(candidate.score, 2),
        "likes": candidate.reply.get("like_count", 0),
        "messages": candidate.message_count,
        "their_last_reply": candidate.their_last_reply,
        "my_last_answer": candidate.my_last_answer,
        "text": str(candidate.reply.get("text", "")),
    }


def scan_as_dict(result: OperationResult) -> dict[str, Any]:
    scan = result.value
    return {
        "status": result.status.value,
        "owner_channel_id": scan.owner_channel_id,
        "threads": [
            {
                "comment_id": thread.comment_id,
                "replies_retrieved": len(thread.replies),
                "replies_reported": thread.reported_reply_count,
                "truncated": thread.truncated,
            }
            for thread in scan.threads
        ],
        "candidates": [candidate_as_dict(c) for c in scan.candidates],
        "retrieval": {
            "status": scan.retrieval.status.value,
            "may_conclude_absence": scan.retrieval.may_conclude_absence,
            "retrieved": scan.retrieval.retrieved,
            "notes": list(scan.retrieval.notes),
        },
        "warnings": [
            {"code": w.code.value, "message": w.message} for w in result.warnings
        ],
        "metrics": dict(result.metrics),
    }


def render_scan(result: OperationResult, only_unanswered: bool = True) -> str:
    """The queue.

    The status word leads every line, because the question the operator is
    actually asking is "who still needs me", not "who is here".
    """

    scan = result.value
    shown = [c for c in scan.candidates
             if c.outstanding or not only_unanswered]

    lines = [
        f"{len(scan.threads)} of your comments, "
        f"{len(scan.candidates)} "
        f"{'person' if len(scan.candidates) == 1 else 'people'}, "
        f"{sum(1 for c in scan.candidates if c.outstanding)} still owed a reply",
        "",
    ]

    if not shown:
        lines.append("  Nobody in this scan is waiting for an answer.")
    for candidate in shown:
        text = " ".join(str(candidate.reply.get("text") or "").split())[:88]
        likes = candidate.reply.get("like_count", 0) or 0
        lines.extend([
            f"  [{candidate.status.value}] {candidate.author}  "
            f"({likes:,} likes, {candidate.message_count} message"
            f"{'s' if candidate.message_count != 1 else ''})",
            f"      id      {candidate.reply.get('comment_id', '')}",
            f"      why     {candidate.reason}",
            f"      said    {text}",
            "",
        ])

    retrieval = scan.retrieval
    lines.append(f"  retrieval  {retrieval.status.value}")
    if not retrieval.may_conclude_absence:
        # An empty queue implies "nobody is waiting". Only a complete scan
        # earns that claim.
        lines.append(
            "             incomplete, so this queue may be missing people"
        )
    for note in retrieval.notes:
        lines.append(f"             {note}")
    lines.append(
        f"  {scan.api_operations_used} logical YouTube API operations used"
    )
    return "\n".join(lines)


def render_target(candidate) -> str:
    return "\n".join([
        f"Target: {candidate.author}",
        f"  status   {candidate.status.value}",
        f"  why      {candidate.reason}",
        f"  comment  {candidate.reply.get('comment_id', '')}",
        f"  thread   {candidate.thread_id}",
        f"  likes    {candidate.reply.get('like_count', 0):,}",
        "",
        "  They said:",
        "",
        "    " + str(candidate.reply.get("text", "")).replace("\n", "\n    "),
    ])


def render_config(configuration, api_key_resolved: bool, key_source: str) -> str:
    """Every effective setting and where it came from.

    Shows whether a key resolved, never the key. A settings dump is a thing
    operators paste into bug reports.
    """

    lines = ["Effective configuration", ""]
    width = max((len(name) for name, _ in configuration.items()), default=10)
    for name, entry in configuration.items():
        value = _safe_config_value(name, entry.value)
        shown = ", ".join(value) if isinstance(value, tuple) else value
        lines.append(f"  {name:<{width}}  {shown}   [{entry.source}]")
    lines.append("")
    lines.append(
        f"  {'api key':<{width}}  "
        f"{'resolved' if api_key_resolved else 'NOT FOUND'}   [{key_source}]"
    )
    return "\n".join(lines)
