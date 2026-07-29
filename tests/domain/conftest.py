"""Builders for the domain tests.

The legacy suites built these dictionaries inline in dozens of tests, which is
why a shape change there meant editing dozens of tests. Building them in one
place is a porting adaptation, not a change of intent.
"""

from __future__ import annotations

from typing import Any

import pytest

OWNER_CHANNEL = "UC" + "o" * 22


@pytest.fixture
def owner_channel() -> str:
    return OWNER_CHANNEL


def channel_for(handle: str) -> str:
    """A deterministic, correctly shaped channel ID for a handle."""

    return ("UC" + handle.lstrip("@").ljust(22, "z"))[:24]


@pytest.fixture
def reply():
    def build(
        comment_id: str,
        author: str,
        text: str,
        published_at: str,
        *,
        likes: int = 0,
        channel_id: str | None = None,
        parent: str = "",
    ) -> dict[str, Any]:
        record = {
            "comment_id": comment_id,
            "author": author,
            "author_channel_id": (
                channel_id if channel_id is not None else channel_for(author)
            ),
            "text": text,
            "published_at": published_at,
            "updated_at": published_at,
            "like_count": likes,
        }
        if parent:
            record["parent_comment_id"] = parent
        return record

    return build


@pytest.fixture
def comment():
    def build(
        comment_id: str,
        *,
        likes: int = 0,
        replies: int = 0,
        published_at: str = "2026-01-01T00:00:00Z",
        text: str = "a comment body",
        author: str = "@someone",
    ) -> dict[str, Any]:
        return {
            "comment_id": comment_id,
            "author": author,
            "author_channel_id": channel_for(author),
            "text": text,
            "like_count": likes,
            "total_reply_count": replies,
            "published_at": published_at,
            "updated_at": published_at,
        }

    return build
