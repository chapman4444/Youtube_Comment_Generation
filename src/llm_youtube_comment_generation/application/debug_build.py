"""Diagnostic material for an explicitly requested debug build.

The bundle carries the exact packet and the complete model response, because
a diagnostic that omitted them could not explain the build it describes. That
means it also carries the retained YouTube evidence inside the packet:
commenter display names, comment and reply text, the video description and
transcript text.

This module used to call that "privacy-safe" and "shareable". It is neither,
and the wording invited exactly the mistake it should have prevented, which is
attaching the file to a public bug report. tests/test_publishable.py states
the project's position on the same material plainly: those are real people's
names and words, and they are not ours to republish.

Redacting the evidence here was considered and rejected: it would leave a
diagnostic that cannot diagnose. The bundle stays complete and the labels now
say what it holds, so deciding to share it is a deliberate act rather than one
taken on a false assurance.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping


DEBUG_PACKET_FILENAME = "debug_packet.md"
DEBUG_RESPONSE_FILENAME = "debug_model_response.md"
DEBUG_REJECTED_RESPONSE_FILENAME = "debug_model_response_rejected.md"
DEBUG_BUNDLE_FILENAME = "debug_bundle.md"


def debug_report_problem(text: str) -> str:
    """Return a precise failure when a diagnostic response omits its report."""

    body = str(text or "").replace("\r\n", "\n")
    report = list(re.finditer(r"(?im)^###\s+debug\s+report\s*$", body))
    final = list(re.finditer(r"(?im)^###\s+hardened\s+final\s*$", body))
    if len(report) != 1:
        return (
            "A Debug build requires exactly one '### Debug report' section "
            "before '### Hardened final'."
        )
    if not final or report[0].start() > final[-1].start():
        return (
            "The Debug report must appear before '### Hardened final', which "
            "must remain the final section."
        )
    return ""


def render_debug_packet(
    packet_text: str,
    *,
    settings: Mapping[str, Any],
    run: Mapping[str, Any],
) -> str:
    """Add a diagnostic instruction without changing the normal final contract."""

    return "\n".join((
        packet_text.rstrip(),
        "",
        "---",
        "",
        "## Debug-build instructions",
        "",
        "This is a diagnostic build. Complete every normal instruction in this "
        "packet. In addition, place one `### Debug report` section immediately "
        "before `### Hardened final`. The Hardened final must remain the last "
        "section and must still be a ready-to-post comment.",
        "",
        "In the Debug report, state briefly:",
        "- whether the required Video line is exact and contains one plain URL;",
        "- any evidence, attribution, or uncertainty concerns;",
        "- whether the proposed variations are genuinely distinct;",
        "- any packet truncation, missing-evidence, or instruction conflict you see;",
        "- the specific change that would most improve the next build.",
        "",
        "The Debug report is for the developer, not for posting. Do not put it "
        "inside the Hardened final. It is mandatory: an answer without exactly "
        "one `### Debug report` before `### Hardened final` will be rejected.",
        "",
        "## Safe debug context",
        "",
        "```json",
        json.dumps({
            "settings": dict(settings),
            "run": {
                "video_id": run.get("video_id", ""),
                "video_title": run.get("video_title", ""),
                "variations": run.get("variations", []),
                "dials": run.get("dials", {}),
                "packet_characters": run.get("packet_characters", 0),
                "budget": run.get("budget", 0),
                "retrieval": run.get("retrieval", {}),
                "transcript": run.get("transcript", {}),
                "warnings": run.get("warnings", []),
            },
        }, indent=2, ensure_ascii=False, sort_keys=True),
        "```",
        "",
    ))


def render_debug_bundle(
    *,
    settings: Mapping[str, Any],
    run: Mapping[str, Any],
    packet_text: str,
    response_text: str,
    draft: str,
    rejection_reason: str = "",
) -> str:
    """Render one diagnostic record, complete enough to explain the build.

    It holds no credentials, no local paths and no settings beyond the safe
    set. It does hold the exact packet and the complete model response, so it
    also holds the retained YouTube evidence those contain. Review it before
    sending it anywhere.
    """

    sections = (
        ("Safe build settings", json.dumps(dict(settings), indent=2,
                                             ensure_ascii=False, sort_keys=True)),
        ("Run record", json.dumps(dict(run), indent=2, ensure_ascii=False,
                                    sort_keys=True)),
        ("Exact debug packet", packet_text.rstrip()),
        ("Complete model response", response_text.rstrip()),
        ("Response status", rejection_reason or "Accepted."),
        ("Saved Hardened final", draft.rstrip()),
    )
    # Stated in the file itself, not only in the interface that produced it.
    # The bundle is what gets attached to a bug report, and by then whatever
    # the window said is long out of view.
    lines = [
        "# Debug build bundle",
        "",
        "> **Review before sharing.** This bundle is unredacted. It contains "
        "the exact packet and the complete model response, and therefore the "
        "retained YouTube evidence inside them: commenter display names, "
        "comment and reply text, the video description and transcript text. "
        "It contains no credentials and no local paths.",
        "",
    ]
    for heading, content in sections:
        lines.extend((f"## {heading}", "", content or "_Not available._", ""))
    return "\n".join(lines)
