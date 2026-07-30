"""Compact, human-readable receipts for completed GUI work."""

from __future__ import annotations

from typing import Any, Mapping


def transcript_notification(transcript: Mapping[str, Any] | Any) -> str:
    """One plain-language line for the persistent transcript status bar."""

    if isinstance(transcript, Mapping):
        get = transcript.get
    else:
        get = lambda name, default="": getattr(transcript, name, default)

    availability = getattr(
        get("availability", ""),
        "value",
        get("availability", ""),
    )
    availability = str(availability or "")
    source = str(get("source", "") or "")
    detail = " ".join(str(get("detail", "") or "").split())

    if availability == "available":
        if source == "whisper":
            return "Using a local Whisper transcript."
        if source == "saved-transcript":
            return (
                f"Using a previously saved transcript. {detail}".strip()
            )
        return f"Transcript found{f' via {source}' if source else ''}."

    labels = {
        "not_published": "No transcript was published for this video.",
        "not_public": (
            "The transcript is unavailable because the video or captions "
            "are not public."
        ),
        "language_unavailable": (
            "No transcript matched the requested language."
        ),
        "empty": "A caption track exists, but it contains no usable text.",
        "fetch_failed": "Transcript retrieval was blocked or failed.",
    }
    summary = labels.get(
        availability,
        "No usable transcript is available.",
    )
    if detail and detail.casefold() not in summary.casefold():
        return f"{summary} Reason: {detail}"
    return summary


def _transcript_note(transcript: Mapping[str, Any]) -> str:
    availability = str(transcript.get("availability") or "")
    detail = " ".join(str(transcript.get("detail") or "").split())
    if not detail or availability == "available":
        return ""
    return f"Transcript note: {detail[:500]}"


def comment_receipt(run: Mapping[str, Any], output: str = "") -> str:
    counts = run.get("counts", {}) if isinstance(run.get("counts"), dict) else {}
    transcript = (
        run.get("transcript", {})
        if isinstance(run.get("transcript"), dict)
        else {}
    )
    title = str(run.get("video_title") or run.get("video_id") or "Video")
    source = str(
        transcript.get("source")
        or transcript.get("availability")
        or "unknown transcript"
    )
    language = str(transcript.get("language") or "")
    transcript_text = f"{source}{f' ({language})' if language else ''}"
    packet_size = int(run.get("packet_characters") or 0)
    operations = int(
        run.get("api_operations_used")
        or run.get("requests_used")  # older saved run
        or 0
    )
    lines = [
        title,
        (
            f"{int(counts.get('comments') or 0):,} comments; "
            f"{int(counts.get('replies') or 0):,} replies; "
            f"transcript: {transcript_text}; "
            f"{operations:,} logical YouTube API operations; "
            f"{packet_size:,} packet characters"
        ),
    ]
    if output:
        lines.append(f"Saved in {output}")
    note = _transcript_note(transcript)
    if note:
        lines.append(note)
    return "\n".join(lines)


def reply_receipt(receipt: Mapping[str, Any]) -> str:
    video = receipt.get("video", {})
    if not isinstance(video, dict):
        video = {}
    transcript = receipt.get("transcript", {})
    if not isinstance(transcript, dict):
        transcript = {}
    title = str(video.get("title") or video.get("video_id") or "Video")
    source = str(
        transcript.get("source")
        or transcript.get("availability")
        or "unknown transcript"
    )
    language = str(transcript.get("language") or "")
    lines = [
        title,
        (
            f"{int(receipt.get('total') or 0):,} people found; "
            f"{int(receipt.get('waiting') or 0):,} waiting; "
            f"transcript: {source}{f' ({language})' if language else ''}; "
            f"{int(receipt.get('api_operations_used') or 0):,} logical "
            "YouTube API operations"
        ),
    ]
    output = str(receipt.get("output") or "")
    if output:
        lines.append(f"Saved in {output}")
    note = _transcript_note(transcript)
    if note:
        lines.append(note)
    return "\n".join(lines)
