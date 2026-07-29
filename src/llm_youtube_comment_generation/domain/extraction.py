"""Reading a deliverable back out of a pasted model answer.

Every function here refuses rather than guesses. What comes out of this module
is text the operator is about to post under his own name, so a wrong answer
that looks like an answer is worse than an error.
"""

from __future__ import annotations

import re

from .sanitize import SOURCE_BOUNDARY_CLOSE, SOURCE_BOUNDARY_OPEN
from .targeting import strip_invisible


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
