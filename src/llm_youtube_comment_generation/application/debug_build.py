"""Privacy-safe diagnostic material for an explicitly requested debug build."""

from __future__ import annotations

import json
from typing import Any, Mapping


DEBUG_PACKET_FILENAME = "debug_packet.md"
DEBUG_RESPONSE_FILENAME = "debug_model_response.md"
DEBUG_BUNDLE_FILENAME = "debug_bundle.md"


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
        "inside the Hardened final.",
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
) -> str:
    """Render one shareable record without secrets, local paths, or credentials."""

    sections = (
        ("Safe build settings", json.dumps(dict(settings), indent=2,
                                             ensure_ascii=False, sort_keys=True)),
        ("Run record", json.dumps(dict(run), indent=2, ensure_ascii=False,
                                    sort_keys=True)),
        ("Exact debug packet", packet_text.rstrip()),
        ("Complete model response", response_text.rstrip()),
        ("Saved Hardened final", draft.rstrip()),
    )
    lines = ["# Debug build bundle", ""]
    for heading, content in sections:
        lines.extend((f"## {heading}", "", content or "_Not available._", ""))
    return "\n".join(lines)
