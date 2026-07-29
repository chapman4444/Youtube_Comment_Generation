"""Video facts parsed out of an API resource."""

from __future__ import annotations

import re
from typing import Any

from .sanitize import safe_token


def watch_url(video_id) -> str:
    """The canonical watch URL for a video, or "unknown".

    The packet carried every other fact about the video and not the one that
    identifies it. Reading a packet, or an answer written from one, there was
    no way back to the video without the run directory's name — and a packet
    is the thing that gets pasted somewhere else.

    The ID is allowlisted before it goes in. A URL invites a click, so it is
    assembled here from characters that cannot carry anything but an ID.
    """

    identifier = safe_token(video_id or "")
    if not video_id or identifier == "unknown":
        return "unknown"
    return f"https://www.youtube.com/watch?v={identifier}"


def as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_duration(duration: str) -> int | None:
    if not duration:
        return None
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
        r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?",
        duration,
    )
    if not match:
        return None
    return int(
        int(match.group("days") or 0) * 86_400
        + int(match.group("hours") or 0) * 3_600
        + int(match.group("minutes") or 0) * 60
        + float(match.group("seconds") or 0)
    )


def parse_video_item(video_id: str, item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("snippet") or {}
    content = item.get("contentDetails") or {}
    statistics = item.get("statistics") or {}
    status = item.get("status") or {}
    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "channel_id": snippet.get("channelId", ""),
        "channel_title": snippet.get("channelTitle", ""),
        "published_at": snippet.get("publishedAt", ""),
        "category_id": snippet.get("categoryId", ""),
        "default_language": snippet.get("defaultLanguage"),
        "default_audio_language": snippet.get("defaultAudioLanguage"),
        "tags": snippet.get("tags", []),
        "thumbnails": snippet.get("thumbnails", {}),
        "duration_iso8601": content.get("duration", ""),
        "duration_seconds": parse_duration(content.get("duration", "")),
        "definition": content.get("definition", ""),
        "caption_declared": content.get("caption", ""),
        "licensed_content": content.get("licensedContent"),
        "projection": content.get("projection", ""),
        "view_count": as_int(statistics.get("viewCount")),
        "like_count": as_int(statistics.get("likeCount")),
        "comment_count": as_int(statistics.get("commentCount")),
        "privacy_status": status.get("privacyStatus", ""),
        "embeddable": status.get("embeddable"),
        "made_for_kids": status.get("madeForKids"),
    }


def format_timestamp(seconds: float | int | None) -> str:
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3_600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
