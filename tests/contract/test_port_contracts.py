"""The behaviour every implementation of a port must satisfy.

These run against the fakes; test_real_adapters_honor_the_contracts.py in
this directory runs the same rules against every real adapter that can be
exercised without a network or a display. That is the point of a contract
test: it is the shared definition of correct, not a test of one
implementation — and for a year this file's own docstring promised the
real-adapter half while nothing ran it, which is how the fake history
store drifted a whole uniqueness rule away from the real one.

Where a rule exists because getting it wrong destroyed something, the test
says which thing.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fakes import (
    BrokenEventSink,
    FakeArtifactStore,
    FakeClipboard,
    FakeClock,
    FakeEventSink,
    FakeHistoryStore,
    FakeSettingsStore,
    FakeTranscriptPort,
    FakeYouTubePort,
)
from llm_youtube_comment_generation.domain.errors import (
    ConfigurationError,
    HistoryCorruptionError,
    QuotaExceededError,
)
from llm_youtube_comment_generation.domain.statuses import (
    RetrievalStatus,
    TranscriptAvailability,
)
from llm_youtube_comment_generation.ports import (
    ArtifactStore,
    ClipboardPort,
    ClockPort,
    EventKind,
    EventSink,
    HistoryStore,
    ProgressEvent,
    SettingsStore,
    TranscriptPort,
    YouTubePort,
)


# --------------------------------------------------------------------------
# Every fake actually satisfies the protocol it claims to
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fake, port", [
    (FakeClock(), ClockPort),
    (FakeClipboard(), ClipboardPort),
    (FakeEventSink(), EventSink),
    (FakeSettingsStore(), SettingsStore),
    (FakeHistoryStore(), HistoryStore),
    (FakeArtifactStore(), ArtifactStore),
    (FakeTranscriptPort(), TranscriptPort),
    (FakeYouTubePort(), YouTubePort),
], ids=lambda value: getattr(value, "__name__", type(value).__name__))
def test_the_fake_satisfies_its_port(fake, port):
    """Structural typing is only a promise until something checks it."""

    assert isinstance(fake, port)


def test_there_is_a_fake_for_every_port():
    """Phase 2's deliverable is eight ports and eight fakes.

    A missing fake is not a gap in coverage, it is a phase that cannot
    proceed: the rule is that no use case is written before its ports have
    fakes.
    """

    ports = {ArtifactStore, ClipboardPort, ClockPort, EventSink, HistoryStore,
             SettingsStore, TranscriptPort, YouTubePort}
    fakes = {FakeArtifactStore, FakeClipboard, FakeClock, FakeEventSink,
             FakeHistoryStore, FakeSettingsStore, FakeTranscriptPort,
             FakeYouTubePort}

    assert len(ports) == 8
    assert len(fakes) == 8


def test_the_youtube_port_cannot_post():
    """Read-only is a product decision, enforced at the boundary.

    The application never posts; the operator does, by hand. If a `post` ever
    appears on this port, a future use case can quietly acquire the ability,
    so the absence is asserted rather than assumed.
    """

    forbidden = [name for name in dir(YouTubePort)
                 if any(word in name.lower()
                        for word in ("post", "insert", "delete", "update",
                                     "write", "reply_to"))]

    assert forbidden == []


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------


def test_a_clock_is_always_timezone_aware():
    """A naive value compared against an aware one raises.

    That comparison is exactly what the reply cutoff does, so the port bars
    naive time rather than defending against it everywhere downstream.
    """

    assert FakeClock().now().tzinfo is not None
    assert FakeClock().now().utcoffset() == timezone.utc.utcoffset(None)

    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2026, 1, 1))


def test_a_clock_only_moves_when_it_is_told_to():
    clock = FakeClock()
    first = clock.now()

    assert clock.now() == first

    clock.advance(days=7)
    assert (clock.now() - first).days == 7


# --------------------------------------------------------------------------
# Clipboard
# --------------------------------------------------------------------------


def test_the_clipboard_round_trips():
    clipboard = FakeClipboard()
    clipboard.write("a packet")

    assert clipboard.read() == "a packet"


def test_the_clipboard_can_feed_a_packet_back_to_itself():
    """The collision the guided workflow has to survive.

    The application writes the packet to the clipboard, then asks for the
    answer on the same clipboard. A stray click submits the packet to itself,
    and the packet contains its own "### Hardened final" heading.
    """

    clipboard = FakeClipboard()
    packet = "# GLOBAL YOUTUBE REPLY WORKFLOW\n### Hardened final\n..."
    clipboard.write(packet)

    assert clipboard.read() == packet     # reproducible, without a display


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


def test_a_sink_records_what_happened_in_facts_not_prose():
    sink = FakeEventSink()
    sink.emit(ProgressEvent(EventKind.STEP, step="retrieve", message="Fetching"))
    sink.emit(ProgressEvent(EventKind.PROGRESS, current=50, total=200))

    assert sink.kinds() == [EventKind.STEP, EventKind.PROGRESS]
    assert sink.steps() == ["retrieve"]
    assert sink.events[1].fraction == 0.25


def test_unknown_progress_is_reported_as_unknown():
    """A bar that invents a denominator lies about how much is left."""

    assert ProgressEvent(EventKind.PROGRESS, current=5).fraction is None
    assert ProgressEvent(EventKind.PROGRESS, current=5, total=0).fraction is None


def test_progress_never_exceeds_its_total():
    event = ProgressEvent(EventKind.PROGRESS, current=250, total=200)

    assert event.fraction == 1.0


def test_a_broken_sink_is_the_callers_problem_to_absorb():
    """Contract: emit() must not raise. This proves the fake that breaks it.

    The rule matters because a destroyed window or a closed pipe must never
    take down the run that was reporting to it. Callers wrap emission; this
    records that BrokenEventSink is the fixture for testing that they do.
    """

    with pytest.raises(RuntimeError):
        BrokenEventSink().emit(ProgressEvent(EventKind.STEP))


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


def test_settings_round_trip():
    store = FakeSettingsStore()
    store.save({"editor": "notepad", "comment_variations": ["short_hook"]})

    assert store.load()["editor"] == "notepad"


def test_settings_never_persist_secrets():
    """A settings file is a thing operators paste into bug reports."""

    store = FakeSettingsStore()

    for field in ("api_key", "API_KEY", "auth_token", "client_secret"):
        with pytest.raises(ValueError, match="credential"):
            store.save({field: "AIzaSyExample"})


def test_unreadable_settings_are_a_fresh_start_not_a_refusal():
    """The operator would have no way to fix a file that stops the app opening."""

    store = FakeSettingsStore({"editor": "notepad"})
    store.unreadable = True

    assert store.load() == {}


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------


def test_a_missing_history_is_simply_an_empty_one():
    assert FakeHistoryStore().load() == []


def test_a_history_that_cannot_be_read_is_never_written_over():
    """The only irreplaceable state this application owns.

    Silently treating an unreadable history as empty and then appending is
    how the measurement record gets destroyed by the tool that keeps it.
    """

    store = FakeHistoryStore()
    store.corrupt = True

    with pytest.raises(HistoryCorruptionError):
        store.load()

    with pytest.raises(HistoryCorruptionError):
        store.append([{"video_id": "v1", "draft": "something"}])


def test_recording_the_same_draft_twice_adds_one_row():
    """Two rows for one reply would double-count the likes it earns."""

    store = FakeHistoryStore()
    entry = {"video_id": "v1", "draft": "the same reply text"}

    assert store.append([entry]) == 1
    assert store.append([entry]) == 0
    assert len(store.load()) == 1


def test_a_lightly_edited_draft_is_a_new_event_not_a_duplicate():
    """Persistence identity is the exact event; fuzzy matching is not it.

    The v1 store deduplicated on normalized text and merged genuinely
    distinct postings, which is why the v2 migration removed that rule.
    Normalized text lives on in match_key for the scoreboard to match likes
    with — matching is its job, identity is not. This fake asserted the v1
    rule for a year after the real store dropped it, precisely because no
    contract test ran against the real adapter.
    """

    store = FakeHistoryStore()
    store.append([{"video_id": "v1", "draft": "The Same Reply Text!"}])

    assert store.append([{"video_id": "v1", "draft": "the same reply text"}]) == 1


def test_an_empty_draft_is_never_recorded():
    assert FakeHistoryStore().append([{"video_id": "v1", "draft": "   "}]) == 0


def test_the_same_corruption_is_quarantined_once_not_once_per_draft():
    """Otherwise one problem becomes a directory full of them."""

    store = FakeHistoryStore()
    store.corrupt = True

    first = store.quarantine()
    store.corrupt = True
    second = store.quarantine()

    assert first == second
    assert len(store.quarantined) == 1


# --------------------------------------------------------------------------
# Artifacts
# --------------------------------------------------------------------------


def test_staged_files_are_not_visible_until_commit():
    store = FakeArtifactStore()
    store.stage("packet.md", "content")

    assert store.committed_names() == ()
    assert store.staged_names() == ("packet.md",)

    assert store.commit() == ("packet.md",)
    assert store.committed_names() == ("packet.md",)


def test_a_failed_commit_leaves_the_previous_output_intact():
    """A half-written set is worse than none: the operator cannot tell which
    half is stale."""

    store = FakeArtifactStore()
    store.stage("packet.md", "first run")
    store.commit()

    store.stage("packet.md", "second run")
    store.stage("report.md", "second run")
    store.fail_on_commit = "report.md"

    with pytest.raises(OSError):
        store.commit()

    assert store.read("packet.md") == "first run"
    assert store.committed_names() == ("packet.md",)


def test_rollback_discards_staged_work_only():
    store = FakeArtifactStore()
    store.stage("packet.md", "committed")
    store.commit()
    store.stage("scratch.md", "discarded")

    store.rollback()

    assert store.staged_names() == ()
    assert store.committed_names() == ("packet.md",)


def test_reading_an_absent_artifact_raises():
    with pytest.raises(FileNotFoundError):
        FakeArtifactStore().read("nothing.md")


# --------------------------------------------------------------------------
# Transcripts
# --------------------------------------------------------------------------


def test_a_transcript_is_returned_with_its_language():
    result = FakeTranscriptPort().fetch("gC-J7zwYMAM")

    assert result.available is True
    assert result.availability is TranscriptAvailability.AVAILABLE
    assert result.entries


@pytest.mark.parametrize("state", [
    TranscriptAvailability.NOT_PUBLISHED,
    TranscriptAvailability.NOT_PUBLIC,
    TranscriptAvailability.LANGUAGE_UNAVAILABLE,
    TranscriptAvailability.EMPTY,
    TranscriptAvailability.FETCH_FAILED,
])
def test_the_fake_can_return_each_unavailable_state(state):
    """Each failure is a distinct state, not one boolean and some English.

    The legacy pipeline had `available: bool` plus a free-text error, so a
    caller wanting to tell "no captions exist" from "the library raised" had
    to match on prose.
    """

    result = FakeTranscriptPort(availability=state).fetch("gC-J7zwYMAM")

    assert result.available is False
    assert result.availability is state


def test_a_missing_transcript_never_raises():
    """An absent transcript is an ordinary outcome; the packet is still worth
    building, so it must not fail the run."""

    result = FakeTranscriptPort(
        availability=TranscriptAvailability.NOT_PUBLISHED
    ).fetch("gC-J7zwYMAM")

    assert result.availability is TranscriptAvailability.NOT_PUBLISHED


# --------------------------------------------------------------------------
# YouTube
# --------------------------------------------------------------------------


def video_fixture():
    return {"gC-J7zwYMAM": {"video_id": "gC-J7zwYMAM", "title": "A video"}}


def test_retrieval_reports_completeness_as_state_not_prose():
    """Completeness is structured state; notes explain it but do not
    determine it."""

    port = FakeYouTubePort(comments=[{"comment_id": f"c{i}"} for i in range(10)])

    page = port.comment_threads("v", maximum=100)

    assert page.outcome.status is RetrievalStatus.COMPLETE
    assert page.outcome.is_complete is True
    assert page.outcome.retrieved == 10
    assert page.outcome.missing == 0


def test_a_truncated_scan_says_so_and_says_by_how_much():
    """"Truncated" without counts gives no way to judge what is missing."""

    port = FakeYouTubePort(comments=[{"comment_id": f"c{i}"} for i in range(50)])

    page = port.comment_threads("v", maximum=20)

    assert page.outcome.status is RetrievalStatus.TOP_LEVEL_TRUNCATED
    assert page.outcome.retrieved == 20
    assert page.outcome.reported_total == 50
    assert page.outcome.missing == 30
    assert page.outcome.notes


def test_only_a_complete_scan_may_conclude_a_reply_is_absent():
    """The rule that stops the scoreboard lying.

    A truncated scan that concludes absence turns "I could not see it" into
    "it is not there", which is this application's most consequential
    possible error.
    """

    port = FakeYouTubePort(comments=[{"comment_id": f"c{i}"} for i in range(50)])

    assert port.comment_threads("v", maximum=100).outcome.may_conclude_absence
    assert not port.comment_threads("v", maximum=20).outcome.may_conclude_absence

    for status in (RetrievalStatus.TOP_LEVEL_TRUNCATED,
                   RetrievalStatus.REPLY_THREAD_TRUNCATED,
                   RetrievalStatus.PAGE_TOKEN_LOOP,
                   RetrievalStatus.CANCELLED):
        assert status.may_conclude_absence is False


def test_a_truncated_reply_thread_has_its_own_status():
    """Distinct from a truncated top-level scan: they mean different things
    and the operator can act on one but not the other."""

    port = FakeYouTubePort(replies={"p1": [{"comment_id": f"r{i}"} for i in range(30)]})

    page = port.replies("p1", maximum=8)

    assert page.outcome.status is RetrievalStatus.REPLY_THREAD_TRUNCATED
    assert page.outcome.missing == 22


def test_the_ordering_is_recorded_on_every_comment():
    """Both orderings are fetched and merged, so each comment must remember
    which one found it."""

    port = FakeYouTubePort(comments=[{"comment_id": "c1"}])

    by_time = port.comment_threads("v", order="time")
    by_relevance = port.comment_threads("v", order="relevance")

    assert by_time.comments[0]["order_source"] == "time"
    assert by_relevance.comments[0]["order_source"] == "relevance"


def test_quota_spent_is_visible():
    """Quota is finite and does not refill until midnight Pacific."""

    port = FakeYouTubePort(videos=video_fixture())
    assert port.api_operations_used == 0

    port.video("gC-J7zwYMAM")
    port.comment_threads("gC-J7zwYMAM")

    assert port.api_operations_used == 2


def test_an_api_failure_arrives_as_a_domain_error():
    """No caller above this line sees an HTTP status code."""

    port = FakeYouTubePort(videos=video_fixture())
    port.raise_on_video = QuotaExceededError(
        "videos", 403, {"error": {"errors": [{"reason": "quotaExceeded"}]}}
    )

    with pytest.raises(QuotaExceededError) as caught:
        port.video("gC-J7zwYMAM")

    assert caught.value.exit_code == 2


def test_an_unknown_handle_refuses_rather_than_returning_nothing():
    """A run with no identity would treat every reply as somebody else's."""

    port = FakeYouTubePort(handles={"@someone": "UC" + "a" * 22})

    assert port.channel_id_for_handle("someone") == "UC" + "a" * 22
    assert port.channel_id_for_handle("@someone") == "UC" + "a" * 22

    with pytest.raises(ConfigurationError, match="No channel was found"):
        port.channel_id_for_handle("@nobody")


def test_the_port_hands_back_copies_not_its_own_state():
    """A caller that mutates a result must not corrupt the next call."""

    port = FakeYouTubePort(comments=[{"comment_id": "c1", "text": "original"}])

    page = port.comment_threads("v")
    page.comments[0]["text"] = "mutated"

    assert port.comment_threads("v").comments[0]["text"] == "original"
