"""The failure hierarchy and the exit code each maps to.

Ported unchanged from the legacy pipeline. The exit codes are a published
contract: a caller scripting this tool branches on them.
"""

from __future__ import annotations

import json
import re
from typing import Any

# 0, 1, 2, 3 and 130 are carried over from the legacy application unchanged:
# they are a published contract and a caller scripting this tool branches on
# them. 4 and 5 split two cases the legacy collapsed into 1, because "the
# packet did not fit" and "the packet was built wrong" call for different
# actions and were indistinguishable to a script.
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_QUOTA = 2
EXIT_CONFIGURATION = 3
EXIT_PACKET_TOO_LARGE = 4
EXIT_VALIDATION = 5
EXIT_CANCELLED = 130


class PacketError(RuntimeError):
    """Base class for every failure this application reports to the user."""

    exit_code = EXIT_ERROR


class ConfigurationError(PacketError):
    """Raised when the run cannot start because of user-supplied settings."""

    exit_code = EXIT_CONFIGURATION


class OperationCancelled(PacketError):
    """Raised when the caller cancels an in-progress run."""

    exit_code = EXIT_CANCELLED


class PacketTooLargeError(PacketError):
    """Raised when protected content cannot fit inside the character budget."""

    exit_code = EXIT_PACKET_TOO_LARGE


class ValidationError(PacketError):
    """Raised when an assembled packet fails its own structural checks.

    Distinct from PacketTooLargeError: this means a forged evidence boundary,
    an unfilled placeholder, or a missing protected section — the packet was
    built wrong, not merely built too big. Shipping it would put prompt text
    or unneutralised evidence in front of a model.
    """

    exit_code = EXIT_VALIDATION


class HistoryCorruptionError(PacketError):
    """Raised rather than writing over a history file that cannot be read."""


class YouTubeAPIError(PacketError):
    """Raised for structured errors returned by the YouTube Data API."""

    def __init__(self, resource: str, status_code: int, payload: Any) -> None:
        self.resource = resource
        self.status_code = status_code
        self.payload = payload if isinstance(payload, dict) else {}
        self.reasons = _google_error_reasons(self.payload)
        super().__init__(
            f"YouTube API error for {resource}: HTTP {status_code}: "
            f"{_google_error_message(self.payload)}"
        )


class QuotaExceededError(YouTubeAPIError):
    """Raised when the API key has no quota left."""

    exit_code = EXIT_QUOTA


class CommentsDisabledError(YouTubeAPIError):
    """Raised when a video has comments turned off."""


QUOTA_REASONS = frozenset({
    "quotaexceeded",
    "dailylimitexceeded",
    "ratelimitexceeded",
    "userratelimitexceeded",
})
COMMENTS_DISABLED_REASONS = frozenset({"commentsdisabled"})


def _normalize_reason(reason: str) -> str:
    return re.sub(r"[^a-z]", "", str(reason).casefold())


def _google_error_reasons(payload: dict[str, Any]) -> frozenset[str]:
    error = payload.get("error")
    if not isinstance(error, dict):
        return frozenset()
    reasons: set[str] = set()
    for key in ("errors", "details"):
        entries = error.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("reason"):
                reasons.add(str(entry["reason"]))
    return frozenset(reasons)


def _google_error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if not isinstance(error, dict):
        return json.dumps(payload, ensure_ascii=False)[:400]
    message = str(error.get("message") or "").strip()
    reasons = sorted(_google_error_reasons(payload))
    if reasons and message:
        return f"{', '.join(reasons)}: {message}"
    return ", ".join(reasons) or message or "unspecified error"


def classify_api_error(
    resource: str,
    status_code: int,
    payload: Any,
) -> YouTubeAPIError:
    """Return the most specific error class for a Google API error payload."""

    normalized = {
        _normalize_reason(reason)
        for reason in _google_error_reasons(
            payload if isinstance(payload, dict) else {}
        )
    }
    if normalized & QUOTA_REASONS:
        return QuotaExceededError(resource, status_code, payload)
    if normalized & COMMENTS_DISABLED_REASONS:
        return CommentsDisabledError(resource, status_code, payload)
    return YouTubeAPIError(resource, status_code, payload)
