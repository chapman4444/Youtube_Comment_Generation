"""What the window's reply scan does, without a window or a network.

This is the entry point to the whole reply side and it had no tests: the live
run proved it works once, which is not the same as knowing which of its parts
is load-bearing.

Two things it must get right. The triage packet and the queue have to name the
same people -- built from one list, or a run asks a model about people it will
never offer. And a cancel has to be honoured between the units of work, not
after all of them.
"""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.interfaces.gui.builder import (
    ReplyRun,
    prepare_replies,
)
from llm_youtube_comment_generation.interfaces.gui.options import (
    PacketOptionsModel,
)
from llm_youtube_comment_generation.interfaces.gui.worker import (
    BackgroundJob,
    Cancelled,
)


class Person:
    def __init__(self, author, thread_id=None):
        self.author = author
        # Distinct threads by default; a shared id models thread-mates.
        self.thread_id = thread_id if thread_id is not None else author


class Scan:
    """What the CLI hands back from a scan."""

    def __init__(self, waiting, total=None):
        self.video_id = "gC-J7zwYMAM"
        self.video = {"video_id": self.video_id, "title": "A video"}
        self.threads = []
        self.waiting = waiting
        self.total = len(waiting) if total is None else total
        self.owner_channel_id = "UC" + "o" * 22


class Transcript:
    entries = ({"text": "a line", "start": 0.0, "duration": 1.0},)


def options(**kwargs) -> PacketOptionsModel:
    return PacketOptionsModel(video="gC-J7zwYMAM", my_handle="@owner", **kwargs)


def run(job=None, *, waiting=None, total=None, triage_for=None, scan=None,
        session_factory=None, model=None):
    people = waiting if waiting is not None else [Person("@alice"),
                                                  Person("@bob")]
    found = Scan(people, total)
    return prepare_replies(
        model or options(), job or BackgroundJob(),
        ports_factory=lambda events: {
            "youtube": object(), "transcripts": _Transcripts()},
        templates={"reply_workflow.md": "w", "reply_final_check.md": "c"},
        artifacts_for=lambda video_id, directory: f"store:{video_id}",
        session_factory=session_factory or (lambda **kwargs: _Session(kwargs)),
        scan=scan or (lambda **kwargs: found),
        triage_for=triage_for,
    )


class _Transcripts:
    def fetch(self, video_id, languages=()):
        return Transcript()


class _Session:
    def __init__(self, kwargs):
        self.kwargs = kwargs
        self.targets = list(kwargs.get("waiting", ()))


# -- what it hands back ----------------------------------------------------


def test_it_returns_a_session_and_a_triage_packet_together():
    result = run(triage_for=lambda **kwargs: "the triage packet")

    assert isinstance(result, ReplyRun)
    assert result.session is not None
    assert result.triage_packet == "the triage packet"


def test_the_triage_packet_names_the_people_the_queue_will_offer():
    """Built from one list. Two lists is how a run asks a model about people
    it will never show."""

    seen = {}

    def triage(candidates, maximum_characters, video=None, threads=()):
        seen["candidates"] = list(candidates)
        seen["video"] = video
        return "packet"

    result = run(triage_for=triage)

    assert [p.author for p in seen["candidates"]] == list(result.people)
    assert [p.author for p in result.session.targets] == list(result.people)
    # The scan's video record reaches the triage builder — without it the
    # packet lists replies to a comment it never shows, on a video it never
    # names, and the reader has no ground for any verdict.
    assert seen["video"], "triage_for was not handed the video record"


def test_nobody_waiting_means_no_triage_packet():
    """A triage packet listing nobody asks a model to choose from an empty
    list, which costs a paste to be told what the window already knows."""

    result = run(waiting=[], triage_for=lambda **kwargs: "should not be built")

    assert result.triage_packet == ""
    assert result.people == ()


def test_no_triage_builder_is_allowed_and_skips_that_step():
    result = run(triage_for=None)

    assert result.triage_packet == ""
    assert result.people == ("@alice", "@bob")


# -- what it tells the operator --------------------------------------------


def test_the_guided_limit_bounds_session_triage_and_run_alike():
    """The limit is resolved once. The review caught triage ranking people
    the limit had withheld from the session, so acting on the ranking
    targeted somebody with no packet."""

    seen = {}

    def triage(candidates, **kwargs):
        seen["candidates"] = list(candidates)
        return "triage"

    result = run(
        waiting=[Person("@alice"), Person("@bob"), Person("@carol")],
        model=options(guided_limit=2),
        triage_for=triage,
    )

    offered = result.session.kwargs["waiting"]
    assert [p.author for p in offered] == ["@alice", "@bob"]
    assert [p.author for p in seen["candidates"]] == ["@alice", "@bob"]
    assert result.people == ("@alice", "@bob")


def test_top_repliers_narrows_the_run_to_the_most_liked():
    people = [
        Person("@quiet", thread_id="t1"),
        Person("@loud", thread_id="t2"),
    ]
    people[0].reply = {"like_count": 1}
    people[1].reply = {"like_count": 40}

    result = run(waiting=people, model=options(top_repliers=1))

    assert result.people == ("@loud",)


def test_per_thread_widens_the_run_to_every_answered_thread():
    class ThreadStub:
        def __init__(self, comment_id, replies):
            self.comment_id = comment_id
            self.replies = replies

    found = Scan([Person("@alice", thread_id="t1")])
    found.threads = [
        ThreadStub("t1", [{"author": "@alice"}]),
        ThreadStub("t2", [{"author": "@dave", "comment_id": "x1"}]),
    ]

    result = run(scan=lambda **kwargs: found, model=options(per_thread=True))

    assert [p.thread_id for p in result.session.kwargs["waiting"]] \
        == ["t1", "t2"]


def test_reply_runs_fall_back_on_dials_the_batch_contract_cannot_carry():
    """A preset is a bundle, not a per-run instruction: "Evidence first"
    carries grounding=summary for comments, and refusing the whole reply
    build over it would strand the operator."""

    model = options()
    model.dials = {"grounding": "summary", "person": "to_author"}

    result = run(model=model)

    dials = result.session.kwargs["dials"]
    assert dials["grounding"] != "summary"
    assert dials["person"] != "to_author"


def test_the_limit_counts_threads_and_never_splits_one():
    """Alice and Bob share a thread: the packet answers both, so a limit
    that dropped Bob would lie. The limit bounds threads, whole."""

    result = run(
        waiting=[
            Person("@alice", thread_id="t1"),
            Person("@bob", thread_id="t1"),
            Person("@carol", thread_id="t2"),
        ],
        model=options(guided_limit=1),
    )

    offered = result.session.kwargs["waiting"]
    assert [p.author for p in offered] == ["@alice", "@bob"]
    assert result.people == ("@alice", "@bob")


def test_it_counts_the_waiting_against_everyone_found():
    """"2 of 2" and "2 of 40" are different situations and the second is the
    one worth knowing about."""

    job = BackgroundJob()
    run(job, total=40)

    said = [event.message for event in job.drain()]

    assert any("2 of 40 people are waiting" in message for message in said)


def test_it_says_it_is_starting_before_the_slow_part():
    job = BackgroundJob()
    run(job)

    first = job.drain()[0]

    assert "Scanning" in first.message
    assert first.fraction is not None


# -- cancelling ------------------------------------------------------------


def test_a_cancel_before_the_scan_stops_before_spending_a_request():
    job = BackgroundJob()
    job.cancel()
    called = []

    with pytest.raises(Cancelled):
        run(job, scan=lambda **kwargs: called.append(1))

    assert called == [], "it scanned anyway"


def test_a_cancel_during_the_scan_stops_before_the_transcript():
    """The transcript is a separate fetch; stopping between them is the whole
    point of checking between units of work."""

    job = BackgroundJob()

    def scan_then_cancel(**kwargs):
        job.cancel()
        return Scan([Person("@alice")])

    with pytest.raises(Cancelled):
        run(job, scan=scan_then_cancel)


# -- what the session is given ---------------------------------------------


def test_the_chosen_registers_and_dials_reach_the_session():
    """Every dial the batch reply contract can carry arrives untouched; the
    ones it cannot are covered by the fall-back test above."""

    result = run(model=options(reply_variations=("dry_one_liner",),
                               reply_approach_mode="custom",
                               dials={"humor": "none", "ending": "flat"}))

    assert result.session.kwargs["registers"] == ("dry_one_liner",)
    assert result.session.kwargs["dials"]["humor"] == "none"
    assert result.session.kwargs["dials"]["ending"] == "flat"


def test_no_register_chosen_still_sends_the_reply_defaults():
    from llm_youtube_comment_generation.domain.writing_options import (
        DEFAULT_REPLY_VARIATIONS,
    )

    result = run()

    assert result.session.kwargs["registers"] == tuple(DEFAULT_REPLY_VARIATIONS)


def test_the_transcript_is_fetched_for_the_video_that_was_scanned():
    result = run()

    assert result.session.kwargs["transcript"].entries


def test_reply_scan_uses_its_own_depth_not_comment_evidence_limit():
    seen = {}

    def scan(**kwargs):
        seen.update(kwargs)
        return Scan([Person("@alice")])

    run(
        model=options(max_top=100, reply_scan_comments=4321),
        scan=scan,
    )

    assert seen["max_comments"] == 4321


def test_guided_limit_bounds_the_session_queue():
    people = [Person(f"@person{i}") for i in range(5)]

    result = run(
        waiting=people,
        model=options(guided_limit=2),
    )

    assert len(result.session.targets) == 2


def test_the_debug_checkbox_reaches_the_reply_session():
    """Found live 2026-08-15: Debug build checked, Reply mode, empty Debug
    tab. The comment path carried the flag from the start; this path
    shipped the checkbox live and never passed it."""

    result = run(model=options(debug_build=True))

    assert result.session.kwargs["debug_build"] is True
    settings = result.session.kwargs["debug_settings"]
    assert settings["mode"] == "reply"
    assert "retrieval_limits" in settings

    unchecked = run(model=options(debug_build=False))
    assert unchecked.session.kwargs["debug_build"] is False
