"""Video and channel identity.

Identity is a domain rule, not a transport concern: what counts as the same
person is the thing the answered-state reconstruction is built on, and it is
the channel ID rather than the display name because display names change.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .errors import ConfigurationError

YOUTUBE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_PATTERN = re.compile(r"^UC[A-Za-z0-9_-]{22}$")

YOUTUBE_HOSTS = frozenset({
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "gaming.youtube.com",
})
YOUTU_BE_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
YOUTUBE_PATH_PREFIXES = frozenset({"shorts", "embed", "live", "v"})


def extract_video_id(video: str) -> str:
    """Return the 11-character video ID from an ID or any YouTube URL form."""

    value = (video or "").strip().strip("<>").strip()
    if not value:
        raise ConfigurationError("A YouTube video URL or video ID is required.")

    if YOUTUBE_ID_PATTERN.fullmatch(value):
        return value

    if "://" not in value:
        host = value.split("/", 1)[0].split("?", 1)[0].lower()
        if host in YOUTUBE_HOSTS or host in YOUTU_BE_HOSTS:
            value = "https://" + value

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()

    if hostname in YOUTU_BE_HOSTS:
        candidate = parsed.path.strip("/").split("/")[0]
        if YOUTUBE_ID_PATTERN.fullmatch(candidate):
            return candidate
        raise ConfigurationError(f"Invalid youtu.be video URL: {video}")

    if hostname in YOUTUBE_HOSTS:
        if parsed.path.rstrip("/") in ("/watch", "/watch_popup"):
            candidate = parse_qs(parsed.query).get("v", [""])[0]
            if YOUTUBE_ID_PATTERN.fullmatch(candidate):
                return candidate

        parts = [part for part in parsed.path.split("/") if part]
        if (
            len(parts) >= 2
            and parts[0].lower() in YOUTUBE_PATH_PREFIXES
            and YOUTUBE_ID_PATTERN.fullmatch(parts[1])
        ):
            return parts[1]

        raise ConfigurationError(
            f"That YouTube URL does not contain a valid video ID: {video}"
        )

    raise ConfigurationError(
        "Enter an 11-character YouTube video ID or a URL from youtube.com or "
        "youtu.be."
    )


YOUTUBE_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:[A-Za-z0-9-]+\.)?(?:youtube\.com|youtu\.be)"
    r"/[^\s<>\"'`\)\]}]+",
    re.IGNORECASE,
)


def find_video_reference(text: str) -> str:
    """Find a video ID inside arbitrary pasted text, or return "".

    Written for a clipboard, which rarely holds exactly one tidy URL. It may
    hold a URL with tracking parameters, a line copied out of a chat, or a
    whole page of prose with the link somewhere in it.

    A bare 11-character ID is accepted only when it is the entire text.
    Loose in prose it would be a menace: ``Republicans`` is eleven characters
    of `[A-Za-z0-9_-]` and so is any number of ordinary words. Requiring the
    whole clipboard keeps the bare form usable without guessing.

    Returns "" rather than raising. Nothing was asked for and nothing was
    found; that is a question for the caller, not an error here.
    """

    value = (text or "").strip()
    if not value:
        return ""

    if YOUTUBE_ID_PATTERN.fullmatch(value):
        return value

    for match in YOUTUBE_URL_PATTERN.finditer(value):
        try:
            return extract_video_id(match.group(0))
        except ConfigurationError:
            continue        # a channel or playlist link; keep looking
    return ""


def validate_channel_id(channel_id: str) -> str:
    """Check a supplied channel ID's shape.

    The legacy ``resolve_channel_id`` also turned a handle into an ID, which
    needs the API. That half belongs to the application layer; only the
    validation rule is a domain fact, so only it lives here.
    """

    candidate = (channel_id or "").strip()
    if not candidate:
        raise ConfigurationError(
            "Reply mode requires a channel ID or a handle."
        )
    if CHANNEL_ID_PATTERN.fullmatch(candidate):
        return candidate
    raise ConfigurationError(
        "Invalid channel ID. Expected UC followed by 22 characters, got: "
        f"{channel_id}"
    )


def normalise_handle(handle: str) -> str:
    """A handle with exactly one leading ``@``, ready for a ``forHandle`` query."""

    wanted = (handle or "").strip()
    if not wanted:
        raise ConfigurationError(
            "Reply mode requires a channel ID or a handle."
        )
    return wanted if wanted.startswith("@") else "@" + wanted
