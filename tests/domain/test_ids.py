"""Video and channel identity."""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.domain.errors import ConfigurationError
from llm_youtube_comment_generation.domain.ids import (
    extract_video_id,
    normalise_handle,
    validate_channel_id,
)

VIDEO = "gC-J7zwYMAM"


@pytest.mark.parametrize("value", [
    VIDEO,
    f"https://www.youtube.com/watch?v={VIDEO}",
    f"https://www.youtube.com/watch?v={VIDEO}&lc=UgxAbC",
    f"https://www.youtube.com/watch?v={VIDEO}&t=37s&list=PL123",
    f"https://youtu.be/{VIDEO}?si=abc123",
    f"https://m.youtube.com/watch?v={VIDEO}",
    f"https://music.youtube.com/watch?v={VIDEO}",
    f"https://www.youtube.com/shorts/{VIDEO}",
    f"https://www.youtube.com/embed/{VIDEO}",
    f"https://www.youtube.com/live/{VIDEO}",
    f"youtube.com/watch?v={VIDEO}",
    f"youtu.be/{VIDEO}",
    f"  <https://youtu.be/{VIDEO}>  ",
])
def test_extract_video_id_accepts(value):
    assert extract_video_id(value) == VIDEO


@pytest.mark.parametrize("value", [
    "",
    "   ",
    "not-video",             # 9 characters
    "way-too-long-for-an-id",
    "bad!chars!!",           # 11 characters, illegal alphabet
    "https://evil.example/?v=gC-J7zwYMAM",
    "https://www.youtube.com/watch?v=too-short",
    "https://www.youtube.com/",
    "https://youtu.be/",
])
def test_extract_video_id_rejects(value):
    with pytest.raises(ConfigurationError):
        extract_video_id(value)


def test_channel_id_passes_through_when_valid():
    channel = "UC" + "a" * 22
    assert validate_channel_id(channel) == channel
    assert validate_channel_id(f"  {channel}  ") == channel


@pytest.mark.parametrize("value", [
    "",
    "UC-too-short",
    "XX" + "a" * 22,
    "UC" + "a" * 21,
    "UC" + "a" * 23,
    "@handle",
])
def test_invalid_channel_id_is_rejected(value):
    with pytest.raises(ConfigurationError):
        validate_channel_id(value)


def test_handle_is_normalised():
    """Ported from test_handle_is_resolved_and_normalised.

    The legacy test covered normalisation and API resolution together. Only
    normalisation is a domain rule; resolution needs a YouTube port and is
    listed in NOT_PORTED.md as deferred to Phase 2.
    """

    assert normalise_handle("someone") == "@someone"
    assert normalise_handle("@someone") == "@someone"
    assert normalise_handle("  someone  ") == "@someone"

    with pytest.raises(ConfigurationError):
        normalise_handle("")
