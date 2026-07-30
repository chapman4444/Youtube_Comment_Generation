"""Running a build off the Tk thread, and reporting it back on it.

The rebuilt window's rule was "the window does no network work", which kept it
free of this machinery and also meant the operator had to know which command
to type before a window could exist. The window can start a build now, so this
has to be right.

No Tk here at all: the job is a thread and a queue, and both are testable
without a display.
"""

from __future__ import annotations

import threading
import time

import pytest

from llm_youtube_comment_generation.interfaces.gui.worker import (
    BackgroundJob,
    Cancelled,
    WorkerEvent,
)


def finished(job: BackgroundJob, timeout: float = 5.0) -> None:
    """Wait for the thread, so no test depends on scheduling luck."""

    deadline = time.time() + timeout
    while job.running and time.time() < deadline:
        time.sleep(0.01)
    assert not job.running, "the job never finished"


def kinds(job: BackgroundJob) -> list[str]:
    return [event.kind for event in job.drain()]


# -- the happy path --------------------------------------------------------


def test_a_result_comes_back_as_a_done_event():
    job = BackgroundJob()
    job.start(lambda _job: "the packet")
    finished(job)

    events = job.drain()

    assert [e.kind for e in events] == ["done"]
    assert events[0].value == "the packet"


def test_progress_arrives_in_order():
    def work(job):
        for index in range(3):
            job.say(f"step {index}", index / 3)
        return None

    job = BackgroundJob()
    job.start(work)
    finished(job)

    events = job.drain()

    assert [e.message for e in events[:3]] == ["step 0", "step 1", "step 2"]
    assert events[0].fraction == 0.0


# -- failures come back rather than vanishing ------------------------------


def test_a_failure_is_reported_not_raised_into_a_dead_thread():
    """An exception on the worker thread would disappear and the window would
    wait forever for a "done" that never came."""

    def work(_job):
        raise ValueError("the API said no")

    job = BackgroundJob()
    job.start(work)
    finished(job)

    events = job.drain()

    assert events[-1].kind == "failed"
    assert "ValueError" in events[-1].message
    assert "the API said no" in events[-1].message


def test_a_failure_still_ends_the_job():
    job = BackgroundJob()
    job.start(lambda _job: 1 / 0)
    finished(job)

    assert not job.running


# -- cancelling ------------------------------------------------------------


def test_cancelling_stops_at_the_next_safe_point():
    """There is no safe way to kill a thread from outside it, so Cancel sets
    a flag that work checks between units."""

    reached = []

    def work(job):
        for index in range(100):
            job.check_cancelled()
            reached.append(index)
            time.sleep(0.01)
        return "never"

    job = BackgroundJob()
    job.start(work)
    time.sleep(0.05)
    job.cancel()
    finished(job)

    assert kinds(job)[-1] == "cancelled"
    assert 0 < len(reached) < 100, "it neither stopped instantly nor ran on"


def test_a_job_that_never_checks_is_not_killed_behind_its_back():
    """Honest about what cancelling can do: work that does not check runs to
    completion, and the result is a done rather than a lie about stopping."""

    job = BackgroundJob()
    job.start(lambda _job: "finished anyway")
    job.cancel()
    finished(job)

    assert kinds(job) == ["done"]


def test_cancelled_is_visible_to_the_work_itself():
    """Work that wants to wind down gracefully can look, rather than being
    forced to let check_cancelled() raise through it."""

    saw_it = threading.Event()

    def work(job):
        while not job.cancelled:
            time.sleep(0.01)
        saw_it.set()
        return "wound down"

    job = BackgroundJob()
    job.start(work)
    time.sleep(0.03)
    job.cancel()
    finished(job)

    assert saw_it.is_set()
    # It returned rather than raising, so this is a completed job.
    assert kinds(job) == ["done"]


# -- worker-to-window questions -------------------------------------------


def test_a_confirmation_is_answered_by_the_event_consumer():
    job = BackgroundJob()
    job.start(lambda running: running.confirm("no captions"))

    deadline = time.time() + 2
    while job.events.empty() and time.time() < deadline:
        time.sleep(0.01)
    event = job.events.get_nowait()

    assert event.kind == "confirmation"
    assert event.value.payload == "no captions"
    event.value.resolve(True)
    finished(job)

    completed = job.drain()
    assert completed[-1].kind == "done"
    assert completed[-1].value is True


def test_cancelling_while_a_confirmation_waits_stops_the_job():
    job = BackgroundJob()
    job.start(lambda running: running.confirm("no captions"))

    deadline = time.time() + 2
    while job.events.empty() and time.time() < deadline:
        time.sleep(0.01)
    assert job.events.get_nowait().kind == "confirmation"

    job.cancel()
    finished(job)

    assert kinds(job)[-1] == "cancelled"


# -- one at a time ---------------------------------------------------------


def test_a_second_start_is_refused_rather_than_silently_ignored():
    """A window that ignored the second press would leave the operator
    pressing Build harder."""

    gate = threading.Event()
    job = BackgroundJob()

    assert job.start(lambda _job: gate.wait(2))
    assert not job.start(lambda _job: "second")

    gate.set()
    finished(job)


def test_a_finished_job_can_be_started_again():
    job = BackgroundJob()
    job.start(lambda _job: "first")
    finished(job)
    job.drain()

    assert job.start(lambda _job: "second")
    finished(job)
    assert job.drain()[-1].value == "second"


def test_cancelling_is_cleared_by_the_next_start():
    job = BackgroundJob()
    job.cancel()
    job.start(lambda _job: None)
    finished(job)
    job.drain()

    ran = []
    job.start(lambda j: ran.append(j.cancelled))
    finished(job)

    assert ran == [False]


# -- draining --------------------------------------------------------------


def test_draining_is_bounded_so_the_loop_can_return():
    """A job emitting faster than the loop drains would otherwise keep the
    loop inside drain() and freeze the window it is updating."""

    job = BackgroundJob()
    for index in range(500):
        job.events.put(WorkerEvent("progress", str(index)))

    assert len(job.drain(limit=10)) == 10


def test_draining_an_empty_queue_is_not_an_error():
    assert BackgroundJob().drain() == []
