"""What the window's Build button does, without a window or a network.

This is the piece that turns the options into a packet, and it runs on the
worker thread — so the two things worth being certain about are that it never
touches a widget and that a cancel actually stops it.

The live path is verified by hand and reported in the CHANGELOG: a real build
from the window produced 74,399 characters. What is tested here is everything
that does not need YouTube.
"""

from __future__ import annotations

import pytest

from llm_youtube_comment_generation.domain.errors import OperationCancelled
from llm_youtube_comment_generation.interfaces.gui.builder import (
    JobEvents,
    build_comment,
)
from llm_youtube_comment_generation.interfaces.gui.options import (
    PacketOptionsModel,
)
from llm_youtube_comment_generation.interfaces.gui.worker import (
    BackgroundJob,
    Cancelled,
)
from llm_youtube_comment_generation.ports.events import EventKind, ProgressEvent
from llm_youtube_comment_generation.domain.statuses import OperationResult


class FakeStore:
    root = "output/fake"

    def __init__(self):
        self.staged = {}

    def stage(self, name, content):
        self.staged[name] = content

    def commit(self):
        return tuple(sorted(self.staged))

    def rollback(self):
        self.staged.clear()

    def read(self, name):
        return self.staged[name]

    def committed_names(self):
        return tuple(sorted(self.staged))


def options(**kwargs) -> PacketOptionsModel:
    return PacketOptionsModel(video="gC-J7zwYMAM", **kwargs)


# -- the event sink --------------------------------------------------------


def test_progress_reaches_the_window_rather_than_the_console():
    """Without this the operator watches a bar that never moves while a
    console he cannot see fills up."""

    job = BackgroundJob()
    sink = JobEvents(job)

    sink.emit(ProgressEvent(EventKind.STEP, step="comments",
                            message="Fetching comments"))

    event = job.drain()[0]
    assert event.message == "Fetching comments"
    assert event.fraction == JobEvents.FRACTIONS["comments"]


def test_an_unknown_step_still_reports_without_inventing_a_fraction():
    job = BackgroundJob()

    JobEvents(job).emit(ProgressEvent(EventKind.STEP, step="mystery",
                                      message="something"))

    assert job.drain()[0].fraction is None


def test_numbered_work_is_named_in_the_activity_log():
    job = BackgroundJob()

    JobEvents(job).emit(ProgressEvent(
        EventKind.PROGRESS,
        step="replies",
        current=3,
        total=8,
    ))

    assert job.drain()[0].message == "Reply threads: 3 of 8"


def test_a_cancel_is_honoured_between_reported_units_of_work():
    """The application is between two units whenever it reports one, which is
    exactly where stopping is safe."""

    job = BackgroundJob()
    sink = JobEvents(job)
    job.cancel()

    with pytest.raises(Cancelled):
        sink.emit(ProgressEvent(EventKind.STEP, step="comments", message="x"))


def test_the_last_event_of_a_run_is_never_cancelled_out_from_under_it():
    """A cancel arriving as the build finishes must not turn a finished
    packet into a cancelled run."""

    job = BackgroundJob()
    job.cancel()

    JobEvents(job).emit(ProgressEvent(EventKind.FINISHED, step="packet",
                                      message="done"))

    assert job.drain()[0].message == "done"


# -- what the options become -----------------------------------------------


def test_the_chosen_registers_and_dials_reach_the_command():
    seen = {}

    def handle(command, **kwargs):
        seen["command"] = command
        raise Cancelled()

    job = BackgroundJob()
    with pytest.raises(Cancelled):
        _run(job, options(comment_variations=("short_hook",),
                          comment_approach_mode="custom",
                          dials={"grounding": "summary"}), handle)

    assert seen["command"].variations == ("short_hook",)
    assert seen["command"].dials["grounding"] == "summary"


def test_no_register_chosen_still_sends_the_defaults():
    from llm_youtube_comment_generation.domain.writing_options import (
        DEFAULT_VARIATIONS,
    )

    seen = {}

    def handle(command, **kwargs):
        seen["command"] = command
        raise Cancelled()

    with pytest.raises(Cancelled):
        _run(BackgroundJob(), options(), handle)

    assert seen["command"].variations == tuple(DEFAULT_VARIATIONS)


def test_infrastructure_cancellation_becomes_a_cancelled_worker_run():
    def handle(command, **kwargs):
        raise OperationCancelled("Stopped during local transcription.")

    with pytest.raises(Cancelled):
        _run(BackgroundJob(), options(), handle)


def test_a_typed_word_count_reaches_the_command_as_a_range():
    seen = {}

    def handle(command, **kwargs):
        seen["command"] = command
        raise Cancelled()

    with pytest.raises(Cancelled):
        _run(BackgroundJob(), options(length="exact", custom_length="120"),
             handle)

    assert seen["command"].explicit_length == (96, 150)


def test_the_named_length_is_resolved_by_the_domain_not_the_window():
    seen = {}

    def handle(command, **kwargs):
        seen["command"] = command
        raise Cancelled()

    with pytest.raises(Cancelled):
        _run(BackgroundJob(), options(length="auto"), handle)

    assert seen["command"].explicit_length is None


@pytest.mark.parametrize(
    "video",
    ("gC-J7zwYMAM", "https://www.youtube.com/watch?v=gC-J7zwYMAM"),
)
def test_comment_build_returns_the_original_canonical_run_context(video):
    stores = []

    def artifacts_for(video_id, directory):
        store = FakeStore()
        stores.append((video_id, store))
        return store

    def handle(command, **kwargs):
        class Packet:
            text = "packet"
            variations = ("short_hook",)

            def __len__(self):
                return len(self.text)

        packet = Packet()
        return OperationResult(
            value={
                "packet": packet,
                "run": {
                    "video_id": command.video_id,
                    "video_title": "Canonical title",
                    "prompt_version": "abc123",
                },
            },
            artifacts=["packet.md", "run.json"],
        )

    import llm_youtube_comment_generation.interfaces.gui.builder as module

    original = module.build_comment_packet.handle
    module.build_comment_packet.handle = handle
    try:
        result = build_comment(
            PacketOptionsModel(video=video),
            BackgroundJob(),
            ports_factory=lambda events: {
                "youtube": None, "transcripts": None
            },
            templates={
                "comment_workflow.md": "x",
                "comment_final_check.md": "y",
            },
            artifacts_for=artifacts_for,
        )
    finally:
        module.build_comment_packet.handle = original

    assert len(stores) == 1
    assert stores[0][0] == "gC-J7zwYMAM"
    assert result.video == {
        "video_id": "gC-J7zwYMAM",
        "title": "Canonical title",
    }
    assert result.artifacts is stores[0][1]
    assert result.packet_path.endswith("packet.md")


def test_the_window_never_names_a_template_or_a_run_directory():
    """Filenames are the artifact store's business. A window that knew one
    would be a second place the output layout is defined, and
    test_gui_boundaries caught this module getting it wrong once already."""

    from llm_youtube_comment_generation.interfaces.gui import builder

    source = (builder.__file__)
    with open(source, encoding="utf-8") as handle:
        text = handle.read()

    for forbidden in (".md\"", ".md'", ".json\"", "output/"):
        assert forbidden not in text


# -- helper ----------------------------------------------------------------


def _run(job, model, handle):
    """Call build_comment with the application layer replaced."""

    import llm_youtube_comment_generation.interfaces.gui.builder as module

    original = module.build_comment_packet.handle
    module.build_comment_packet.handle = handle
    try:
        return build_comment(
            model, job,
            ports_factory=lambda events: {"youtube": None, "transcripts": None},
            templates={"comment_workflow.md": "x", "comment_final_check.md": "y"},
            artifacts_for=lambda video_id, directory: FakeStore(),
        )
    finally:
        module.build_comment_packet.handle = original
