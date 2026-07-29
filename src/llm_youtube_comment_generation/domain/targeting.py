"""Who each reply is answering.

The YouTube API is flat: a reply to a reply is stored as another reply to the
same top-level comment, with the client prepending an @mention. Everything in
this module exists to recover the conversation that shape throws away.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from .statuses import ReplyTargetKind, ReplyTargetResolution

MENTION_PATTERN = re.compile(r"^@([\w.\-]+)", re.UNICODE)

# YouTube prefixes a rendered @mention with U+200B ZERO WIDTH SPACE, which is
# Unicode category Cf, not whitespace, so \s does not match it. Left in place
# it makes every mention look like the start of ordinary text.
#
# Written as escapes rather than literal bytes on purpose: these characters are
# invisible in an editor and do not survive a careless encoding round-trip, so
# the source states them by codepoint. test_targeting.py asserts the runtime
# value, because a comment cannot enforce this and a silent change here would
# break mention parsing without breaking anything visible.
INVISIBLE_CHARACTERS = "\u200b\u200c\u200d\u2060\ufeff"

# Below this length a known handle is too likely to be an accidental prefix of
# a different account to be trusted as a run-together mention.
MENTION_PREFIX_MIN_LENGTH = 8


def strip_invisible(text: str) -> str:
    return str(text or "").lstrip(INVISIBLE_CHARACTERS + " \t\r\n")


def leading_mention(text: str, known_handles: Sequence[str]) -> str:
    """Return the handle a reply opens by addressing, or an empty string.

    Two things make this harder than a regex. YouTube inserts an invisible
    U+200B before the mention, and the rendered mention runs straight into the
    following word with no separator, so "@somebodyno, but..." is a mention of
    "somebody" and not of "somebodyno". Matching against the handles actually
    present in the thread resolves both, with a greedy fallback for handles
    that were not captured.
    """

    cleaned = strip_invisible(text)
    if not cleaned.startswith("@"):
        return ""

    match = MENTION_PATTERN.match(cleaned)
    if not match:
        return ""
    token = match.group(1)
    lowered = {h.casefold(): h for h in known_handles if h}

    # An exact hit is unambiguous and always wins.
    if token.casefold() in lowered:
        return lowered[token.casefold()]

    # Otherwise the rendered mention has run into the following word, as in
    # "@somebodyno, but". Take the longest known handle that prefixes the
    # token, but refuse when the remainder is all digits: "@alice123" is far
    # more likely a different account than a mention of "alice" followed by
    # the number 123.
    for handle in sorted(known_handles, key=len, reverse=True):
        if not handle or not token.casefold().startswith(handle.casefold()):
            continue
        remainder = token[len(handle):]
        if not remainder:
            return handle
        # "@alice123" is another account, not "alice" plus a number.
        if remainder.isdigit():
            continue
        # A short handle is very likely a prefix of an unrelated one by
        # chance: "@aliceabc" is not a mention of "alice". Long handles
        # colliding by accident is vanishingly unlikely, so those are taken
        # as the mention running into the next word.
        if len(handle) < MENTION_PREFIX_MIN_LENGTH:
            continue
        return handle

    # Unresolvable. Report it as written rather than guessing, which keeps it
    # out of the owner's queue without misattributing it to a real person.
    return token


def annotate_reply_targets(
    owner_author: str,
    replies: Sequence[dict[str, Any]],
    owner_channel_id: str = "",
) -> list[dict[str, Any]]:
    """Reconstruct who each reply is answering.

    Measured across 860 real replies there is no true nesting at all, and 25
    percent open with an @mention. Recovering that structure is the difference
    between a chronological list and a readable conversation.

    Adds "responds_to_author" and "responds_to_owner" without mutating input.
    """

    def handle_of(record: dict[str, Any]) -> str:
        return str(record.get("author") or "").lstrip("@")

    owner_handle = str(owner_author or "").lstrip("@")
    known = [handle_of(reply) for reply in replies if handle_of(reply)]
    if owner_handle:
        known.append(owner_handle)

    annotated: list[dict[str, Any]] = []
    for reply in replies:
        record = dict(reply)
        # Channel ID is stable; the display name is not. A reply written by the
        # owner can never be a reply to the owner.
        record["is_owner_reply"] = bool(
            owner_channel_id
            and reply.get("author_channel_id") == owner_channel_id
        )
        target = leading_mention(str(reply.get("text") or ""), known)
        resolved = bool(
            target and any(target.casefold() == h.casefold() for h in known)
        )
        # Three states, not two. A mention naming somebody not in this thread
        # cannot be classified either way, and guessing "side exchange" made
        # legitimate replies disappear from the queue.
        if record["is_owner_reply"]:
            record["responds_to_author"] = target
            record["target_state"] = "owner_reply"
        elif not target:
            # No mention: YouTube's Reply button on the owner's comment.
            record["responds_to_author"] = ""
            record["target_state"] = "owner"
        elif target.casefold() == owner_handle.casefold():
            record["responds_to_author"] = owner_handle
            record["target_state"] = "owner"
        elif resolved:
            record["responds_to_author"] = target
            record["target_state"] = "other"
        else:
            record["responds_to_author"] = target
            record["target_state"] = "unknown"
        record["responds_to_owner"] = record["target_state"] == "owner"
        record["mentions_known_participant"] = resolved
        annotated.append(record)
    return annotated


def resolution_of(reply: dict[str, Any]) -> ReplyTargetResolution:
    """The typed answer to "who is this reply for", with its reasoning.

    Built from an already-annotated reply rather than re-deriving the answer,
    so there is exactly one implementation of the rule. The dict form is what
    the ported logic produces and what the equivalence proof covers; this is
    the contract the rest of the application reads.

    ``reason`` is for a human wondering why somebody is or is not in their
    queue. It is never parsed.
    """

    state = str(reply.get("target_state") or "")
    mention = str(reply.get("responds_to_author") or "")

    if state == ReplyTargetKind.OWNER_REPLY.value:
        reason = "written by the owner, so it answers rather than asks"
    elif state == ReplyTargetKind.OWNER.value:
        reason = (
            f"names the owner (@{mention})" if mention
            else "opens with no mention, so it used the Reply button on the "
                 "owner's comment"
        )
    elif state == ReplyTargetKind.OTHER_PARTICIPANT.value:
        reason = f"names @{mention}, another participant in this thread"
    else:
        reason = (
            f"names @{mention}, who is not in this thread; the target could "
            "not be resolved either way and is shown rather than guessed"
        )

    return ReplyTargetResolution(
        kind=ReplyTargetKind(state) if state else ReplyTargetKind.UNRESOLVABLE,
        target_channel_id=str(reply.get("author_channel_id") or ""),
        raw_mention=mention,
        reason=reason,
    )
