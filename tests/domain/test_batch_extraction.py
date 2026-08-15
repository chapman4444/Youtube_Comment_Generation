"""Reading a batch reply sheet back out of a pasted model answer.

Every refusal here protects the same thing: text about to be posted under
the operator's own name. A batch is accepted whole or refused whole, and
nothing outside a code fence can ever become a draft.
"""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.domain.extraction import (
    extract_batch_replies,
    looks_like_batch_reply_sheet,
)

IDS = ["AAA.111", "AAA.222", "AAA.333"]


def sheet(*, third_id="AAA.333", third_body="Third reply."):
    return (
        "# Copy/Paste Replies\n\n"
        "## Direct replies to your comment\n\n"
        "### Response 1 of 3: Norm\n\n"
        "**Post beneath comment ID:** AAA.111\n\n"
        "**Author channel ID:** UCX\n\n"
        "**Responding to:** PACKET OWNER\n\n"
        "**Relationship:** Direct\n\n"
        "```text\nFirst reply.\n```\n\n"
        "## Nested replies between other users\n\n"
        "### Response 2 of 3: Knight\n\n"
        "**Post beneath comment ID:** `AAA.222`\n\n"
        "```text\nSecond reply,\nover two lines.\n```\n\n"
        "### Response 3 of 3: Fly\n\n"
        f"**Post beneath comment ID:** {third_id}\n\n"
        f"```text\n{third_body}\n```\n"
    )


# --------------------------------------------------------------------------
# Accepting a well-formed sheet
# --------------------------------------------------------------------------


def test_a_well_formed_sheet_parses_every_target():
    replies, problems = extract_batch_replies(sheet(), IDS)

    assert problems == []
    assert replies == {
        "AAA.111": "First reply.",
        "AAA.222": "Second reply,\nover two lines.",
        "AAA.333": "Third reply.",
    }


def test_a_backticked_or_bolded_id_line_still_parses():
    replies, problems = extract_batch_replies(sheet(), IDS)

    assert problems == []
    assert "AAA.222" in replies      # its line wraps the id in backticks


def test_windows_line_endings_are_tolerated():
    replies, problems = extract_batch_replies(
        sheet().replace("\n", "\r\n"), IDS)

    assert problems == []
    assert replies["AAA.111"] == "First reply."


def test_metadata_between_the_id_line_and_the_fence_is_never_draft_text():
    replies, problems = extract_batch_replies(sheet(), IDS)

    assert problems == []
    for reply in replies.values():
        assert "Responding to" not in reply
        assert "Relationship" not in reply
        assert "###" not in reply


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


def test_a_missing_target_is_reported():
    _, problems = extract_batch_replies(sheet(), IDS + ["AAA.444"])

    assert any("AAA.444" in p and "missing" in p for p in problems)


def test_an_unknown_target_is_reported():
    _, problems = extract_batch_replies(sheet(third_id="AAA.999"), IDS)

    assert any("AAA.999" in p and "not a target" in p for p in problems)
    assert any("AAA.333" in p and "missing" in p for p in problems)


def test_a_duplicated_target_is_reported():
    doubled = sheet() + (
        "\n**Post beneath comment ID:** AAA.111\n\n```text\nAgain.\n```\n"
    )
    _, problems = extract_batch_replies(doubled, IDS)

    assert any("AAA.111" in p and "more than once" in p for p in problems)


def test_an_empty_code_block_is_not_a_reply():
    _, problems = extract_batch_replies(sheet(third_body=""), IDS)

    assert any("AAA.333" in p and "no code block" in p for p in problems)


def test_two_code_blocks_for_one_target_are_ambiguous():
    doubled = sheet(third_body="Third reply.\n```\n\n```text\nOr this one?")
    _, problems = extract_batch_replies(doubled, IDS)

    assert any("AAA.333" in p and "2 code blocks" in p for p in problems)


def test_an_unclosed_fence_is_malformed_not_guessed():
    broken = sheet().rsplit("```", 1)[0]      # drop the final closing fence
    _, problems = extract_batch_replies(broken, IDS)

    assert any("AAA.333" in p and "never closed" in p for p in problems)


def test_prose_with_no_sheet_lines_is_not_an_answer():
    replies, problems = extract_batch_replies("thoughts, but no sheet", IDS)

    assert replies == {}
    assert any("not a Copy/Paste Replies sheet" in p for p in problems)


def test_a_non_text_fence_language_is_refused():
    """A 'python' fence means the model wrapped something that is not a
    paste-ready YouTube reply."""

    wrong = sheet().replace("```text\nThird reply.", "```python\nThird reply.")
    _, problems = extract_batch_replies(wrong, IDS)

    assert any("'python' code block" in p for p in problems)


def test_a_bare_fence_is_still_accepted():
    """Chat clients drop the language on copy; that is a formatting
    accident, not a different intent."""

    bare = sheet().replace("```text\n", "```\n")
    replies, problems = extract_batch_replies(bare, IDS)

    assert problems == []
    assert len(replies) == 3


def test_targets_out_of_the_packets_order_are_refused():
    """The packet fixes the order; a shuffled sheet may have shuffled the
    replies against their metadata."""

    _, problems = extract_batch_replies(sheet(), ["AAA.222", "AAA.111",
                                                  "AAA.333"])

    assert any("different order than the packet asked for" in p
               for p in problems)


@pytest.mark.parametrize(("payload", "expected"), [
    ("### Analysis\nthe reply", "a Markdown heading"),
    ("Response 1 of 3: Norm\nthe reply", "a metadata label"),
    ("Hardened final\nthe reply", "a metadata label"),
    ("the reply [insert name]", "a placeholder"),
])
def test_analysis_or_labels_inside_a_reply_are_refused(payload, expected):
    mutated = sheet(third_body=payload)
    _, problems = extract_batch_replies(mutated, IDS)

    assert any(expected in p and "AAA.333" in p for p in problems)


def test_a_fence_inside_a_reply_is_refused():
    """A fence inside the reply closes the block early and leaves the rest
    dangling. However it is described, the paste must not be accepted."""

    mutated = sheet(third_body="the reply\n```\nmore text")
    _, problems = extract_batch_replies(mutated, IDS)

    assert any("AAA.333" in p for p in problems)


def test_ordinary_prose_with_brackets_survives():
    """A reply may legitimately contain bracketed asides; only
    placeholder-shaped tokens are refused."""

    replies, problems = extract_batch_replies(
        sheet(third_body="He said it at 14:20 (the permit was filed)."), IDS)

    assert problems == []
    assert replies["AAA.333"].endswith("filed).")


def test_a_sheet_without_its_header_is_refused():
    """An analysis paste or a partial copy announces itself by the missing
    header before any id happens to match."""

    headless = sheet().replace("# Copy/Paste Replies\n\n", "")
    _, problems = extract_batch_replies(headless, IDS)

    assert any("does not begin with '# Copy/Paste Replies'" in p
               for p in problems)


def test_a_quoted_header_from_a_chat_client_still_counts():
    quoted = "> # Copy/Paste Replies" + sheet()[len("# Copy/Paste Replies"):]
    _, problems = extract_batch_replies(quoted, IDS)

    assert problems == []


# --------------------------------------------------------------------------
# Sheet detection
# --------------------------------------------------------------------------


def test_a_sheet_is_detected_by_shape():
    assert looks_like_batch_reply_sheet(sheet()) is True
    assert looks_like_batch_reply_sheet("ordinary prose") is False
    assert looks_like_batch_reply_sheet("") is False


def test_the_packets_own_contract_text_is_not_detected_as_a_sheet():
    """The workflow describes the id line with a bracketed placeholder; the
    description must not read as an actual sheet."""

    contract_line = (
        "**Post beneath comment ID:** [that target's complete comment_id]"
    )

    assert looks_like_batch_reply_sheet(contract_line) is False
