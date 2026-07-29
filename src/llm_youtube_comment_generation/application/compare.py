"""Comparing a packet from the rebuild against one from the old application.

A checksum proves the prompt text did not change. It does not prove the text
was assembled in the right order, with the right counts, under the right
headings — and that is where a rebuild degrades silently. So this diffs the
*instruction region* of two packets and shows every difference for a human to
judge.

Only the instruction region. The evidence region legitimately differs between
two runs: comments arrive, likes change, and a transcript may be sampled
differently. Diffing the whole packet would bury the differences that matter
under hundreds that do not.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

BOUNDARY_OPEN = "## BEGIN UNTRUSTED SOURCE MATERIAL"
BOUNDARY_CLOSE = "## END UNTRUSTED SOURCE MATERIAL"

def changed_lines(diff: list[str]) -> list[str]:
    """The real +/- lines, ignoring headers and context."""

    return [
        line for line in diff
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def only_whitespace(diff: list[str]) -> bool:
    """Whether every change is blank-line placement.

    Worth separating. Two packets whose instructions differ only in where a
    blank line falls ask the model for exactly the same thing, and reporting
    that as a difference alongside a real one would train the operator to
    skim past both.
    """

    changes = changed_lines(diff)
    return bool(changes) and all(not line[1:].strip() for line in changes)


@dataclass
class PacketComparison:
    left_name: str = ""
    right_name: str = ""
    left_characters: int = 0
    right_characters: int = 0
    instruction_diff: list[str] = field(default_factory=list)
    check_diff: list[str] = field(default_factory=list)
    headings_left: list[str] = field(default_factory=list)
    headings_right: list[str] = field(default_factory=list)

    @property
    def substantive_changes(self) -> list[str]:
        """Changed lines that are not blank-line placement."""

        return [
            line for line in
            changed_lines(self.instruction_diff) + changed_lines(self.check_diff)
            if line[1:].strip()
        ]

    @property
    def identical_instructions(self) -> bool:
        """No differences at all, of any kind."""

        return not changed_lines(self.instruction_diff) and \
            not changed_lines(self.check_diff)

    @property
    def equivalent_instructions(self) -> bool:
        """The same thing asked in the same words, whitespace aside."""

        return not self.substantive_changes

    @property
    def headings_match(self) -> bool:
        return self.headings_left == self.headings_right


def split_regions(packet: str) -> tuple[str, str, str]:
    """Instructions, evidence, final check.

    A packet without boundaries is treated as all instructions: that is the
    conservative reading, since it means everything gets diffed rather than
    silently skipped.
    """

    if BOUNDARY_OPEN not in packet or BOUNDARY_CLOSE not in packet:
        return packet, "", ""
    head, rest = packet.split(BOUNDARY_OPEN, 1)
    evidence, tail = rest.split(BOUNDARY_CLOSE, 1)
    return head, evidence, tail


def headings_in(text: str) -> list[str]:
    return re.findall(r"(?m)^### .+$", text)


def compare_packets(
    left: str,
    right: str,
    *,
    left_name: str = "old",
    right_name: str = "new",
) -> PacketComparison:
    """Diff two packets' instruction regions."""

    left_head, _, left_tail = split_regions(left)
    right_head, _, right_tail = split_regions(right)

    # Unfiltered. Removing lines from a diff leaves hunk headers pointing at
    # changes that are no longer shown, which reads as "something differs
    # but I will not tell you what". Whitespace-only changes are separated
    # by the report instead.
    instruction_diff = list(difflib.unified_diff(
        left_head.splitlines(), right_head.splitlines(),
        fromfile=f"{left_name}/instructions",
        tofile=f"{right_name}/instructions",
        lineterm="", n=2,
    ))
    check_diff = list(difflib.unified_diff(
        left_tail.splitlines(), right_tail.splitlines(),
        fromfile=f"{left_name}/final-check",
        tofile=f"{right_name}/final-check",
        lineterm="", n=2,
    ))

    return PacketComparison(
        left_name=left_name,
        right_name=right_name,
        left_characters=len(left),
        right_characters=len(right),
        instruction_diff=instruction_diff,
        check_diff=check_diff,
        headings_left=headings_in(left_head + left_tail),
        headings_right=headings_in(right_head + right_tail),
    )


def render(comparison: PacketComparison) -> str:
    lines = [
        "# Packet comparison",
        "",
        f"- {comparison.left_name}: {comparison.left_characters:,} characters",
        f"- {comparison.right_name}: {comparison.right_characters:,} characters",
        "",
        "Only the instruction region and the final check are compared. The",
        "evidence region differs between any two runs — comments arrive and",
        "likes change — and diffing it would bury what matters.",
        "",
    ]

    if comparison.headings_match:
        lines.append(
            f"Headings: identical ({len(comparison.headings_left)} sections)."
        )
    else:
        lines.extend([
            "## Headings differ",
            "",
            f"- {comparison.left_name}: {comparison.headings_left}",
            f"- {comparison.right_name}: {comparison.headings_right}",
        ])
    lines.append("")

    if comparison.identical_instructions:
        lines.extend([
            "## No instruction differences",
            "",
            "The two packets ask for the same thing in the same words.",
        ])
        return "\n".join(lines)

    if comparison.equivalent_instructions:
        lines.extend([
            "## Whitespace only",
            "",
            "The instructions differ only in where blank lines fall. The two",
            "packets ask the model for the same thing in the same words.",
            "",
        ])
        if comparison.instruction_diff:
            lines.extend(["```diff", *comparison.instruction_diff, "```", ""])
        if comparison.check_diff:
            lines.extend(["```diff", *comparison.check_diff, "```", ""])
        return "\n".join(lines)

    if changed_lines(comparison.instruction_diff):
        lines.extend(["## Instruction region", "", "```diff"])
        lines.extend(comparison.instruction_diff)
        lines.extend(["```", ""])

    if changed_lines(comparison.check_diff):
        lines.extend(["## Final output check", "", "```diff"])
        lines.extend(comparison.check_diff)
        lines.extend(["```", ""])

    lines.extend([
        f"{len(comparison.substantive_changes)} substantive changed lines.",
        "",
        "Every difference above is either intended by the rebuild plan or a",
        "defect. There is no third category, and nothing here decides which",
        "it is.",
    ])
    return "\n".join(lines)


def compare_files(left: Path | str, right: Path | str) -> PacketComparison:
    left, right = Path(left), Path(right)
    return compare_packets(
        left.read_text(encoding="utf-8"),
        right.read_text(encoding="utf-8"),
        left_name=left.name,
        right_name=right.name,
    )
