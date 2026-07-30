"""Detect private state and credentials before files are published."""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PRIVATE_FILENAMES = frozenset({
    ".env",
    "comment_drafts.md",
    "engagement_history.sqlite3",
    "posted_history.json",
    "replies_to_review.md",
    "settings.json",
    "window_settings.json",
    "writing_presets.json",
    "youtube_packet_settings.json",
})

PERSONAL_NOTE_FILENAMES = frozenset({
    "BUILD_DESIGN_REQUEST_FOR_CLAUDE.md",
    "CHANGES_MADE.md",
    "FILES_CHANGED.txt",
    "HANDOFF.md",
    "OTHER_COMPUTER_FIX.txt",
    "PHASES.md",
    "REMAINING_UNVERIFIED.md",
    "TEST_RESULTS_AFTER.txt",
    "launcher_fix_for_other_computer.zip",
})

TEXT_SUFFIXES = frozenset({
    ".bat", ".cfg", ".ini", ".json", ".md", ".ps1", ".py", ".toml",
    ".txt", ".yaml", ".yml",
})

CONTENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("YouTube API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    (
        "YouTube channel ID",
        re.compile(r"\bUC[0-9A-Za-z_-]{22}\b"),
    ),
    (
        "credential-bearing URL",
        re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@"),
    ),
    (
        "Windows user directory",
        re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+(?!<)[A-Za-z0-9._-]+"),
    ),
    (
        "private key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
)


@dataclass(frozen=True)
class PrivacyFinding:
    path: str
    kind: str
    detail: str = ""
    line: int = 0


def audit_files(
    root: str | Path,
    relative_paths: Iterable[str | Path],
) -> tuple[PrivacyFinding, ...]:
    """Inspect the exact publishable file set supplied by the caller."""

    root = Path(root).resolve()
    findings: list[PrivacyFinding] = []
    for relative in relative_paths:
        relative = Path(relative)
        path = root / relative
        name = relative.name
        if name in PRIVATE_FILENAMES:
            findings.append(PrivacyFinding(
                str(relative), "private state file",
                "settings, drafts, or engagement history",
            ))
        if name in PERSONAL_NOTE_FILENAMES:
            findings.append(PrivacyFinding(
                str(relative), "personal project note",
                "not part of the distributable application",
            ))
        lowered_parts = {part.casefold() for part in relative.parts}
        if "local_notes" in lowered_parts:
            findings.append(PrivacyFinding(
                str(relative), "personal project note",
                "not part of the distributable application",
            ))
        if lowered_parts & {
            "output", "review_packages", "previous_runs", "ab_compare",
        }:
            findings.append(PrivacyFinding(
                str(relative), "generated or review material",
            ))
        if path.suffix.casefold() not in TEXT_SUFFIXES or not path.is_file():
            continue
        try:
            body = _read_candidate_text(path)
        except OSError as exc:
            findings.append(PrivacyFinding(
                str(relative),
                "unscannable text file",
                f"read failed ({type(exc).__name__})",
            ))
            continue
        except UnicodeError as exc:
            findings.append(PrivacyFinding(
                str(relative),
                "unscannable text file",
                f"decode failed ({type(exc).__name__})",
            ))
            continue
        for line_number, line in enumerate(body.splitlines(), 1):
            for kind, pattern in CONTENT_PATTERNS:
                match = pattern.search(line)
                if match:
                    findings.append(PrivacyFinding(
                        str(relative),
                        kind,
                        _safe_detail(match.group(0)),
                        line_number,
                    ))
    return tuple(findings)


def _read_candidate_text(path: Path) -> str:
    """Decode common Windows text encodings and fail closed otherwise."""

    raw = path.read_bytes()
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig")
    if raw.startswith(codecs.BOM_UTF16_LE):
        return raw.decode("utf-16-le")[1:]
    if raw.startswith(codecs.BOM_UTF16_BE):
        return raw.decode("utf-16-be")[1:]
    return raw.decode("utf-8")


def _safe_detail(value: str) -> str:
    """Identify the shape without echoing a discovered credential."""

    if value.startswith("AIza"):
        return f"{value[:4]}...{value[-4:]}"
    if "://" in value and "@" in value:
        return value.split("://", 1)[0] + "://[credentials]@..."
    if value.startswith("UC") and len(value) == 24:
        return f"{value[:4]}...{value[-4:]}"
    return value


def render_findings(findings: Iterable[PrivacyFinding]) -> str:
    rows = list(findings)
    if not rows:
        return "Privacy check passed: no private publishable files were found."
    lines = ["Privacy check failed:"]
    for finding in rows:
        location = f"{finding.path}:{finding.line}" if finding.line else finding.path
        detail = f" ({finding.detail})" if finding.detail else ""
        lines.append(f"- {location}: {finding.kind}{detail}")
    return "\n".join(lines)
