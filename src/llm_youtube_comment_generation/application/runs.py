"""Inspecting runs after the fact.

The goal this serves is stated in the plan as an acceptance test: a failing
run can be diagnosed from artifacts alone. That means the run directory has
to answer, without the operator re-running anything: what was asked for, what
came back, what the packet was built from, and which of those went wrong.

``validate`` reports problems; it never repairs. A command that quietly fixed
a broken run would destroy the evidence of what broke.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.writing_options import resolve_prompt_spec

# What a completed comment run should contain. A missing file is a finding,
# not an error: an interrupted run is exactly the thing being diagnosed.
COMMENT_ARTIFACTS = (
    "packet.md", "run.json", "report.md", "evidence.json",
    "transcript_timestamped.txt",
)
# run.json is required of every kind. Without it a run is a directory of
# markdown with no way to say which prompt version produced it, which is
# exactly the question asked when something looks wrong.
REPLY_ARTIFACTS = ("reply_packet.md", "run.json")
GUIDED_ARTIFACTS = ("replies_to_review.md", "run.json")
TRIAGE_ARTIFACTS = ("reply_triage_packet.md", "run.json")


@dataclass
class RunSummary:
    directory: str = ""
    video_id: str = ""
    video_title: str = ""
    kind: str = "unknown"
    prompt_version: str = ""
    characters: int = 0
    files: tuple[str, ...] = ()
    problems: list[str] = field(default_factory=list)
    run: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems


def classify(names: set[str]) -> str:
    if "replies_to_review.md" in names:
        return "guided"
    if "reply_packet.md" in names:
        return "reply"
    if "reply_triage_packet.md" in names:
        return "triage"
    if "packet.md" in names:
        return "comment"
    return "unknown"


def expected_for(kind: str) -> tuple[str, ...]:
    return {
        "comment": COMMENT_ARTIFACTS,
        "reply": REPLY_ARTIFACTS,
        "guided": GUIDED_ARTIFACTS,
        "triage": TRIAGE_ARTIFACTS,
    }.get(kind, ())


def validate_run(directory: Path | str) -> RunSummary:
    """Report everything wrong with one run directory."""

    directory = Path(directory)
    summary = RunSummary(directory=str(directory))

    if not directory.is_dir():
        summary.problems.append(f"{directory} is not a directory")
        return summary

    files = sorted(entry.name for entry in directory.iterdir() if entry.is_file())
    summary.files = tuple(files)
    names = set(files)
    summary.kind = classify(names)

    if summary.kind == "unknown":
        summary.problems.append(
            "no packet or review file, so this directory is not a run this "
            "tool produced"
        )

    for expected in expected_for(summary.kind):
        if expected not in names:
            summary.problems.append(f"missing {expected}")

    for name in files:
        if (directory / name).stat().st_size == 0:
            summary.problems.append(f"{name} is empty")

    if "run.json" in names:
        try:
            summary.run = json.loads(
                (directory / "run.json").read_text(encoding="utf-8")
            )
        except ValueError as exc:
            summary.problems.append(f"run.json is not valid JSON: {exc}")
        else:
            summary.video_id = str(summary.run.get("video_id", ""))
            summary.video_title = str(summary.run.get("video_title", ""))
            summary.prompt_version = str(summary.run.get("prompt_version", ""))
            summary.characters = int(summary.run.get("packet_characters") or 0)
            summary.problems.extend(_check_record(summary.run, directory, names))

    return summary


def _check_record(run: dict[str, Any], directory: Path, names: set[str]) -> list[str]:
    """Cross-check the recorded decisions against the artifacts beside them."""

    problems: list[str] = []

    if not run.get("prompt_version"):
        problems.append(
            "run.json records no prompt_version, so this packet cannot be "
            "attributed to the prompt that produced it"
        )

    if "packet.md" in names:
        actual = len((directory / "packet.md").read_text(encoding="utf-8"))
        recorded = int(run.get("packet_characters") or 0)
        if recorded and abs(actual - recorded) > 1:
            problems.append(
                f"run.json says the packet is {recorded:,} characters but "
                f"packet.md is {actual:,}"
            )
        budget = int(run.get("budget") or 0)
        if budget and actual > budget:
            problems.append(
                f"packet.md is {actual:,} characters, over the {budget:,} "
                "budget it recorded"
            )

    retrieval = run.get("retrieval") or {}
    if retrieval.get("may_conclude_absence") is True and \
            retrieval.get("status") not in (None, "complete"):
        problems.append(
            f"run.json claims absence may be concluded while retrieval was "
            f"{retrieval.get('status')!r}; those cannot both be true"
        )

    variations = run.get("variations") or []
    headings = run.get("variation_headings") or []
    expected_headings = resolve_prompt_spec(
        variations, run.get("dials") or {}
    ).headings if variations else ()
    if variations and headings and tuple(headings) != expected_headings:
        problems.append(
            f"{len(variations)} registers were asked for but "
            "the recorded headings do not match the resolved prompt contract; "
            "the contract disagreed with itself"
        )

    return problems


def list_runs(root: Path | str) -> list[RunSummary]:
    """Every run under a directory, newest first."""

    root = Path(root)
    if not root.is_dir():
        return []
    summaries = [
        validate_run(entry) for entry in sorted(root.iterdir()) if entry.is_dir()
    ]
    return list(reversed(summaries))


def render_list(summaries: list[RunSummary]) -> str:
    if not summaries:
        return "No runs found."
    lines = [f"{len(summaries)} runs", ""]
    for summary in summaries:
        marker = "ok" if summary.ok else "!!"
        title = summary.video_title or summary.video_id or "(unknown video)"
        lines.append(
            f"  {marker} {Path(summary.directory).name}  {summary.kind:<7} "
            f"{title[:44]}"
        )
        for problem in summary.problems:
            lines.append(f"       {problem}")
    return "\n".join(lines)


def render_validation(summary: RunSummary) -> str:
    lines = [
        f"Run: {summary.directory}",
        f"  kind      {summary.kind}",
        f"  video     {summary.video_title or summary.video_id or 'unknown'}",
        f"  prompt    {summary.prompt_version or 'not recorded'}",
        f"  files     {', '.join(summary.files) or 'none'}",
        "",
    ]
    if summary.ok:
        lines.append("  No problems found.")
    else:
        lines.append(f"  {len(summary.problems)} problems:")
        lines.extend(f"    - {problem}" for problem in summary.problems)
    return "\n".join(lines)
