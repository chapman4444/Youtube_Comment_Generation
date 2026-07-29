"""Answered-state reconstruction: who is still owed a reply.

The thread is the log. No local state file records who was answered, because
the operator's own replies already carry that information in the form of an
@mention, and a state file would go stale the moment he replied from a phone.
"""

from __future__ import annotations

from llm_youtube_comment_generation.domain.candidates import (
    build_reply_candidates,
    candidates_across_threads,
    score_reply,
)
from llm_youtube_comment_generation.domain.threads import OwnerThread

OWNER = "UC" + "o" * 22


def owner_reply(reply, comment_id, text, when):
    return reply(comment_id, "@owner", text, when, channel_id=OWNER)


def only(candidates, author):
    found = [c for c in candidates if c.author == author]
    assert found, f"{author} is not in {[c.author for c in candidates]}"
    return found[0]


def test_person_never_answered_is_outstanding(reply):
    replies = [reply("r1", "@alice", "you are wrong", "2026-01-01T00:00:00Z")]
    candidates = build_reply_candidates(OWNER, "@owner", replies)

    assert only(candidates, "@alice").outstanding is True
    assert only(candidates, "@alice").answered is False


def test_person_already_answered_is_not_outstanding(reply):
    replies = [
        reply("r1", "@alice", "you are wrong", "2026-01-01T00:00:00Z"),
        owner_reply(reply, "r2", "@alice no I am not", "2026-01-02T00:00:00Z"),
    ]
    candidates = build_reply_candidates(OWNER, "@owner", replies)

    assert only(candidates, "@alice").answered is True
    assert only(candidates, "@alice").outstanding is False


def test_person_who_replied_again_is_outstanding_once_more(reply):
    replies = [
        reply("r1", "@alice", "you are wrong", "2026-01-01T00:00:00Z"),
        owner_reply(reply, "r2", "@alice no", "2026-01-02T00:00:00Z"),
        reply("r3", "@alice", "still wrong actually", "2026-01-03T00:00:00Z"),
    ]
    candidate = only(build_reply_candidates(OWNER, "@owner", replies), "@alice")

    assert candidate.answered is True
    assert candidate.replied_again is True
    assert candidate.outstanding is True


def test_answered_people_leave_the_outstanding_queue(reply):
    replies = [
        reply("r1", "@alice", "question one", "2026-01-01T00:00:00Z"),
        reply("r2", "@bob", "question two", "2026-01-01T01:00:00Z"),
        owner_reply(reply, "r3", "@alice answered", "2026-01-02T00:00:00Z"),
    ]
    candidates = build_reply_candidates(OWNER, "@owner", replies)
    outstanding = [c.author for c in candidates if c.outstanding]

    assert outstanding == ["@bob"]


def test_answered_state_survives_a_display_name_change(reply):
    """Your reply can only name a handle, so channel ID is the bridge.

    Alice posts twice under two different display names from one channel. The
    answer names the first handle; she must still count as answered.
    """

    channel = "UC" + "a" * 22
    replies = [
        reply("r1", "@alice", "first", "2026-01-01T00:00:00Z", channel_id=channel),
        owner_reply(reply, "r2", "@alice answered", "2026-01-02T00:00:00Z"),
        reply("r3", "@aliceRenamed", "second", "2026-01-01T12:00:00Z",
              channel_id=channel),
    ]
    candidates = build_reply_candidates(OWNER, "@owner", replies)

    assert len(candidates) == 1
    assert candidates[0].answered is True


def test_people_are_keyed_by_channel_not_display_name(reply):
    """Display names are not unique.

    Keying by them merges two strangers who chose the same name and splits one
    person who renamed. Both failures are silent.
    """

    replies = [
        reply("r1", "@same", "one person", "2026-01-01T00:00:00Z",
              channel_id="UC" + "a" * 22),
        reply("r2", "@same", "different person", "2026-01-02T00:00:00Z",
              channel_id="UC" + "b" * 22),
    ]
    candidates = build_reply_candidates(OWNER, "@owner", replies)

    assert len(candidates) == 2
    assert {c.channel_id for c in candidates} == {"UC" + "a" * 22, "UC" + "b" * 22}


def test_a_general_owner_reply_answers_nobody_specific(reply):
    """An unmentioned reply of yours is context, not an answer.

    Treating it as a blanket answer produced silent false negatives: two people
    asked separate questions, the owner posted one unmentioned follow-up, and
    both vanished from the queue.
    """

    replies = [
        reply("r1", "@alice", "question one", "2026-01-01T00:00:00Z"),
        reply("r2", "@bob", "question two", "2026-01-01T01:00:00Z"),
        owner_reply(reply, "r3", "thanks everyone", "2026-01-02T00:00:00Z"),
    ]
    candidates = build_reply_candidates(OWNER, "@owner", replies)

    assert all(not c.answered for c in candidates)
    assert {c.author for c in candidates} == {"@alice", "@bob"}


def test_a_general_reply_no_longer_answers_everyone(reply):
    """The same rule stated as the regression it fixed."""

    replies = [
        reply("r1", "@alice", "a real challenge here", "2026-01-01T00:00:00Z"),
        owner_reply(reply, "r2", "good points all round", "2026-01-02T00:00:00Z"),
    ]
    assert only(build_reply_candidates(OWNER, "@owner", replies),
                "@alice").outstanding is True


def test_my_own_replies_are_never_listed_as_candidates(reply):
    replies = [
        reply("r1", "@alice", "challenge", "2026-01-01T00:00:00Z"),
        owner_reply(reply, "r2", "@alice answer", "2026-01-02T00:00:00Z"),
    ]
    candidates = build_reply_candidates(OWNER, "@owner", replies)

    assert "@owner" not in [c.author for c in candidates]


def test_side_conversations_are_never_listed_as_owed(reply):
    """Two viewers arguing under your comment owe you nothing."""

    replies = [
        reply("r1", "@alice", "first point", "2026-01-01T00:00:00Z"),
        reply("r2", "@bob", "@alice you are wrong", "2026-01-02T00:00:00Z"),
    ]
    candidates = build_reply_candidates(OWNER, "@owner", replies)

    assert [c.author for c in candidates] == ["@alice"]


def test_unknown_mentions_stay_in_the_queue(reply):
    """Uncertainty is surfaced, never resolved against the owner's interest."""

    replies = [reply("r1", "@carol", "@ghostuser what?", "2026-01-01T00:00:00Z")]
    candidates = build_reply_candidates(OWNER, "@owner", replies)

    assert [c.author for c in candidates] == ["@carol"]
    assert candidates[0].uncertain_target is True
    assert candidates[0].outstanding is True


def test_never_answered_targets_their_strongest_message(reply):
    """A weak afterthought must not displace a real unanswered challenge."""

    replies = [
        reply("r1", "@alice", "you are wrong because the source says otherwise",
              "2026-01-01T00:00:00Z", likes=50),
        reply("r2", "@alice", "lol", "2026-01-02T00:00:00Z"),
    ]
    candidate = only(build_reply_candidates(OWNER, "@owner", replies), "@alice")

    assert candidate.reply["comment_id"] == "r1"
    assert candidate.message_count == 2


def test_replied_again_targets_their_strongest_message_since_the_answer(reply):
    """Everything before the answer was already handled."""

    replies = [
        reply("r1", "@alice", "an early strong point with evidence",
              "2026-01-01T00:00:00Z", likes=99),
        owner_reply(reply, "r2", "@alice answered", "2026-01-02T00:00:00Z"),
        reply("r3", "@alice", "ok", "2026-01-03T00:00:00Z"),
        reply("r4", "@alice", "but actually the source disagrees with you",
              "2026-01-04T00:00:00Z", likes=8),
    ]
    candidate = only(build_reply_candidates(OWNER, "@owner", replies), "@alice")

    assert candidate.replied_again is True
    assert candidate.reply["comment_id"] == "r4"


def test_people_who_replied_again_sort_first(reply):
    replies = [
        reply("r1", "@alice", "a question for you", "2026-01-01T00:00:00Z"),
        reply("r2", "@bob", "another question", "2026-01-01T01:00:00Z", likes=500),
        owner_reply(reply, "r3", "@alice answered", "2026-01-02T00:00:00Z"),
        reply("r4", "@alice", "you did not address it", "2026-01-03T00:00:00Z"),
    ]
    candidates = build_reply_candidates(OWNER, "@owner", replies)

    assert candidates[0].author == "@alice"
    assert candidates[0].replied_again is True


def test_an_unresolvable_post_answer_reply_stays_visible_but_ranks_last(reply):
    """Its own state, because collapsing it either way is wrong.

    Treating it as a return drags you back in every time somebody you already
    answered joins a side conversation. Treating it as nothing hides a real
    follow-up posted under an unrecognised mention form.
    """

    replies = [
        reply("r1", "@alice", "a challenge", "2026-01-01T00:00:00Z"),
        owner_reply(reply, "r2", "@alice answered", "2026-01-02T00:00:00Z"),
        reply("r3", "@alice", "@ghostuser hmm", "2026-01-03T00:00:00Z"),
        reply("r4", "@bob", "never answered at all", "2026-01-01T06:00:00Z"),
    ]
    candidates = build_reply_candidates(OWNER, "@owner", replies)
    alice = only(candidates, "@alice")

    assert alice.unclear_after_answer is True
    assert alice.replied_again is False
    assert alice.outstanding is True
    # Ranked below the person who was never answered at all.
    assert [c.author for c in candidates].index("@bob") < \
           [c.author for c in candidates].index("@alice")


def test_confirmed_returns_outrank_unresolved_ones(reply):
    replies = [
        reply("a1", "@alice", "challenge", "2026-01-01T00:00:00Z"),
        owner_reply(reply, "a2", "@alice answered", "2026-01-02T00:00:00Z"),
        reply("a3", "@alice", "@ghostuser hmm", "2026-01-03T00:00:00Z"),
        reply("b1", "@bob", "challenge", "2026-01-01T00:00:00Z"),
        owner_reply(reply, "b2", "@bob answered", "2026-01-02T00:00:00Z"),
        reply("b3", "@bob", "you still have not said", "2026-01-03T00:00:00Z"),
    ]
    candidates = build_reply_candidates(OWNER, "@owner", replies)

    assert candidates[0].author == "@bob"
    assert candidates[0].replied_again is True


def test_a_resolvable_side_chat_does_not_re_open_the_obligation(reply):
    """A resolvable mention of somebody else is not a return to you."""

    replies = [
        reply("r1", "@alice", "challenge", "2026-01-01T00:00:00Z"),
        owner_reply(reply, "r2", "@alice answered", "2026-01-02T00:00:00Z"),
        reply("r3", "@bob", "unrelated", "2026-01-02T06:00:00Z"),
        reply("r4", "@alice", "@bob talking to you now", "2026-01-03T00:00:00Z"),
    ]
    alice = only(build_reply_candidates(OWNER, "@owner", replies), "@alice")

    assert alice.replied_again is False
    assert alice.unclear_after_answer is False
    assert alice.outstanding is False


def test_general_answer_does_not_leak_across_threads(reply):
    """Answered-state is a property of one conversation.

    Flattening every thread into one pool let an answer posted under thread A
    mark participants in unrelated thread B as answered, hiding them silently.
    """

    thread_a = OwnerThread(
        comment={"comment_id": "t1", "author": "@owner"},
        replies=[
            reply("a1", "@alice", "question in A", "2026-01-01T00:00:00Z"),
            owner_reply(reply, "a2", "@alice answered", "2026-01-02T00:00:00Z"),
        ],
    )
    thread_b = OwnerThread(
        comment={"comment_id": "t2", "author": "@owner"},
        replies=[
            reply("b1", "@alice", "different question in B",
                  "2026-01-01T00:00:00Z"),
        ],
    )
    candidates = candidates_across_threads(OWNER, [thread_a, thread_b])
    in_b = [c for c in candidates if c.thread_id == "t2"]

    assert len(in_b) == 1
    assert in_b[0].answered is False
    assert in_b[0].outstanding is True


def test_candidate_state_names_what_the_queue_shows(reply):
    """Superseded from test_candidate_labels_show_state_for_the_dropdown.

    The legacy test asserted on a formatted dropdown string. Formatting is an
    interface concern, so only the state word crossed into the domain. The old
    and new assertions are quoted in NOT_PORTED.md.
    """

    replies = [
        reply("r1", "@alice", "challenge", "2026-01-01T00:00:00Z"),
        owner_reply(reply, "r2", "@alice answered", "2026-01-02T00:00:00Z"),
        reply("r3", "@alice", "you did not address it", "2026-01-03T00:00:00Z"),
        reply("r4", "@bob", "new and unanswered", "2026-01-01T00:00:00Z"),
        reply("r5", "@carol", "@ghostuser hm", "2026-01-01T00:00:00Z"),
    ]
    candidates = build_reply_candidates(OWNER, "@owner", replies)

    assert only(candidates, "@alice").state == "replied again"
    assert only(candidates, "@bob").state == "new"
    assert only(candidates, "@carol").state == "unclear target"


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def test_scoring_rewards_a_reply_aimed_at_you(reply):
    aimed = dict(reply("r1", "@alice", "a real point here", "2026-01-01T00:00:00Z"),
                 responds_to_owner=True)
    aside = reply("r2", "@alice", "a real point here", "2026-01-01T00:00:00Z")

    assert score_reply(aimed) > score_reply(aside)


def test_scoring_punishes_a_throwaway(reply):
    """"lol", "exactly", an emoji. These are not owed an answer."""

    throwaway = reply("r1", "@alice", "lol", "2026-01-01T00:00:00Z")
    substantial = reply("r2", "@bob", " ".join(["word"] * 40),
                        "2026-01-01T00:00:00Z")

    assert score_reply(throwaway) < 0
    assert score_reply(substantial) > score_reply(throwaway)


def test_scoring_rewards_a_challenge_and_a_question(reply):
    plain = reply("r1", "@alice", " ".join(["word"] * 20), "2026-01-01T00:00:00Z")
    challenge = reply("r2", "@alice", "actually " + " ".join(["word"] * 19),
                      "2026-01-01T00:00:00Z")
    question = reply("r3", "@alice", " ".join(["word"] * 19) + "?",
                     "2026-01-01T00:00:00Z")

    assert score_reply(challenge) > score_reply(plain)
    assert score_reply(question) > score_reply(plain)


def test_likes_are_damped_rather_than_linear(reply):
    """100 likes is not ten times the signal of 10.

    The room has already voted, so likes dominate, but a runaway reply must
    not swamp every other consideration.
    """

    # Long enough to clear the short-reply penalty, or both scores go negative
    # and "less than ten times" stops meaning anything.
    text = " ".join(["word"] * 20)
    ten = reply("r1", "@a", text, "2026-01-01T00:00:00Z", likes=10)
    hundred = reply("r2", "@b", text, "2026-01-01T00:00:00Z", likes=100)

    assert score_reply(ten) > 0

    assert score_reply(hundred) > score_reply(ten)
    assert score_reply(hundred) < score_reply(ten) * 10
