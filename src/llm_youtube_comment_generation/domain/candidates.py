"""Who is still owed an answer, and in what order.

The thread itself is the log. Your own replies sit in the same flat list as
everyone else's and carry an @mention of whoever you answered, so no local
state file is needed and none is kept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from .statuses import CandidateStatus
from .targeting import annotate_reply_targets
from .threads import OwnerThread, as_moment
from .video import as_int

QUESTION_MARKERS = ("?",)
DISAGREEMENT_MARKERS = (
    "actually", "wrong", "no,", "not true", "disagree", "but ", "however",
    "except", "incorrect", "false", "citation", "source", "evidence", "proof",
)


def score_reply(reply: dict[str, Any]) -> float:
    """How much a reply deserves an answer.

    On one real thread 92 of 177 replies were aimed at the owner, with a median
    of 13 words and a third under 10. Answering all of them is absurd and
    answering none of them individually is what the single-thread packet does.
    Scoring lets a short list of genuine challenges surface.

    Likes dominate because the room has already voted on which reply landed.
    """

    text = str(reply.get("text") or "")
    words = len(text.split())
    likes = as_int(reply.get("like_count")) or 0
    lowered = text.casefold()

    score = 0.0
    score += min(likes, 1_000) ** 0.5          # damped: 100 likes is not 10x of 10
    score += min(words, 120) / 12.0            # substance, capped
    if any(marker in lowered for marker in DISAGREEMENT_MARKERS):
        score += 4.0                           # an actual challenge
    if any(marker in text for marker in QUESTION_MARKERS):
        score += 3.0                           # asks you something
    if reply.get("responds_to_owner"):
        score += 5.0                           # aimed at you, not a side argument
    if words < 6:
        score -= 6.0                           # "lol", "exactly", emoji
    return score


@dataclass
class ReplyCandidate:
    """One person in a thread and whether they are still owed an answer."""

    author: str = ""
    reply: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    my_last_answer: str = ""
    their_last_reply: str = ""
    answered: bool = False
    replied_again: bool = False
    uncertain_target: bool = False
    # They posted after your answer, but the only thing addressed at anyone
    # was a mention this parser could not resolve. Might be a follow-up to
    # you under an old handle or an unrecognised mention form, might be a
    # side conversation. Kept visible and ranked last rather than guessed.
    unclear_after_answer: bool = False
    thread_id: str = ""
    channel_id: str = ""
    message_count: int = 1

    @property
    def outstanding(self) -> bool:
        """Whether this person should appear in the default queue.

        unclear_after_answer is included deliberately. A confirmed return and
        an unresolvable one are ranked differently, but neither is silently
        dropped: a false positive costs you a glance, a false negative costs
        you the reply.
        """

        return not self.answered or self.replied_again or self.unclear_after_answer

    @property
    def status(self) -> CandidateStatus:
        """This person's status as a typed value.

        Extracted from the legacy ``label()``, which built a dropdown string.
        The status is a domain fact; how a dropdown renders it is not, so the
        formatting stays in the interface layer and only this crosses over.
        """

        if self.replied_again:
            return CandidateStatus.RETURNED_AFTER_ANSWER
        if self.unclear_after_answer:
            return CandidateStatus.UNCLEAR_AFTER_ANSWER
        if self.answered:
            return CandidateStatus.ANSWERED
        if self.uncertain_target:
            return CandidateStatus.UNCLEAR_TARGET
        return CandidateStatus.NEVER_ANSWERED

    @property
    def state(self) -> str:
        """The status as its stored string. Kept for display and settings."""

        return self.status.value

    @property
    def reason(self) -> str:
        """Why this person has the status they have.

        For a human wondering why somebody is or is not in their queue. Never
        parsed, and never the thing a decision is made from.
        """

        if self.replied_again:
            return ("answered, then posted again afterwards naming you or "
                    "using the Reply button")
        if self.unclear_after_answer:
            return ("answered, then posted again with a mention that could "
                    "not be resolved; shown rather than guessed")
        if self.answered:
            return "you answered them and they have not come back"
        if self.uncertain_target:
            return ("their message names somebody not in this thread, so who "
                    "it is for could not be established")
        return "they addressed you and you have not answered"


def build_reply_candidates(
    owner_channel_id: str,
    owner_author: str,
    replies: Sequence[dict[str, Any]],
    thread_id: str = "",
) -> list[ReplyCandidate]:
    """Work out who is still owed a reply, using the thread itself as the log.

    A person is outstanding when you never answered them, or when their newest
    reply postdates your newest answer to them, which is exactly the case where
    they came back at you.

    A reply of yours with no @mention is NOT treated as answering anyone in
    particular; only a reply that names someone counts against that person.

    Replies aimed at another commenter are excluded entirely. Only people who
    addressed the owner, either with no mention at all or by naming the owner,
    can be owed an answer.
    """

    annotated = annotate_reply_targets(owner_author, replies, owner_channel_id)
    mine = [r for r in annotated if r.get("is_owner_reply")]

    # Only replies actually addressed to the owner create an obligation. A
    # reply opening "@SomeoneElse" is two viewers arguing under the comment,
    # and listing those as owed a reply buries the ones that are.
    # "unknown" joins the queue rather than being dropped. An unresolvable
    # mention is uncertainty, and uncertainty must be surfaced, not silently
    # resolved against the owner's interest.
    theirs = [
        r
        for r in annotated
        if not r.get("is_owner_reply")
        and r.get("target_state") in ("owner", "unknown")
    ]

    # Map handles to channel IDs so answered-state survives a display-name
    # change. Your replies can only name a handle, so this is the bridge.
    channel_of_handle = {
        str(r.get("author") or "").lstrip("@").casefold():
            str(r.get("author_channel_id") or "")
        for r in theirs
        if r.get("author")
    }

    # A reply of the owner's with no @mention is NOT evidence that any
    # particular person was answered. Treating it as a blanket answer produced
    # silent false negatives: two people asked separate questions, the owner
    # posted one unmentioned follow-up, and both vanished from the queue. A
    # false positive costs a glance; a false negative costs the reply.
    answered_at: dict[str, datetime] = {}
    floor = datetime.min.replace(tzinfo=timezone.utc)
    for reply in mine:
        stamp = as_moment(reply.get("published_at"))
        target = str(reply.get("responds_to_author") or "").casefold()
        if target and target != str(owner_author or "").lstrip("@").casefold():
            key = channel_of_handle.get(target) or ("name:" + target)
            answered_at[key] = max(answered_at.get(key, floor), stamp)
        # An unmentioned owner reply is context, not an answer to anyone.

    # Key by channel ID. Display names are not unique and can change, so
    # keying by them merges strangers and splits one person into two.
    by_person: dict[str, list[dict[str, Any]]] = {}
    for reply in theirs:
        key = str(reply.get("author_channel_id") or "") or (
            "name:" + str(reply.get("author") or "").casefold()
        )
        by_person.setdefault(key, []).append(reply)

    candidates: list[ReplyCandidate] = []
    for key, posts in by_person.items():
        posts.sort(key=lambda reply: as_moment(reply.get("published_at")))
        newest = posts[-1]
        handle = str(newest.get("author") or "").lstrip("@")
        channel = str(newest.get("author_channel_id") or "")
        my_answer = max(
            answered_at.get(channel, floor),
            answered_at.get("name:" + handle.casefold(), floor),
        )
        answered = my_answer > floor
        their_stamp = as_moment(newest.get("published_at"))

        # A confirmed return re-opens the obligation outright. An unresolvable
        # mention after an answer is a third thing, and collapsing it into
        # either neighbour is wrong in a different direction.
        #
        # Treating it as a return drags you back in every time somebody you
        # already answered joins a side conversation. Treating it as nothing
        # hides a real follow-up posted under your old handle, a display-name
        # variant, or a mention form this parser does not recognise. The
        # previous version did the second, which is the same false negative
        # this module already refused to accept elsewhere, arrived at by a
        # more sophisticated route.
        #
        # So it gets its own state: visible, ranked below confirmed returns,
        # never silently dropped.
        certain = [r for r in posts if r.get("target_state") == "owner"]
        newest_certain = (
            as_moment(certain[-1].get("published_at")) if certain else floor
        )
        replied_again = answered and newest_certain > my_answer
        unclear_after_answer = (
            answered
            and not replied_again
            and their_stamp > my_answer
            and any(r.get("target_state") == "unknown"
                    for r in posts
                    if as_moment(r.get("published_at")) > my_answer)
        )

        # Which of their messages to put in front of the reader:
        #   never answered  -> their strongest contribution, because a weak
        #                      afterthought should not displace a real
        #                      challenge that was never addressed
        #   came back       -> their strongest message since the last answer,
        #                      since everything before it was already handled
        if replied_again:
            pool = [
                r for r in certain
                if as_moment(r.get("published_at")) > my_answer
            ] or [certain[-1]]
        elif unclear_after_answer:
            pool = [r for r in posts
                    if as_moment(r.get("published_at")) > my_answer] or [newest]
        elif answered:
            pool = [newest]
        else:
            pool = posts
        target = max(pool, key=score_reply)

        candidates.append(
            ReplyCandidate(
                author="@" + handle,
                reply=dict(target, answer_score=score_reply(target)),
                score=score_reply(target),
                my_last_answer=my_answer.isoformat() if answered else "",
                their_last_reply=their_stamp.isoformat(),
                answered=answered,
                replied_again=replied_again,
                thread_id=thread_id,
                channel_id=channel,
                message_count=len(posts),
                uncertain_target=target.get("target_state") == "unknown",
                unclear_after_answer=unclear_after_answer,
            )
        )

    # Confirmed returns first, then people never answered, then the ones whose
    # post-answer message could not be resolved. The last group is visible but
    # ranks below everything certain, which is the whole point of giving it a
    # state of its own instead of folding it into either neighbour.
    candidates.sort(
        key=lambda c: (
            c.replied_again,
            not c.answered,
            c.unclear_after_answer,
            c.score,
        ),
        reverse=True,
    )
    return candidates


def candidates_across_threads(
    owner_channel_id: str,
    threads: Sequence[OwnerThread],
) -> list[ReplyCandidate]:
    """Build candidates thread by thread, never from a flattened pool.

    Answered-state is a property of one conversation. Flattening every thread
    into one list let a general answer posted under thread A mark participants
    in unrelated thread B as answered, silently hiding them.
    """

    found: list[ReplyCandidate] = []
    for thread in threads:
        found.extend(
            build_reply_candidates(
                owner_channel_id,
                thread.comment.get("author", ""),
                thread.replies,
                thread_id=thread.comment_id,
            )
        )
    found.sort(
        key=lambda c: (c.replied_again, not c.answered, c.score),
        reverse=True,
    )
    return found
