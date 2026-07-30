"""Run one long job off the Tk thread, and report it back on the Tk thread.

The rebuilt window's rule was "the window does no network work", which kept it
free of exactly this machinery — and also meant the operator had to know which
command to type before he could open a window at all. Matching the old
application's logic means the window can start a build, so this exists.

Two rules, both of which a naive version gets wrong:

**Nothing touches a widget from the worker thread.** Tk is not thread-safe and
the failure is not an exception, it is a hang or a corrupted display an hour
later. The worker only ever puts events on a queue; the window drains that
queue from its own ``after`` loop.

**Cancelling sets a flag; it does not kill anything.** There is no safe way to
stop a thread from outside it. The flag is checked between units of work, so
Cancel means "stop at the next safe point" and the window says so rather than
implying the request was torn out of the air.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerEvent:
    """One thing that happened, on its way back to the window."""

    kind: str  # progress | confirmation | done | failed | cancelled
    message: str = ""
    value: Any = None
    fraction: float | None = None
    generation: int = 0


class Cancelled(Exception):
    """Raised inside the worker when the operator asked it to stop."""


@dataclass
class ConfirmationRequest:
    """A worker question that only the Tk thread may put on screen."""

    payload: Any
    accepted: bool = False
    answered: threading.Event = field(
        default_factory=threading.Event,
        repr=False,
    )

    def resolve(self, accepted: bool) -> None:
        self.accepted = bool(accepted)
        self.answered.set()


class BackgroundJob:
    """One cancellable job and the events it produced."""

    def __init__(self) -> None:
        self.events: "queue.Queue[WorkerEvent]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._generation = 0
        self._local = threading.local()

    # -- from the window -------------------------------------------------

    def start(self, work: Callable[["BackgroundJob"], Any]) -> bool:
        """Begin, unless something is already running.

        Returns whether it started. A window that silently ignored a second
        press would leave the operator pressing Build harder.
        """

        if self.running:
            return False
        self._cancel.clear()
        self._generation += 1
        generation = self._generation
        self._thread = threading.Thread(
            target=self._run, args=(work, generation), daemon=True,
            name="ytcomment-build",
        )
        self._thread.start()
        return True

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def generation(self) -> int:
        return self._generation

    def cancel(self) -> None:
        """Ask it to stop at the next safe point."""

        self._cancel.set()

    def drain(self, limit: int = 100) -> list[WorkerEvent]:
        """Every event waiting, for the window's ``after`` loop.

        Bounded: a job that emits faster than the loop drains would otherwise
        keep the loop inside this function and freeze the window it is trying
        to update.
        """

        drained: list[WorkerEvent] = []
        for _ in range(limit):
            try:
                drained.append(self.events.get_nowait())
            except queue.Empty:
                break
        return drained

    # -- from the worker thread -------------------------------------------

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check_cancelled(self) -> None:
        """Call between units of work. Raises so the job unwinds cleanly."""

        if self._cancel.is_set():
            raise Cancelled()

    def say(
        self,
        message: str,
        fraction: float | None = None,
        payload: Any = None,
    ) -> None:
        self.events.put(WorkerEvent(
            "progress",
            message,
            value=payload,
            fraction=fraction,
            generation=self._event_generation(),
        ))

    def confirm(self, payload: Any) -> bool:
        """Ask the Tk thread a question and wait without touching Tk here."""

        request = ConfirmationRequest(payload)
        self.events.put(WorkerEvent(
            "confirmation",
            value=request,
            generation=self._event_generation(),
        ))
        while not request.answered.wait(0.1):
            self.check_cancelled()
        self.check_cancelled()
        return request.accepted

    # -- internals ---------------------------------------------------------

    def _event_generation(self) -> int:
        return int(getattr(self._local, "generation", self._generation))

    def _run(
        self,
        work: Callable[["BackgroundJob"], Any],
        generation: int,
    ) -> None:
        self._local.generation = generation
        try:
            value = work(self)
        except Cancelled:
            self.events.put(WorkerEvent(
                "cancelled", "Stopped.", generation=generation
            ))
        except Exception as failure:        # noqa: BLE001 - reported, not raised
            # Reported rather than raised: an exception on this thread would
            # vanish into a dead thread and the window would wait for a
            # "done" that never came.
            LOGGER.exception("the background job failed")
            self.events.put(WorkerEvent(
                "failed", f"{type(failure).__name__}: {failure}",
                generation=generation,
            ))
        else:
            self.events.put(WorkerEvent(
                "done",
                "Finished.",
                value=value,
                generation=generation,
            ))
