"""The reply behaviours REPLY_SPEC.md listed as ported but never re-checked.

Every test here corresponds to one spec row and one hard-won legacy rule.
They are written from the *behaviour* described in the row rather than from
the current implementation, so a test that passes is evidence the behaviour
survived the migration rather than evidence the code still does what it does.

Spec rows covered: A4, B4, B5, B6, B8, C2, C3, C4, D2, D3, D4, E2, E3, E6,
E7, E8, F1, G4, G5, G6, G9.
"""

from __future__ import annotations

from llm_youtube_comment_generation.domain.candidates import (
    build_reply_candidates,
    candidates_across_threads,
)
from llm_youtube_comment_generation.domain.targeting import (
    annotate_reply_targets,
    leading_mention,
)
from llm_youtube_comment_generation.domain.threads import OwnerThread

OWNER = "UC" + "o" * 22


def message(cid, author, text, when, *, channel=None, likes=0):
    return {
        "comment_id": cid,
        "author": author,
        "author_channel_id": channel or (
            "UC" + author.lstrip("@").ljust(22, "z"))[:24],
        "text": text,
        "like_count": likes,
        "published_at": when,
        "updated_at": when,
    }


# --------------------------------------------------------------------------
# A. Time, and B. what the scan may claim
# --------------------------------------------------------------------------


def test_a4_a_fractional_second_does_not_sort_a_reply_backwards():
    """String comparison looked fine until a fractional second appeared:
    "…00.123Z" sorts BEFORE "…00Z" because "." precedes "Z", so a reply
    that arrived after the cutoff was reported as older than it."""

    from llm_youtube_comment_generation.domain.threads import as_moment

    assert as_moment("2026-07-01T12:00:00.123Z") > \
        as_moment("2026-07-01T12:00:00Z")


def test_a4_an_unparseable_timestamp_sorts_oldest_never_newest():
    """Unknown must never win a "which is newest" comparison, because that
    is how an unanswered reply gets treated as already handled."""

    from llm_youtube_comment_generation.domain.threads import as_moment

    assert as_moment("not a date") < as_moment("2000-01-01T00:00:00Z")
    assert as_moment("") < as_moment("2000-01-01T00:00:00Z")


def test_a4_an_unparseable_stamp_cannot_fake_a_return():
    """The queue rule that depends on it: a reply whose timestamp is
    unreadable must not postdate the owner's answer."""

    replies = [
        message("r1", "@alice", "a question", "2026-07-02T00:00:00Z"),
        message("r2", "@owner", "@alice my answer", "2026-07-03T00:00:00Z",
                channel=OWNER),
        message("r3", "@alice", "a later message", "nonsense-timestamp"),
    ]

    found = build_reply_candidates(OWNER, "@owner", replies, "t1")

    assert found[0].answered is True
    assert found[0].replied_again is False


def test_b4_b5_a_truncated_thread_reports_both_numbers_and_refuses_absence():
    """"I could not see it" must never become "it is not there". The note
    carries the reported and retrieved counts so the gap is visible."""

    from llm_youtube_comment_generation.domain.statuses import (
        RetrievalOutcome,
        RetrievalStatus,
    )

    thread = OwnerThread(
        comment=message("t1", "@owner", "my comment",
                        "2026-07-01T00:00:00Z", channel=OWNER),
        replies=[message("r1", "@alice", "a reply",
                         "2026-07-02T00:00:00Z")],
        reported_reply_count=178,
    )

    assert thread.truncated is True

    outcome = RetrievalOutcome(
        status=RetrievalStatus.REPLY_THREAD_TRUNCATED,
        retrieved=len(thread.replies),
        reported_total=thread.reported_reply_count,
        notes=(f"thread {thread.comment_id} reported "
               f"{thread.reported_reply_count:,} replies but "
               f"{len(thread.replies):,} were retrieved",),
    )

    assert outcome.may_conclude_absence is False
    assert "178" in outcome.notes[0] and "1" in outcome.notes[0]


def test_b6_threads_rank_by_replies_aimed_at_you_not_audience_volume():
    """A thread where forty people argue with each other is louder than one
    where three people asked you something. Ordering by volume put the side
    argument first."""

    from fakes import FakeClock, FakeEventSink, FakeYouTubePort
    from llm_youtube_comment_generation.application.scan_threads import (
        ScanMyThreadsCommand,
        handle,
    )

    loud = [
        message(f"loud{i}", f"@person{i}", f"@person{i - 1} you are wrong",
                "2026-07-02T00:00:00Z")
        for i in range(1, 6)
    ]
    aimed = [
        message(f"aimed{i}", f"@asker{i}", "a question for you",
                "2026-07-02T00:00:00Z")
        for i in range(1, 4)
    ]
    youtube = FakeYouTubePort(
        videos={"gC-J7zwYMAM": {"video_id": "gC-J7zwYMAM"}},
        comments=[
            dict(message("side", "@owner", "the loud thread",
                         "2026-07-01T00:00:00Z", channel=OWNER),
                 total_reply_count=len(loud)),
            dict(message("real", "@owner", "the thread aimed at me",
                         "2026-07-01T00:00:00Z", channel=OWNER),
                 total_reply_count=len(aimed)),
        ],
        replies={"side": loud, "real": aimed},
    )

    result = handle(ScanMyThreadsCommand("gC-J7zwYMAM", channel_id=OWNER),
                    youtube=youtube, events=FakeEventSink(),
                    clock=FakeClock())

    order = [t.comment_id for t in result.value.threads]
    assert order[0] == "real", order


def test_b8_replies_to_you_and_audience_replies_are_different_numbers():
    """On one real thread 161 audience replies contained only 92 aimed at
    the owner. Reporting the first as the second is misleading."""

    thread = OwnerThread(
        comment=message("t1", "@owner", "my comment",
                        "2026-07-01T00:00:00Z", channel=OWNER),
        replies=[
            message("r1", "@alice", "aimed at you", "2026-07-02T00:00:00Z"),
            message("r2", "@bob", "@alice aimed at alice",
                    "2026-07-03T00:00:00Z"),
            message("r3", "@owner", "my own reply", "2026-07-04T00:00:00Z",
                    channel=OWNER),
        ],
    )

    assert len(thread.audience_replies(OWNER)) == 2      # owner's excluded
    assert len(thread.direct_replies(OWNER)) == 1        # only one aimed here


# --------------------------------------------------------------------------
# F. Scoring, and G. what the packet promises
# --------------------------------------------------------------------------


def test_f1_the_score_damps_likes_and_rewards_a_real_challenge():
    """Likes dominate because the room already voted, but damped: 100 likes
    is not ten times 10. Substance, disagreement, a question and being aimed
    at the owner all add; a three-word reaction is penalised."""

    from llm_youtube_comment_generation.domain.candidates import score_reply

    def reply(text, likes=0, to_owner=True):
        return {"text": text, "like_count": likes,
                "responds_to_owner": to_owner}

    ten = score_reply(reply("a perfectly ordinary reply here", likes=10))
    hundred = score_reply(reply("a perfectly ordinary reply here", likes=100))
    assert hundred < ten * 10          # damped, not linear
    assert hundred > ten

    plain = reply("this is a plain observation about the video")
    challenge = reply("actually that is wrong, the filing says otherwise")
    question = reply("what happened to the second permit?")
    assert score_reply(challenge) > score_reply(plain)
    assert score_reply(question) > score_reply(plain)

    aimed = score_reply(reply("a plain observation about it", to_owner=True))
    aside = score_reply(reply("a plain observation about it", to_owner=False))
    assert aimed > aside

    assert score_reply(reply("lol")) < 0        # under six words


def test_g4_the_packet_carries_the_refusal_path():
    """If a target cannot be answered from the evidence, one honest line and
    stop — never a different person, never an invention."""

    from llm_youtube_comment_generation.infrastructure import prompt_resources

    workflow = prompt_resources.load("reply_workflow.md").text
    compact = " ".join(workflow.split())

    assert "cannot be answered from the evidence" in compact
    assert "Never answer a different person instead" in compact
    assert "never manufacture a reply" in compact


def test_g5_the_option_block_sits_outside_the_untrusted_boundary():
    """Dial-driven overrides are instructions; putting them inside the
    boundary would make the packet tell the model to obey evidence."""

    from llm_youtube_comment_generation.domain.reply_packet import (
        ReplyEvidence,
        build_reply_packet,
    )
    from llm_youtube_comment_generation.domain.sanitize import (
        SOURCE_BOUNDARY_OPEN,
    )
    from llm_youtube_comment_generation.infrastructure import prompt_resources

    thread = OwnerThread(
        comment=message("t1", "@owner", "my comment", "2026-07-01T00:00:00Z",
                        channel=OWNER),
        replies=[message("r1", "@alice", "a question",
                         "2026-07-02T00:00:00Z")],
    )
    packet = build_reply_packet(
        ReplyEvidence(thread=thread, owner_channel_id=OWNER),
        workflow_template=prompt_resources.load("reply_workflow.md").text,
        final_check_template=prompt_resources.load(
            "reply_final_check.md").text,
        dials={"hedging": "none", "ending": "flat"},
    )

    assert "## Output options" in packet.instructions
    assert packet.text.index("## Output options") < \
        packet.text.index(SOURCE_BOUNDARY_OPEN)
    assert "[hedging=none]" in packet.instructions


def test_g6_the_validator_enforces_its_stated_invariants():
    """Placeholders filled, one boundary pair in order, every promised
    heading present, the final check after the close."""

    import re

    from llm_youtube_comment_generation.domain.reply_packet import (
        ReplyEvidence,
        build_reply_packet,
    )
    from llm_youtube_comment_generation.domain.sanitize import (
        SOURCE_BOUNDARY_CLOSE,
        SOURCE_BOUNDARY_OPEN,
    )
    from llm_youtube_comment_generation.infrastructure import prompt_resources

    thread = OwnerThread(
        comment=message("t1", "@owner", "my comment", "2026-07-01T00:00:00Z",
                        channel=OWNER),
        replies=[message("r1", "@alice", "a question",
                         "2026-07-02T00:00:00Z")],
    )
    packet = build_reply_packet(
        ReplyEvidence(thread=thread, owner_channel_id=OWNER),
        workflow_template=prompt_resources.load("reply_workflow.md").text,
        final_check_template=prompt_resources.load(
            "reply_final_check.md").text,
    )

    assert re.search(r"\{[a-z_]+\}", packet.instructions) is None
    assert packet.text.count(SOURCE_BOUNDARY_OPEN) == 1
    assert packet.text.count(SOURCE_BOUNDARY_CLOSE) == 1
    assert packet.text.index(SOURCE_BOUNDARY_OPEN) < \
        packet.text.index(SOURCE_BOUNDARY_CLOSE)
    for heading in packet.headings:
        assert packet.instructions.count(heading) >= 1
    assert packet.text.index("FINAL OUTPUT CHECK") > \
        packet.text.index(SOURCE_BOUNDARY_CLOSE)


def test_g9_the_thread_section_states_its_own_coverage():
    """Reported versus retrieved versus targets versus context, stated in
    the packet rather than implied by what happens to be present."""

    from llm_youtube_comment_generation.domain.reply_packet import (
        ReplyEvidence,
        build_reply_packet,
    )
    from llm_youtube_comment_generation.infrastructure import prompt_resources

    thread = OwnerThread(
        comment=message("t1", "@owner", "my comment", "2026-07-01T00:00:00Z",
                        channel=OWNER),
        replies=[
            message("r1", "@alice", "a question", "2026-07-02T00:00:00Z"),
            message("r2", "@owner", "@alice my answer",
                    "2026-07-03T00:00:00Z", channel=OWNER),
        ],
        reported_reply_count=2,
    )
    packet = build_reply_packet(
        ReplyEvidence(thread=thread, owner_channel_id=OWNER),
        workflow_template=prompt_resources.load("reply_workflow.md").text,
        final_check_template=prompt_resources.load(
            "reply_final_check.md").text,
    )

    assert "- replies_reported_by_api: 2" in packet.evidence
    assert "- replies_retrieved: 2" in packet.evidence
    assert "- targets: 1" in packet.evidence
    assert "- context_only_owner_replies: 1" in packet.evidence


def test_d4_uncertainty_is_stated_as_uncertainty():
    """"Could not be matched" is the honest rendering. Stating a guess as a
    fact is how the model answers the wrong person confidently."""

    from llm_youtube_comment_generation.domain.reply_packet import (
        ReplyEvidence,
        build_reply_packet,
    )
    from llm_youtube_comment_generation.infrastructure import prompt_resources

    thread = OwnerThread(
        comment=message("t1", "@owner", "my comment", "2026-07-01T00:00:00Z",
                        channel=OWNER),
        replies=[message("r1", "@carol", "@ghostwriter what do you think",
                         "2026-07-02T00:00:00Z")],
    )
    packet = build_reply_packet(
        ReplyEvidence(thread=thread, owner_channel_id=OWNER),
        workflow_template=prompt_resources.load("reply_workflow.md").text,
        final_check_template=prompt_resources.load(
            "reply_final_check.md").text,
    )
    compact = " ".join(packet.instructions.split())

    assert "- relationship: unresolved" in packet.evidence
    assert "could not be matched to anyone in the thread" in compact
    assert "who it answers is unknown" in compact


# --------------------------------------------------------------------------
# C. Mention parsing
# --------------------------------------------------------------------------


def test_c2_a_mention_with_non_ascii_letters_is_captured_whole():
    """`@José` is one handle, not `@Jos` plus a stray letter."""

    known = ["José", "Ana-María", "Владимир"]

    assert leading_mention("@José you are wrong", known) == "José"
    assert leading_mention("@Ana-María that is true", known) == "Ana-María"
    assert leading_mention("@Владимир no", known) == "Владимир"


def test_c3_a_run_together_mention_resolves_to_the_longest_known_handle():
    """YouTube renders the mention with no separator, so "@somebodyno, but"
    is a mention of "somebody" followed by the word "no"."""

    known = ["normagraham3", "somebodyelse"]

    assert leading_mention("@normagraham3omg I know a company",
                           known) == "normagraham3"


def test_c3_a_digit_remainder_is_refused_as_another_account():
    """"@alice123" is far more likely a different account than a mention of
    "alice" followed by the number 123."""

    assert leading_mention("@alice123 hello", ["alice"]) == "alice123"


def test_c3_a_short_handle_is_not_taken_as_a_prefix():
    """A handle under eight characters colliding by chance is likely;
    "@aliceabc" is not a mention of "alice"."""

    assert leading_mention("@aliceabc hello", ["alice"]) == "aliceabc"


def test_c3_an_exact_hit_always_wins():
    known = ["alice", "aliceabc"]

    assert leading_mention("@aliceabc hi", known) == "aliceabc"
    assert leading_mention("@alice hi", known) == "alice"


def test_c4_an_unresolvable_mention_is_reported_as_written():
    """Never guessed into a real person: the token is returned as typed and
    the reply is classified unknown rather than attributed."""

    replies = [message("r1", "@carol", "@ghostwriter what do you think",
                       "2026-07-02T00:00:00Z")]

    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["responds_to_author"] == "ghostwriter"
    assert annotated[0]["target_state"] == "unknown"
    assert annotated[0]["mentions_known_participant"] is False


# --------------------------------------------------------------------------
# H/I. Reading the operator's pastes back
# --------------------------------------------------------------------------


def test_h2_the_ranked_form_wins_and_skip_is_sticky():
    """A wrapped SKIP line looks exactly like a bare list of handles, and
    every person deliberately skipped became a target."""

    from llm_youtube_comment_generation.domain.extraction import (
        parse_triage_selection,
    )

    ranked = (
        "@alice | 1 | substantive challenge worth answering\n"
        "@bob | 2 | asks for a source\n"
        "SKIP: @lol, @spam"
    )
    assert parse_triage_selection(ranked) == ["@alice", "@bob"]

    # No ranked lines: the bare-list fallback, with SKIP sticky to the end
    # however many lines it wraps onto.
    wrapped = (
        "@alice\n@bob\n"
        "SKIP: @lol, @spam,\n"
        "@drive-by, @noise"
    )
    assert parse_triage_selection(wrapped) == ["@alice", "@bob"]


def test_h2_a_ranked_line_after_skip_restarts_the_wanted_list():
    from llm_youtube_comment_generation.domain.extraction import (
        parse_triage_selection,
    )

    text = "SKIP: @lol\n@alice | 1 | worth answering"

    assert parse_triage_selection(text) == ["@alice"]


def test_i3_a_pasted_reply_loses_only_its_wrappers():
    """Chat clients add fences, quote markers and surrounding quotes on
    copy. None of that is the reply, and all of it would post."""

    from llm_youtube_comment_generation.domain.extraction import (
        clean_pasted_reply,
    )

    assert clean_pasted_reply("```text\nthe reply\n```") == "the reply"
    assert clean_pasted_reply("> the reply\n> second line") == \
        "the reply\nsecond line"
    assert clean_pasted_reply('"the reply"') == "the reply"
    assert clean_pasted_reply("“the reply”") == "the reply"
    assert clean_pasted_reply("first\n\n\n\nsecond") == "first\n\nsecond"
    # A quotation inside the reply is the writer's, not a wrapper.
    assert clean_pasted_reply('he said "no" and left') == \
        'he said "no" and left'


# --------------------------------------------------------------------------
# J/K. History and the scoreboard
# --------------------------------------------------------------------------


def test_j8_a_history_failure_warns_and_never_loses_the_draft():
    """The deliverable is the reply. A scoreboard that cannot record it is
    a degraded scoreboard, not a lost draft."""

    from llm_youtube_comment_generation.application.guided_session import (
        AcceptedDraft,
        GuidedSession,
    )

    class Failing:
        def append(self, entries):
            raise RuntimeError("history is locked")

    session = GuidedSession(history=Failing())
    session.accepted.append(AcceptedDraft(author="@alice", draft="the reply"))

    try:
        session.record_posted(0)
    except RuntimeError as failure:
        assert "history is locked" in str(failure)

    # The draft survives the failure, unrecorded rather than discarded.
    assert session.accepted[0].draft == "the reply"
    assert session.accepted[0].posted_recorded is False


def test_k2_one_live_reply_satisfies_at_most_one_draft():
    """Prefix matching with nothing consumed let two drafts opening the same
    way both claim the same posted reply and its likes, which doubled the
    only numbers this project measures."""

    from llm_youtube_comment_generation.domain.history import score_history
    from llm_youtube_comment_generation.domain.statuses import (
        HistoryMatchStatus,
    )

    posted = [{"text": "The costs order is the whole story here.",
               "like_count": 12}]
    drafts = [
        {"draft": "The costs order is the whole story here.",
         "video_id": "v1"},
        {"draft": "The costs order is the whole story here, and more.",
         "video_id": "v1"},
    ]

    rows = score_history(posted, drafts, "v1")
    matched = [r for r in rows
               if r["match_status"] == HistoryMatchStatus.MATCHED]

    assert len(matched) == 1
    assert sum(int(r.get("likes") or 0) for r in matched) == 12


def test_k2_exact_matches_are_settled_before_prefixes():
    from llm_youtube_comment_generation.domain.history import score_history
    from llm_youtube_comment_generation.domain.statuses import (
        HistoryMatchStatus,
    )

    posted = [{"text": "the exact reply", "like_count": 5}]
    drafts = [
        {"draft": "the exact reply with a longer tail", "video_id": "v1"},
        {"draft": "the exact reply", "video_id": "v1"},
    ]

    rows = {r["draft"]: r for r in score_history(posted, drafts, "v1")}

    assert rows["the exact reply"]["match_status"] \
        == HistoryMatchStatus.MATCHED


def test_k2_ambiguous_is_not_unmatched():
    """One says the reply cannot be identified, the other says it is not
    there. Collapsing them puts an uncertain row under a finding."""

    from llm_youtube_comment_generation.domain.statuses import (
        HistoryMatchStatus,
    )

    assert HistoryMatchStatus.AMBIGUOUS != HistoryMatchStatus.UNMATCHED


# --------------------------------------------------------------------------
# D. Target annotation
# --------------------------------------------------------------------------


def test_d2_the_owner_is_recognised_by_channel_id_not_display_name():
    """Channel id is stable; the display name is not. An impostor using the
    owner's display name must not be read as the owner."""

    replies = [
        message("r1", "@owner", "posted from my other account",
                "2026-07-02T00:00:00Z", channel=OWNER),
        message("r2", "@owner", "I am not the real owner",
                "2026-07-03T00:00:00Z", channel="UC" + "f" * 22),
    ]

    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["is_owner_reply"] is True
    assert annotated[0]["target_state"] == "owner_reply"
    assert annotated[1]["is_owner_reply"] is False


def test_d2_a_renamed_owner_is_still_recognised():
    """The owner's display name changed since the comment was posted; the
    channel id did not."""

    replies = [message("r1", "@my-new-name", "following up on my own point",
                       "2026-07-02T00:00:00Z", channel=OWNER)]

    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["target_state"] == "owner_reply"


def test_d3_a_reply_with_no_mention_is_addressed_to_the_owner():
    """That is what YouTube's Reply button on the owner's comment produces,
    and it is the commonest shape in a real thread."""

    replies = [message("r1", "@alice", "I was part of a case like this",
                       "2026-07-02T00:00:00Z")]

    annotated = annotate_reply_targets("@owner", replies, OWNER)

    assert annotated[0]["target_state"] == "owner"
    assert annotated[0]["responds_to_owner"] is True
    assert annotated[0]["responds_to_author"] == ""


# --------------------------------------------------------------------------
# E. Answered-state
# --------------------------------------------------------------------------


def test_e2_an_unmentioned_owner_reply_answers_nobody():
    """The highest-value rule in the file. Two people asked separate
    questions, the owner posted one unmentioned follow-up, and both
    vanished from the queue. A false positive costs a glance; a false
    negative costs the reply."""

    replies = [
        message("r1", "@alice", "a question about the costs order",
                "2026-07-02T00:00:00Z"),
        message("r2", "@bob", "a different question about the lease",
                "2026-07-02T01:00:00Z"),
        message("r3", "@owner", "good points all round, thanks everyone",
                "2026-07-03T00:00:00Z", channel=OWNER),
    ]

    found = build_reply_candidates(OWNER, "@owner", replies, "t1")

    assert {c.author for c in found} == {"@alice", "@bob"}
    assert all(not c.answered for c in found)
    assert all(c.outstanding for c in found)


def test_e2_a_mentioned_owner_reply_answers_only_that_person():
    replies = [
        message("r1", "@alice", "a question", "2026-07-02T00:00:00Z"),
        message("r2", "@bob", "another question", "2026-07-02T01:00:00Z"),
        message("r3", "@owner", "@alice here is the answer",
                "2026-07-03T00:00:00Z", channel=OWNER),
    ]

    found = {c.author: c for c in
             build_reply_candidates(OWNER, "@owner", replies, "t1")}

    assert found["@alice"].answered is True
    assert found["@bob"].answered is False


def test_e3_answered_state_survives_a_display_name_change():
    """Keyed by channel id, with a handle bridge: the owner's reply can only
    name a handle, so the two have to be reconciled."""

    channel = "UC" + "a" * 22
    replies = [
        message("r1", "@alice", "a question", "2026-07-02T00:00:00Z",
                channel=channel),
        message("r2", "@owner", "@alice here is the answer",
                "2026-07-03T00:00:00Z", channel=OWNER),
        message("r3", "@alice-renamed", "thanks, that clears it up",
                "2026-07-04T00:00:00Z", channel=channel),
    ]

    found = build_reply_candidates(OWNER, "@owner", replies, "t1")

    # One person, not two: the rename did not split them.
    assert len(found) == 1
    assert found[0].answered is True
    assert found[0].message_count == 2


def test_e6_a_never_answered_person_shows_their_strongest_message():
    """A weak afterthought must not displace a real challenge that was
    never addressed."""

    replies = [
        message("r1", "@alice",
                "actually the filing says the permit was granted, which is "
                "the opposite of what the video claims",
                "2026-07-02T00:00:00Z", likes=40),
        message("r2", "@alice", "anyway", "2026-07-03T00:00:00Z"),
    ]

    found = build_reply_candidates(OWNER, "@owner", replies, "t1")

    assert found[0].reply["comment_id"] == "r1"
    assert found[0].message_count == 2


def test_e6_a_returner_shows_their_strongest_message_since_your_answer():
    """Everything before the answer was already handled."""

    replies = [
        message("r1", "@alice", "the first challenge", "2026-07-02T00:00:00Z",
                likes=99),
        message("r2", "@owner", "@alice my answer", "2026-07-03T00:00:00Z",
                channel=OWNER),
        message("r3", "@alice", "you did not address the second half at all",
                "2026-07-04T00:00:00Z", likes=5),
    ]

    found = build_reply_candidates(OWNER, "@owner", replies, "t1")

    assert found[0].replied_again is True
    assert found[0].reply["comment_id"] == "r3"


def test_e7_the_queue_ranks_returns_then_new_then_unclear():
    replies = [
        # Never answered.
        message("n1", "@newcomer", "a fresh question for you",
                "2026-07-05T00:00:00Z"),
        # Answered, then came back with a certain reply.
        message("r1", "@returner", "first challenge", "2026-07-02T00:00:00Z"),
        message("a1", "@owner", "@returner my answer",
                "2026-07-03T00:00:00Z", channel=OWNER),
        message("r2", "@returner", "you still have not answered it",
                "2026-07-04T00:00:00Z"),
        # Answered, then posted again naming somebody absent.
        message("u1", "@unclear", "a question", "2026-07-02T00:00:00Z"),
        message("a2", "@owner", "@unclear my answer", "2026-07-03T00:00:00Z",
                channel=OWNER),
        message("u2", "@unclear", "@ghostwriter what do you think",
                "2026-07-04T00:00:00Z"),
    ]

    order = [c.author for c in
             build_reply_candidates(OWNER, "@owner", replies, "t1")]

    assert order.index("@returner") < order.index("@newcomer")
    assert order.index("@newcomer") < order.index("@unclear")


def test_e8_an_answer_in_one_thread_never_marks_another_answered():
    """Answered-state is a property of one conversation. Flattening let a
    general answer under thread A silently hide participants in thread B."""

    first = OwnerThread(
        comment=message("t1", "@owner", "my first comment",
                        "2026-07-01T00:00:00Z", channel=OWNER),
        replies=[
            message("r1", "@alice", "a question here",
                    "2026-07-02T00:00:00Z"),
            message("r2", "@owner", "@alice answered here",
                    "2026-07-03T00:00:00Z", channel=OWNER),
        ],
    )
    second = OwnerThread(
        comment=message("t2", "@owner", "my second comment",
                        "2026-07-01T00:00:00Z", channel=OWNER),
        replies=[
            message("r3", "@alice", "a different question over here",
                    "2026-07-02T00:00:00Z"),
        ],
    )

    found = candidates_across_threads(OWNER, [first, second])

    by_thread = {c.thread_id: c for c in found}
    assert by_thread["t1"].answered is True
    assert by_thread["t2"].answered is False
    assert by_thread["t2"].outstanding is True
