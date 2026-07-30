"""Readable, separately copyable views of retrieved YouTube evidence."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from ...domain.video import format_timestamp, watch_url


def metadata_text(video: Mapping[str, Any]) -> str:
    """Render stable video facts without dumping adapter-only fields."""

    video_id = str(video.get("video_id") or "")
    rows = (
        ("Title", video.get("title")),
        ("URL", watch_url(video_id) if video_id else ""),
        ("Channel", video.get("channel_title")),
        ("Published", video.get("published_at")),
        ("Duration", _duration(video.get("duration_seconds"))),
        ("Views", _count(video.get("view_count"))),
        ("Likes", _count(video.get("like_count"))),
        ("Comments reported", _count(video.get("comment_count"))),
    )
    return "\n".join(
        f"{label}: {value}"
        for label, value in rows
        if value not in (None, "")
    )


def description_text(video: Mapping[str, Any]) -> str:
    return str(video.get("description") or "").strip()


def comments_text(comments: Iterable[Mapping[str, Any]]) -> str:
    return _items_text(comments, heading="Retrieved comments", reply=False)


def replies_text(replies: Iterable[Mapping[str, Any]]) -> str:
    return _items_text(replies, heading="Retrieved replies", reply=True)


def transcript_text(transcript: Any) -> str:
    entries = list(getattr(transcript, "entries", ()) or ())
    if not entries and isinstance(transcript, Mapping):
        entries = list(transcript.get("entries", ()) or ())
    lines = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        text = str(entry.get("text") or "").strip()
        if text:
            lines.append(
                f"[{format_timestamp(entry.get('start'))}] {text}"
            )
    return "\n".join(lines)


def _items_text(
    items: Iterable[Mapping[str, Any]],
    *,
    heading: str,
    reply: bool,
) -> str:
    values = list(items)
    lines = [f"# {heading}", "", f"Items retrieved: {len(values):,}"]
    for index, item in enumerate(values, 1):
        author = str(item.get("author") or "unknown author")
        likes = _count(item.get("like_count")) or "0"
        item_id = str(
            item.get("comment_id") or item.get("reply_id") or ""
        )
        replies = _count(item.get("total_reply_count"))
        suffix = f", {replies} replies" if replies and not reply else ""
        lines.extend([
            "",
            f"## {index}. {author} — {likes} likes{suffix}",
        ])
        if item_id:
            lines.append(f"ID: {item_id}")
        if reply and item.get("parent_comment_id"):
            lines.append(f"Parent comment ID: {item['parent_comment_id']}")
        lines.extend(["", str(item.get("text") or "").strip()])
    return "\n".join(lines).rstrip()


def _count(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return ""


def _duration(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return ""
    return format_timestamp(seconds) if seconds > 0 else ""
