"""Comment parsing, deduplication, and the orderings the packet renders."""

from __future__ import annotations

import html
import re
from typing import Any, Iterable, Sequence

from .video import as_int


def clean_comment_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_comment_item(
    resource: dict[str, Any],
    *,
    parent_id: str | None = None,
    order_source: str | None = None,
) -> dict[str, Any]:
    snippet = resource.get("snippet") or {}
    author_channel = snippet.get("authorChannelId")
    return {
        "comment_id": resource.get("id", ""),
        "parent_comment_id": parent_id or snippet.get("parentId"),
        "author": snippet.get("authorDisplayName", ""),
        "author_channel_url": snippet.get("authorChannelUrl", ""),
        "author_channel_id": (
            author_channel.get("value")
            if isinstance(author_channel, dict)
            else None
        ),
        "text": clean_comment_text(
            snippet.get("textOriginal") or snippet.get("textDisplay") or ""
        ),
        "like_count": as_int(snippet.get("likeCount")) or 0,
        "published_at": snippet.get("publishedAt", ""),
        "updated_at": snippet.get("updatedAt", ""),
        "viewer_rating": snippet.get("viewerRating", ""),
        "order_source": order_source,
        "is_reply": parent_id is not None,
    }


def merge_comments(
    groups: Iterable[Iterable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Deduplicate comments by ID, keeping the newest text and largest counts."""

    merged: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    for group in groups:
        for comment in group:
            comment_id = comment.get("comment_id") or ""
            if not comment_id:
                continue

            existing = by_id.get(comment_id)
            if existing is None:
                stored = dict(comment)
                source = stored.get("order_source")
                stored["order_sources"] = [source] if source else []
                by_id[comment_id] = stored
                merged.append(stored)
                continue

            source = comment.get("order_source")
            if source and source not in existing["order_sources"]:
                existing["order_sources"].append(source)

            for key in ("like_count", "total_reply_count"):
                existing[key] = max(
                    as_int(existing.get(key)) or 0,
                    as_int(comment.get(key)) or 0,
                )

            if str(comment.get("updated_at") or "") > str(
                existing.get("updated_at") or ""
            ):
                for key in ("text", "updated_at", "author", "viewer_rating"):
                    if comment.get(key):
                        existing[key] = comment[key]

            for key, value in comment.items():
                if key == "order_sources":
                    continue
                if value not in (None, "", []) and existing.get(key) in (None, "", []):
                    existing[key] = value

    return merged


def rank_replies_by_likes(
    replies: Sequence[dict[str, Any]],
    keep: int,
) -> list[dict[str, Any]]:
    """Keep the most-liked replies from a fetched thread window.

    The YouTube comments endpoint returns replies in ascending publish order,
    so the first page of a busy thread is its oldest replies. On one measured
    video the top thread had 178 replies and every displayed reply came from
    the publication date, hiding nine days of subsequent argument. Ranking the
    fetched window by likes puts the replies people actually responded to in
    front of the reader.
    """

    if keep <= 0:
        return []
    return sorted(
        replies,
        key=lambda reply: (
            as_int(reply.get("like_count")) or 0,
            str(reply.get("published_at") or ""),
        ),
        reverse=True,
    )[:keep]


def select_reply_parents(
    comments: Sequence[dict[str, Any]],
    maximum_threads: int,
) -> list[dict[str, Any]]:
    candidates = [
        comment
        for comment in comments
        if (as_int(comment.get("total_reply_count")) or 0) > 0
        and comment.get("comment_id")
    ]
    candidates.sort(
        key=lambda comment: (
            as_int(comment.get("total_reply_count")) or 0,
            as_int(comment.get("like_count")) or 0,
            str(comment.get("published_at") or ""),
        ),
        reverse=True,
    )
    return candidates[:maximum_threads]
