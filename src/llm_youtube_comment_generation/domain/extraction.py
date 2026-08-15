"""Reading a deliverable back out of a pasted model answer.

Every function here refuses rather than guesses. What comes out of this module
is text the operator is about to post under his own name, so a wrong answer
that looks like an answer is worse than an error.
"""

from __future__ import annotations

import re
from typing import Sequence

from .sanitize import SOURCE_BOUNDARY_CLOSE, SOURCE_BOUNDARY_OPEN
from .targeting import strip_invisible
from .video import watch_url


def parse_triage_selection(text: str) -> list[str]:
    """Read handles back out of an LLM's triage answer.

    Accepts the documented "@handle | rank | reason" form, and also a bare list
    of handles, because a reader will not always follow the format exactly.
    """

    lines = [strip_invisible(line).strip()
             for line in str(text or "").splitlines()]

    def add(collected: list[str], handle: str) -> None:
        if handle.casefold() not in {h.casefold() for h in collected}:
            collected.append(handle)

    # The documented shape wins outright when it is present. Reading only the
    # ranked lines means the SKIP list cannot leak in no matter how it is
    # wrapped, which is what happens whenever it is copied out of a chat
    # window: the tail of a wrapped SKIP line looks exactly like a bare list
    # of handles, and every person deliberately skipped became a target.
    ranked = re.compile(r"^@([A-Za-z0-9_.\-]+)\s*\|\s*\d+\s*\|")
    chosen: list[str] = []
    for line in lines:
        found = ranked.match(line)
        if found:
            add(chosen, "@" + found.group(1))
    if chosen:
        return chosen

    # No ranked lines, so fall back to a bare list. SKIP is sticky here: once
    # it starts, everything after it is a skip, however many lines it runs to.
    handles: list[str] = []
    skipping = False
    for line in lines:
        if not line:
            continue
        if line.upper().startswith("SKIP:"):
            skipping = True
            continue
        if skipping:
            # Only something that clearly restarts the wanted list ends it.
            if ranked.match(line):
                skipping = False
            else:
                continue
        for found in re.findall(r"@([A-Za-z0-9_.\-]+)", line):
            add(handles, "@" + found)
    return handles


def extract_hardened_final(text: str) -> str:
    """Pull the deliverable reply out of a pasted model answer.

    The packet asks for a "### Hardened final" section containing only the
    finished reply, so that is what is looked for first. Real answers drift:
    the heading arrives bolded, numbered, as plain text, with different
    capitalisation, or wrapped in a code fence somebody's client added. Each
    of those is a formatting accident, not a different intent, so all of them
    are accepted.

    Returns "" when nothing recognisable is present. An empty string is a
    refusal to guess: silently handing back the critique section, or the whole
    paste, would put text on the channel that was never meant to be posted.
    """

    body = strip_invisible(str(text or "")).replace("\r\n", "\n")
    if not body.strip():
        return ""

    heading = re.compile(
        r"""(?imx)
        ^\s*
        (?:\#{1,6}\s*)?          # optional markdown heading marks
        (?:\d+[.)]\s*)?          # optional numbering
        (?:\*{1,2}|_{1,2})?      # optional bold or italic
        \s*hardened\s+final\s*
        (?:\*{1,2}|_{1,2})?
        \s*:?\s*$
        """
    )
    matches = list(heading.finditer(body))
    if not matches:
        return ""

    # The last one, because a model often names the section in its own
    # preamble before actually writing it.
    start = matches[-1].end()
    rest = body[start:]

    # Stop at the next heading of any kind. Nothing should follow the
    # Hardened final, but when something does it is commentary, not reply.
    following = re.search(r"(?m)^\s*(?:\#{1,6}\s+\S|-{3,}\s*$)", rest)
    if following:
        rest = rest[: following.start()]

    return clean_pasted_reply(rest)


_POST_BENEATH_LINE = re.compile(
    r"""(?imx)
    ^[\s>*_]*                     # leading space, quote or emphasis marks
    post\s+beneath\s+comment\s+id
    [\s:*_\x60]*                  # label punctuation, emphasis, backticks
    ([A-Za-z0-9_.\-]+)            # the comment id itself
    [\s*_\x60]*$
    """
)

# A `text` fence is what the packet asks for. A bare fence is accepted
# because chat clients drop the language on copy; any *other* language means
# the model wrapped something that is not a paste-ready reply.
_FENCE_OPEN = re.compile(r"^\s*```\s*(text)?\s*$", re.IGNORECASE)
_ANY_FENCE_OPEN = re.compile(r"^\s*```([A-Za-z0-9_-]*)\s*$")
_FENCE_CLOSE = re.compile(r"^\s*```\s*$")

# Things that must never appear inside a paste-ready reply. Each one means
# the model wrapped its workings instead of the deliverable.
_NOT_PASTE_READY = (
    (re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S"), "a Markdown heading"),
    (re.compile(r"(?im)^\s*\*{0,2}(response|post beneath|author channel|"
                r"responding to|relationship|variation|hardened final|"
                r"harsh critique|analysis|triage)\b"), "a metadata label"),
    (re.compile(r"(?m)^\s*```"), "another code fence"),
    # Bracketed tokens are how the contract writes its own placeholders
    # ("[Only the exact paste-ready reply]"). A YouTube reply has no need
    # for square brackets, so any of them reads as unfinished text.
    (re.compile(r"\[[^\]\n]{1,80}\]|\{[a-z_]+\}", re.IGNORECASE),
     "a placeholder"),
)


def _reply_content_problem(reply: str) -> str:
    for pattern, description in _NOT_PASTE_READY:
        if pattern.search(reply):
            return description
    return ""


def extract_batch_replies(
    text: str,
    expected_ids: Sequence[str],
) -> tuple[dict[str, str], list[str]]:
    """Parse a pasted Copy/Paste Replies sheet against the packet's targets.

    Validated deterministically, in the order the packet asked for: the
    sheet header, one section per target keyed by "Post beneath comment ID",
    the packet's own target order, exactly one `text` fence per target, and
    nothing inside that fence except paste-ready prose.

    Nothing outside a fence can become draft text, because the only
    characters ever taken are fence contents.

    Returns the replies keyed by comment id and a list of problems. A
    nonempty problem list means the paste must be refused whole: accepting
    the parseable half of a batch would post some people's replies while
    silently dropping others, and a wrong answer that looks like an answer
    is worse than an error.
    """

    problems: list[str] = []
    expected = [str(identifier) for identifier in expected_ids]
    body = strip_invisible(str(text or "")).replace("\r\n", "\n")
    lines = body.split("\n")

    # The header is the contract's own first line. Its absence is how an
    # analysis paste, a partial copy, or a different conversation's answer
    # announces itself before any id happens to match.
    if not re.search(r"(?im)^[\s>]*#\s*copy/paste\s+replies\s*$", body):
        problems.append(
            "the paste does not begin with '# Copy/Paste Replies', so it "
            "is not this packet's answer sheet"
        )

    # Where each target's section starts, in sheet order.
    found: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        match = _POST_BENEATH_LINE.match(line)
        if match:
            found.append((match.group(1), index))

    if not found:
        problems.append(
            "no 'Post beneath comment ID' lines were found, so this is not "
            "a Copy/Paste Replies sheet"
        )
        return {}, problems

    # The packet fixes the order: direct, nested, unresolved, each group in
    # source order. A sheet in a different order is a sheet whose targets
    # may have been shuffled against their metadata.
    listed = [identifier for identifier, _ in found]
    if len(listed) == len(expected) and set(listed) == set(expected) \
            and listed != expected:
        problems.append(
            "the targets appear in a different order than the packet asked "
            f"for ({', '.join(listed)} instead of {', '.join(expected)})"
        )

    replies: dict[str, str] = {}
    for position, (identifier, start) in enumerate(found):
        end = found[position + 1][1] if position + 1 < len(found) else len(lines)
        if identifier in replies:
            problems.append(f"comment id {identifier} appears more than once")
            continue
        if identifier not in expected:
            problems.append(
                f"comment id {identifier} is not a target of this packet"
            )
            continue

        # The code blocks between this target line and the next one.
        blocks: list[str] = []
        cursor = start + 1
        while cursor < end:
            language = _ANY_FENCE_OPEN.match(lines[cursor])
            if language:
                if not _FENCE_OPEN.match(lines[cursor]):
                    problems.append(
                        f"comment id {identifier} uses a "
                        f"'{language.group(1)}' code block; the reply must "
                        "be in a plain text block"
                    )
                content: list[str] = []
                cursor += 1
                while cursor < end and not _FENCE_CLOSE.match(lines[cursor]):
                    content.append(lines[cursor])
                    cursor += 1
                if cursor >= end:
                    problems.append(
                        f"the code block for comment id {identifier} is "
                        "never closed"
                    )
                    content = []
                blocks.append("\n".join(content).strip())
            cursor += 1

        clean = [block for block in blocks if block]
        if not clean:
            problems.append(
                f"comment id {identifier} has no code block holding its "
                "reply"
            )
            continue
        if len(clean) > 1:
            problems.append(
                f"comment id {identifier} has {len(clean)} code blocks; one "
                "reply per target, so which one to post is ambiguous"
            )
            continue
        unpasteable = _reply_content_problem(clean[0])
        if unpasteable:
            problems.append(
                f"the reply for comment id {identifier} contains "
                f"{unpasteable}; a code block holds only the finished reply"
            )
            continue
        replies[identifier] = clean[0]

    for identifier in expected:
        if identifier not in replies and not any(
            identifier in problem for problem in problems
        ):
            problems.append(
                f"comment id {identifier} is missing from the sheet"
            )

    return replies, problems


def looks_like_batch_reply_sheet(text: str) -> bool:
    """Shape check only: does this paste carry Post-beneath target lines?

    Used to *offer* a paste as a reply sheet. Validation against the actual
    target ids belongs to extract_batch_replies, so no id is checked here —
    two places owning that rule is how they end up disagreeing.
    """

    body = strip_invisible(str(text or "")).replace("\r\n", "\n")
    return any(_POST_BENEATH_LINE.match(line) for line in body.split("\n"))


def comment_answer_identification_problem(
    text: str,
    *,
    video_title: str,
    video_id: str,
) -> str:
    """Explain an invalid required ``Video`` identification line."""

    body = strip_invisible(str(text or "")).replace("\r\n", "\n")
    expected_url = watch_url(video_id)
    expected_line = f"**Video:** {video_title} {expected_url}"
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return (
            "The answer is empty. Its first line must identify the video as "
            f"{expected_line}"
        )

    copies = body.count(expected_url)
    if copies != 1:
        return (
            "The Video line must contain the YouTube URL exactly once as "
            f"plain text; found {copies} copies. Do not wrap it in Markdown "
            "brackets, parentheses, or link syntax."
        )
    if lines[0] != expected_line:
        return (
            "The first nonblank line must be exactly "
            f"{expected_line}. Keep the URL as plain text with no Markdown "
            "brackets, parentheses, or link syntax."
        )
    return ""


def looks_like_packet_text(text: str, packet: str = "") -> bool:
    """Is this the packet coming back, rather than an answer to it?

    The application puts the packet on the clipboard and then asks for an
    answer on the same clipboard, so a stray click submits the packet to
    itself. That has to be caught rather than parsed, because the packet
    contains a literal "### Hardened final" heading in its own instructions:
    extraction happily returns the sentence describing the section, and a
    line of prompt text ends up in the file of replies ready to post.

    A wrong answer that looks like an answer is worse than an error.
    """

    body = strip_invisible(str(text or ""))
    if not body.strip():
        return False

    for marker in (SOURCE_BOUNDARY_OPEN, SOURCE_BOUNDARY_CLOSE,
                   "# GLOBAL YOUTUBE REPLY WORKFLOW",
                   "# GLOBAL YOUTUBE COMMENT WORKFLOW",
                   "## FINAL OUTPUT CHECK",
                   "## Non-negotiable output contract",
                   "# REPLY TRIAGE"):
        if marker in body:
            return True

    if packet:
        stripped = body.strip()
        reference = strip_invisible(packet).strip()
        if stripped == reference or reference.startswith(stripped[:400]):
            return True

    return False


def clean_pasted_reply(text: str) -> str:
    """Strip the wrappers a chat client adds around text you meant to copy."""

    body = str(text or "").strip()

    # A whole-answer code fence, which several clients add on copy.
    fence = re.match(r"^```[^\n]*\n(.*?)\n?```$", body, re.S)
    if fence:
        body = fence.group(1).strip()

    lines = [line.rstrip() for line in body.split("\n")]
    # Block-quote markers, which appear when the reply is quoted back.
    if lines and all(not line or line.startswith(">") for line in lines):
        lines = [re.sub(r"^>\s?", "", line) for line in lines]

    body = "\n".join(lines).strip()

    # Surrounding quotation marks around the entire reply, straight or curly.
    for opening, closing in (('"', '"'), ("“", "”"), ("'", "'")):
        if len(body) > 1 and body.startswith(opening) and body.endswith(closing):
            body = body[1:-1].strip()
            break

    # Collapse the blank-line runs that survive a copy out of a chat window,
    # without joining paragraphs the writer intended to keep apart.
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()
