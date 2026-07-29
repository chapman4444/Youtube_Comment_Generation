"""Comparing two packets' instruction regions.

A checksum proves the prompt text did not change. It does not prove the text
was assembled in the right order with the right counts, and that is where a
rebuild degrades silently.
"""

from __future__ import annotations

from llm_youtube_comment_generation.application.compare import (
    compare_files,
    compare_packets,
    render,
    split_regions,
)

OPEN = "## BEGIN UNTRUSTED SOURCE MATERIAL"
CLOSE = "## END UNTRUSTED SOURCE MATERIAL"


def packet(instructions="### 1. Short hook\nask for five things",
           evidence="a comment somebody wrote",
           check="## FINAL OUTPUT CHECK\nthe five headings"):
    return f"{instructions}\n{OPEN}\n{evidence}\n{CLOSE}\n{check}"


def test_identical_packets_show_no_differences():
    comparison = compare_packets(packet(), packet())

    assert comparison.identical_instructions
    assert comparison.equivalent_instructions
    assert "No instruction differences" in render(comparison)


def test_a_blank_line_difference_is_reported_as_whitespace_only():
    """Two packets whose instructions differ only in blank-line placement
    ask for exactly the same thing, and saying otherwise trains the operator
    to skim past real differences."""

    comparison = compare_packets(
        packet(instructions="line one\nline two"),
        packet(instructions="line one\n\nline two"),
    )

    assert not comparison.identical_instructions
    assert comparison.equivalent_instructions
    assert comparison.substantive_changes == []
    assert "Whitespace only" in render(comparison)


def test_a_diff_is_never_shown_with_its_changes_removed():
    """A hunk header pointing at changes that are not displayed reads as
    "something differs but I will not say what"."""

    comparison = compare_packets(
        packet(instructions="line one\n\nline two"),
        packet(instructions="line one\nline two"),
    )

    text = render(comparison)
    if "```diff" in text:
        body = text.split("```diff")[1]
        assert any(line.startswith(("+", "-")) and
                   not line.startswith(("+++", "---"))
                   for line in body.splitlines())


def test_a_changed_instruction_is_surfaced():
    comparison = compare_packets(
        packet(instructions="ask for five things"),
        packet(instructions="ask for four things"),
    )

    assert not comparison.identical_instructions
    assert any("five" in line for line in comparison.instruction_diff)
    assert any("four" in line for line in comparison.instruction_diff)


def test_evidence_differences_are_ignored():
    """Two runs always differ here: comments arrive and likes change.

    Diffing the evidence would bury the differences that matter under
    hundreds that do not.
    """

    comparison = compare_packets(
        packet(evidence="a comment with 4 likes"),
        packet(evidence="a completely different comment with 900 likes"),
    )

    assert comparison.identical_instructions


def test_a_changed_final_check_is_surfaced_separately():
    """The check drifting away from the contract is the exact defect that
    shipped in the old application."""

    comparison = compare_packets(
        packet(check="## FINAL OUTPUT CHECK\nthe five headings"),
        packet(check="## FINAL OUTPUT CHECK\nthe four headings"),
    )

    assert comparison.check_diff
    assert not comparison.instruction_diff
    assert "Final output check" in render(comparison)


def test_heading_differences_are_reported_plainly():
    comparison = compare_packets(
        packet(instructions="### 1. Short hook\n### 2. Dry joke"),
        packet(instructions="### 1. Short hook"),
    )

    assert not comparison.headings_match
    assert "Headings differ" in render(comparison)


def test_matching_headings_are_stated_rather_than_left_silent():
    comparison = compare_packets(packet(), packet())

    assert comparison.headings_match
    assert "Headings: identical" in render(comparison)


def test_a_packet_without_boundaries_is_treated_as_all_instructions():
    """The conservative reading: everything gets diffed rather than skipped."""

    head, evidence, tail = split_regions("no boundaries here")

    assert head == "no boundaries here"
    assert evidence == "" and tail == ""


def test_character_counts_are_reported_for_both():
    comparison = compare_packets(packet(), packet(evidence="x" * 500))

    text = render(comparison)
    assert str(comparison.left_characters) in text.replace(",", "")
    assert comparison.right_characters > comparison.left_characters


def test_the_report_refuses_to_judge_the_differences():
    """The tool surfaces drift. Deciding whether a difference is intended is
    the operator's job and the report says so."""

    comparison = compare_packets(
        packet(instructions="five"), packet(instructions="four")
    )

    assert "either intended by the rebuild plan or a" in render(comparison)


def test_files_can_be_compared_directly(tmp_path):
    old = tmp_path / "old_packet.md"
    new = tmp_path / "new_packet.md"
    old.write_text(packet(instructions="five"), encoding="utf-8")
    new.write_text(packet(instructions="four"), encoding="utf-8")

    comparison = compare_files(old, new)

    assert comparison.left_name == "old_packet.md"
    assert comparison.right_name == "new_packet.md"
    assert not comparison.identical_instructions
