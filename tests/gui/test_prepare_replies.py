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
    def __init__(self, author):
        self.author = author


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

    def triage(candidates, maximum_characters):
        seen["candidates"] = list(candidates)
        return "packet"

    result = run(triage_for=triage)

    assert [p.author for p in seen["candidates"]] == list(result.people)
    assert [p.author for p in result.session.targets] == list(result.people)


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
    result = run(model=options(reply_variations=("dry_one_liner",),
                               reply_approach_mode="custom",
                               dials={"grounding": "summary"}))

    assert result.session.kwargs["registers"] == ("dry_one_liner",)
    assert result.session.kwargs["dials"]["grounding"] == "summary"


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
