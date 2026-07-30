"""Inspecting runs after the fact.

The goal this serves is stated in the plan as an acceptance test: a failing
run can be diagnosed from artifacts alone. That means the run directory has
to answer, without the operator re-running anything: what was asked for, what
came back, what the packet was built from, and which of those went wrong.

``validate`` reports problems; it never repairs. A command that quietly fixed
a broken run would destroy the evidence of what broke.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.statuses import TranscriptAvailability
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
MAX_RECORDED_INTEGER = (1 << 63) - 1
COMPLETION_MARKER = ".artifacts-complete.json"


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
        "rebuild": COMMENT_ARTIFACTS,
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
    empty_files = {
        name for name in files if (directory / name).stat().st_size == 0
    }
    for name in sorted(empty_files - {"transcript_timestamped.txt"}):
        summary.problems.append(f"{name} is empty")

    if "run.json" in names:
        try:
            parsed = json.loads(
                (directory / "run.json").read_text(encoding="utf-8")
            )
        except ValueError as exc:
            summary.problems.append(f"run.json is not valid JSON: {exc}")
        else:
            if not isinstance(parsed, dict):
                summary.problems.append(
                    "run.json must contain an object at its top level"
                )
            else:
                summary.run = parsed
                recorded_kind = summary.run.get("kind")
                if isinstance(recorded_kind, str) and \
                        expected_for(recorded_kind):
                    summary.kind = recorded_kind
                summary.video_id = str(summary.run.get("video_id", ""))
                summary.video_title = str(summary.run.get("video_title", ""))
                summary.prompt_version = str(
                    summary.run.get("prompt_version", "")
                )
                recorded = _bounded_integer(
                    summary.run, "packet_characters", summary.problems,
                )
                budget = _bounded_integer(
                    summary.run, "budget", summary.problems,
                )
                summary.characters = recorded or 0
                summary.problems.extend(_check_record(
                    summary.run,
                    directory,
                    names,
                    recorded_characters=recorded,
                    budget=budget,
                ))
                if summary.run.get("artifact_contract_version") == 2:
                    summary.problems.extend(
                        _check_completion_record(directory, names)
                    )

    if summary.kind == "unknown":
        summary.kind = classify(names)

    if summary.kind == "unknown":
        summary.problems.append(
            "no packet or review file, so this directory is not a run this "
            "tool produced"
        )

    for expected in expected_for(summary.kind):
        if expected not in names:
            summary.problems.append(f"missing {expected}")

    if "transcript_timestamped.txt" in empty_files:
        if not _allows_empty_transcript(summary.kind, summary.run):
            summary.problems.append("transcript_timestamped.txt is empty")

    return summary


def _check_completion_record(
    directory: Path,
    names: set[str],
) -> list[str]:
    """A version-two run is complete only when its final manifest validates."""

    if COMPLETION_MARKER not in names:
        return [
            f"missing {COMPLETION_MARKER}; this run was not fully published"
        ]
    try:
        record = json.loads(
            (directory / COMPLETION_MARKER).read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        return [f"{COMPLETION_MARKER} is invalid: {exc}"]
    if not isinstance(record, dict) or record.get("version") != 1:
        return [f"{COMPLETION_MARKER} has an unsupported format"]
    expected = record.get("files")
    if not isinstance(expected, dict) or not all(
        isinstance(name, str) and isinstance(digest, str)
        for name, digest in expected.items()
    ):
        return [f"{COMPLETION_MARKER} has an invalid files table"]

    actual_names = names - {COMPLETION_MARKER}
    expected_names = set(expected)
    problems: list[str] = []
    missing = sorted(expected_names - actual_names)
    unrecorded = sorted(actual_names - expected_names)
    if missing:
        problems.append(
            f"{COMPLETION_MARKER} names missing files: {', '.join(missing)}"
        )
    if unrecorded:
        problems.append(
            f"{COMPLETION_MARKER} omits files: {', '.join(unrecorded)}"
        )
    for name in sorted(expected_names & actual_names):
        digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if digest != expected[name]:
            problems.append(
                f"{name} does not match {COMPLETION_MARKER}"
            )
    return problems


def _bounded_integer(
    run: dict[str, Any],
    field: str,
    problems: list[str],
) -> int | None:
    """Read one untrusted integer field without letting it abort validation."""

    if field not in run:
        return None
    value = run[field]
    converted: int | None = None
    if isinstance(value, int) and not isinstance(value, bool):
        converted = value
    elif isinstance(value, str):
        text = value.strip()
        digits = text[1:] if text.startswith("+") else text
        if digits and len(digits) <= 19 and digits.isdigit():
            converted = int(text)

    if converted is None or not 0 <= converted <= MAX_RECORDED_INTEGER:
        shown = repr(value)
        if len(shown) > 80:
            shown = shown[:77] + "..."
        problems.append(
            f"run.json field {field} must be an integer from 0 through "
            f"{MAX_RECORDED_INTEGER:,}; got {shown}"
        )
        return None
    return converted


def _allows_empty_transcript(kind: str, run: dict[str, Any]) -> bool:
    """Only an explicitly recorded unavailable comment transcript is empty."""

    if kind not in {"comment", "rebuild"}:
        return False
    transcript = run.get("transcript")
    if not isinstance(transcript, dict):
        return False
    unavailable = {
        state.value for state in TranscriptAvailability
        if state is not TranscriptAvailability.AVAILABLE
    }
    availability = transcript.get("availability")
    return isinstance(availability, str) and availability in unavailable


def _check_record(
    run: dict[str, Any],
    directory: Path,
    names: set[str],
    *,
    recorded_characters: int | None,
    budget: int | None,
) -> list[str]:
    """Cross-check the recorded decisions against the artifacts beside them."""

    problems: list[str] = []

    if not run.get("prompt_version"):
        problems.append(
            "run.json records no prompt_version, so this packet cannot be "
            "attributed to the prompt that produced it"
        )

    if "packet.md" in names:
        actual = len((directory / "packet.md").read_text(encoding="utf-8"))
        if recorded_characters and abs(actual - recorded_characters) > 1:
            problems.append(
                f"run.json says the packet is {recorded_characters:,} "
                "characters but "
                f"packet.md is {actual:,}"
            )
        if budget and actual > budget:
            problems.append(
                f"packet.md is {actual:,} characters, over the {budget:,} "
                "budget it recorded"
            )

    retrieval = run.get("retrieval")
    if retrieval is not None and not isinstance(retrieval, dict):
        problems.append(
            "run.json field retrieval must be an object"
        )
    elif isinstance(retrieval, dict):
        if retrieval.get("may_conclude_absence") is True and \
                retrieval.get("status") not in (None, "complete"):
            problems.append(
                "run.json claims absence may be concluded while retrieval was "
                f"{retrieval.get('status')!r}; those cannot both be true"
            )

    variations = run.get("variations")
    headings = run.get("variation_headings")
    dials = run.get("dials")
    variations_ok = (
        variations is None
        or isinstance(variations, list)
        and all(isinstance(value, str) for value in variations)
    )
    headings_ok = (
        headings is None
        or isinstance(headings, list)
        and all(isinstance(value, str) for value in headings)
    )
    dials_ok = dials is None or isinstance(dials, dict)
    if not variations_ok:
        problems.append("run.json field variations must be a list of strings")
    if not headings_ok:
        problems.append(
            "run.json field variation_headings must be a list of strings"
        )
    if not dials_ok:
        problems.append("run.json field dials must be an object")

    variation_values = variations or [] if variations_ok else []
    heading_values = headings or [] if headings_ok else []
    dial_values = dials or {} if dials_ok else {}
    if variation_values and variations_ok and headings_ok and dials_ok:
        try:
            expected_headings = resolve_prompt_spec(
                variation_values, dial_values,
            ).headings
        except Exception as exc:
            problems.append(
                "run.json prompt fields could not be resolved: "
                f"{type(exc).__name__}: {exc}"
            )
        else:
            if heading_values and tuple(heading_values) != expected_headings:
                problems.append(
                    f"{len(variation_values)} registers were asked for but "
                    "the recorded headings do not match the resolved prompt "
                    "contract; the contract disagreed with itself"
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
