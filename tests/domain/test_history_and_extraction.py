"""History matching, and reading a deliverable back out of a pasted answer."""

from __future__ import annotations

from llm_youtube_comment_generation.domain.extraction import (
    clean_pasted_reply,
    extract_hardened_final,
    looks_like_packet_text,
    parse_triage_selection,
)
from llm_youtube_comment_generation.domain.history import (
    normalise_for_match,
    score_history,
)
from llm_youtube_comment_generation.domain.sanitize import SOURCE_BOUNDARY_OPEN


# --------------------------------------------------------------------------
# History matching
# --------------------------------------------------------------------------


def draft(text, video_id="v1"):
    return {"video_id": video_id, "draft": text}


def posted(text, likes=0):
    return {"text": text, "like_count": likes}


def test_normalisation_survives_a_trip_through_youtube():
    """The operator posts by hand and may edit, so matching is on text."""

    assert normalise_for_match("@alice Hello, World!") == "hello world"
    assert normalise_for_match("​@bob  x") == "x"
    assert normalise_for_match("") == ""


def test_scoring_matches_a_draft_that_was_edited_before_posting():
    """A prefix match is tolerant enough to survive a small edit."""

    history = [draft("the argument here is that the source disagrees")]
    live = [posted("the argument here is that the source disagrees, actually", 12)]

    scored = score_history(live, history, "v1")

    assert scored[0]["posted"] is True
    assert scored[0]["likes"] == 12
    assert scored[0]["match_status"] == "matched"


def test_scoring_ignores_other_videos():
    history = [draft("this one", "v1"), draft("another", "v2")]

    scored = score_history([posted("this one", 5)], history, "v1")

    assert len(scored) == 1
    assert scored[0]["draft"] == "this one"


def test_one_live_reply_is_never_credited_to_two_drafts():
    """Double-counting silently doubled the only numbers this project measures."""

    history = [
        draft("the same opening words and then one ending"),
        draft("the same opening words and then another ending"),
    ]
    live = [posted("the same opening words and then one ending", 40)]

    scored = score_history(live, history, "v1")
    matched = [row for row in scored if row["posted"]]

    assert len(matched) == 1
    assert sum(row["likes"] or 0 for row in scored) == 40


def test_two_identical_drafts_cannot_share_one_reply():
    history = [draft("identical text"), draft("identical text")]

    scored = score_history([posted("identical text", 7)], history, "v1")

    assert [row["posted"] for row in scored].count(True) == 1


def test_an_exact_match_is_settled_before_any_prefix_match():
    """A draft that merely opens like a reply cannot steal a certain match."""

    history = [
        draft("hello there this is the longer version of the draft"),
        draft("hello there"),
    ]
    live = [posted("hello there", 3)]

    scored = score_history(live, history, "v1")
    exact = [row for row in scored if row["draft"] == "hello there"][0]

    assert exact["posted"] is True
    assert exact["likes"] == 3


def test_a_draft_with_two_plausible_replies_is_ambiguous_not_unmatched():
    """Ambiguous says "cannot identify"; unmatched says "not there".

    Collapsing them puts an uncertain row under a heading that reads as a
    finding.
    """

    opening = "the shared opening contains enough specific words to compare safely"
    history = [draft(opening)]
    live = [
        posted(opening + " and one tail", 1),
        posted(opening + " and another tail", 2),
    ]

    scored = score_history(live, history, "v1")

    assert scored[0]["match_status"] == "ambiguous"
    assert scored[0]["posted"] is False


def test_an_ambiguous_row_is_never_shown_as_an_ordinary_miss():
    opening = "the shared opening contains enough specific words to compare safely"
    history = [draft(opening), draft("nowhere near anything posted")]
    live = [
        posted(opening + " and one tail", 1),
        posted(opening + " and another tail", 2),
    ]

    statuses = {row["draft"]: row["match_status"]
                for row in score_history(live, history, "v1")}

    assert statuses[opening] == "ambiguous"
    assert statuses["nowhere near anything posted"] == "unmatched"


def test_two_replies_still_match_two_drafts():
    """The consumption rule must not cost a legitimate second match."""

    history = [draft("first distinct draft"), draft("second distinct draft")]
    live = [posted("first distinct draft", 1), posted("second distinct draft", 2)]

    scored = score_history(live, history, "v1")

    assert [row["posted"] for row in scored] == [True, True]
    assert [row["likes"] for row in scored] == [1, 2]


def test_an_empty_draft_is_not_a_row_at_all():
    assert score_history([posted("x")], [draft("")], "v1") == []


def test_a_one_word_live_prefix_is_never_a_match():
    scored = score_history(
        [posted("this")],
        [draft("this is a complete and substantially longer drafted reply")],
        "v1",
    )

    assert scored[0]["match_status"] == "unmatched"


def test_post_kind_prevents_a_comment_from_matching_a_reply():
    text = "the exact same wording can still have different posting context"
    live = [{"text": text, "like_count": 7, "is_reply": False}]

    scored = score_history(
        live,
        [dict(draft(text), workflow="reply")],
        "v1",
    )

    assert scored[0]["match_status"] == "unmatched"


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def test_extraction_takes_only_the_deliverable_from_a_real_answer():
    answer = (
        "### 1. Dry one-liner\nSomething witty.\n\n"
        "### Harsh critique\nRanking and repairs.\n\n"
        "### Hardened final\nThe finished reply, ready to post.\n"
    )

    assert extract_hardened_final(answer) == "The finished reply, ready to post."


def test_extraction_survives_the_ways_a_heading_arrives():
    """Formatting accidents, not different intents."""

    for heading in ("### Hardened final", "**Hardened final**",
                    "Hardened final:", "3. Hardened final",
                    "## HARDENED FINAL", "_Hardened final_"):
        assert extract_hardened_final(f"{heading}\nthe reply") == "the reply", heading


def test_extraction_prefers_the_real_section_over_a_mention_of_it():
    """A model often names the section in its preamble before writing it."""

    answer = (
        "I will produce a Hardened final at the end.\n\n"
        "### Hardened final\nthe actual reply\n"
    )

    assert extract_hardened_final(answer) == "the actual reply"


def test_extraction_stops_at_anything_that_follows():
    answer = (
        "### Hardened final\nthe reply\n\n"
        "### Notes\ncommentary that must not be posted\n"
    )

    assert extract_hardened_final(answer) == "the reply"


def test_extraction_refuses_to_guess_when_there_is_no_section():
    """An empty string is a refusal.

    Handing back the critique, or the whole paste, would put text on the
    channel that was never meant to be posted.
    """

    assert extract_hardened_final("just some prose with no heading") == ""
    assert extract_hardened_final("") == ""
    assert extract_hardened_final(None) == ""


def test_extraction_strips_client_added_wrappers():
    assert extract_hardened_final("### Hardened final\n```\nthe reply\n```") == "the reply"
    assert extract_hardened_final("### Hardened final\n> the reply") == "the reply"
    assert extract_hardened_final('### Hardened final\n"the reply"') == "the reply"


def test_client_wrappers_are_stripped_directly():
    assert clean_pasted_reply("```\ntext\n```") == "text"
    assert clean_pasted_reply("> a\n> b") == "a\nb"
    assert clean_pasted_reply('"quoted"') == "quoted"
    assert clean_pasted_reply("“curly”") == "curly"
    assert clean_pasted_reply("a\n\n\n\n\nb") == "a\n\nb"
    assert clean_pasted_reply("") == ""


def test_packet_text_is_never_mistaken_for_an_answer():
    """The packet contains its own "### Hardened final" heading.

    Extraction happily returns the sentence describing the section, so a line
    of prompt text ends up in the file of replies ready to post. A wrong answer
    that looks like an answer is worse than an error.
    """

    assert looks_like_packet_text(f"{SOURCE_BOUNDARY_OPEN}\nevidence") is True
    assert looks_like_packet_text("## FINAL OUTPUT CHECK\n1. ...") is True
    assert looks_like_packet_text("# GLOBAL YOUTUBE REPLY WORKFLOW") is True
    assert looks_like_packet_text("# REPLY TRIAGE") is True


def test_packet_detection_is_specific():
    """A guard that rejects ordinary replies is worse than none."""

    assert looks_like_packet_text("A perfectly ordinary reply.") is False
    assert looks_like_packet_text("") is False


def test_the_packet_is_recognised_by_its_own_opening():
    packet = "# GLOBAL WORKFLOW\n" + "x" * 900
    assert looks_like_packet_text(packet[:500], packet) is True


# --------------------------------------------------------------------------
# Triage answers
# --------------------------------------------------------------------------


def test_triage_answer_parses_back_into_handles():
    answer = "@alice | 1 | a real challenge\n@bob | 2 | worth answering"

    assert parse_triage_selection(answer) == ["@alice", "@bob"]


def test_triage_answer_parses_a_bare_handle_list():
    """A reader will not always follow the format exactly."""

    assert parse_triage_selection("@alice\n@bob") == ["@alice", "@bob"]


def test_multiple_handles_on_one_line():
    assert parse_triage_selection("@alice @bob @carol") == ["@alice", "@bob", "@carol"]


def test_triage_answer_ignores_the_skip_line():
    answer = "@alice\nSKIP: @carol"

    assert parse_triage_selection(answer) == ["@alice"]


def test_real_triage_answer_survives_a_wrapped_skip_list():
    """SKIP is sticky, however many lines it wraps to.

    The tail of a wrapped SKIP line looks exactly like a bare handle list, and
    every person deliberately skipped became a target.
    """

    answer = (
        "@alice\n"
        "SKIP: @carol @dave because they are\n"
        "@eve @frank not worth answering\n"
    )

    assert parse_triage_selection(answer) == ["@alice"]


def test_the_ranked_form_wins_outright_when_present():
    """Reading only ranked lines means SKIP cannot leak in however it wraps."""

    answer = (
        "@alice | 1 | yes\n"
        "SKIP: @bob wrapped over\n"
        "@carol @dave two lines\n"
    )

    assert parse_triage_selection(answer) == ["@alice"]


def test_triage_answer_paste_keeps_only_the_ranked_handles():
    """The ranks, reasons and SKIP line are stripped from a pasted block."""

    block = (
        "@alice | 1 | must answer the low-bar objection\n"
        "@bob | 2 | asks for the corrected report\n"
        "SKIP: @lol, @nice, @agreed"
    )

    assert parse_triage_selection(block) == ["@alice", "@bob"]


def test_triage_answer_paste_survives_a_chatty_model():
    """Models add preamble. Handles must still come through, SKIP still out."""

    block = (
        "Here are the replies worth answering:\n\n"
        "@alice | 1 | substantive challenge\n\n"
        "SKIP: @jokeguy\n\n"
        "Let me know if you want these drafted."
    )

    assert parse_triage_selection(block) == ["@alice"]


def test_a_triage_answer_with_no_handles_is_rejected():
    assert parse_triage_selection("nothing here at all") == []
    assert parse_triage_selection("") == []


def test_a_repeated_handle_is_listed_once():
    assert parse_triage_selection("@alice @Alice @ALICE") == ["@alice"]
