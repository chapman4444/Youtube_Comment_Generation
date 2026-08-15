"""The reply path: which step you are on, and what to do about it.

The old window drew four numbered rows, two copy buttons, a status line, a
"what this person said" box, three more buttons and a manual-controls panel —
all on screen at once, all the time. It was taller than a 1080p screen and its
own comments say so. This is the same path with one step in front of you and
the rest visible as a rail beside it.

Pure. No tkinter, no clock, no clipboard — the window passes in what the
clipboard holds and this decides what that means. Which is the whole point:
what the clipboard is *offering* is the part worth being certain about, and
Tk interpreter creation is too flaky on this machine to make it a display
test.

**Nothing ever advances on its own.** The old window had a "steps 2 and 3
advance without me pressing anything" option; the operator does not use it and
asked for it gone. Watching the clipboard is still the best part of the
window, so it is kept and made louder — it *reports what it sees and offers*,
and the offer is something he presses. A step that moves under the cursor is a
step he did not choose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from ...domain.extraction import (
    extract_hardened_final,
    looks_like_batch_reply_sheet,
    looks_like_packet_text,
    parse_triage_selection,
)
from ...domain.ids import find_video_reference


class Step(Enum):
    """The four things that happen, in order."""

    BUILD = "build"
    TRIAGE = "triage"
    PEOPLE = "people"
    FINISH = "finish"


#: The rail's short labels, and the heading shown in the detail pane.
STEP_RAIL = {
    Step.BUILD: "Build",
    Step.TRIAGE: "Triage",
    Step.PEOPLE: "People",
    Step.FINISH: "Finish",
}

STEP_TITLE = {
    Step.BUILD: "Find who needs a reply",
    Step.TRIAGE: "Paste the triage answer",
    Step.PEOPLE: "Paste an answer for this person",
    Step.FINISH: "Open the finished replies",
}

STEP_DETAIL = {
    Step.BUILD: (
        "Scans this video for your own comments and the people who replied "
        "to them without hearing back. Spends YouTube API operations."
    ),
    Step.TRIAGE: (
        "The triage template is on your clipboard. Paste it into your model, "
        "ask which of these people are worth answering, then copy the answer "
        "back."
    ),
    Step.PEOPLE: (
        "This person's packet is on your clipboard. Paste it into your model, "
        "then copy its answer back. Accepted drafts are saved as you go."
    ),
    Step.FINISH: (
        "Every accepted draft is written to replies_to_review.md. Nothing has "
        "been posted."
    ),
}


class Holding(Enum):
    """What the clipboard appears to contain."""

    NOTHING = "nothing"
    VIDEO = "a video link"
    OUR_PACKET = "the packet this tool just copied"
    ANSWER = "an answer from your model"
    TRIAGE_ANSWER = "a list of people to answer"
    OTHER = "something else"


#: What the clipboard has to be holding for a step to have anything to offer.
#:
#: Triage and the per-person steps want different shapes, which is the whole
#: reason this table exists. A triage answer is a list of handles and has no
#: "### Hardened final" heading, so classifying every answer the same way left
#: the chip reporting a perfectly good triage answer as "something else".
WANTED = {
    Step.BUILD: Holding.VIDEO,
    Step.TRIAGE: Holding.TRIAGE_ANSWER,
    Step.PEOPLE: Holding.ANSWER,
    Step.FINISH: Holding.NOTHING,
}


@dataclass(frozen=True)
class ClipboardOffer:
    """What the clipboard holds, and whether this step can use it."""

    holding: Holding = Holding.NOTHING
    usable: bool = False
    label: str = ""
    #: What this module made of the clipboard: an extracted draft, or a video
    #: id. Enough to decide whether there is anything here worth offering, and
    #: to show how much of it there is.
    payload: str = ""
    #: The clipboard exactly as it was. This is what gets handed on.
    #:
    #: Extracting here and submitting the result meant the session extracted a
    #: second time, from text whose "### Hardened final" heading had already
    #: been consumed -- so every answer was refused as having no heading. The
    #: session owns that rule; this only decides whether to offer.
    raw: str = ""

    @property
    def offered(self) -> bool:
        return self.usable and bool(self.payload)


def read_clipboard(text: str, *, step: Step, packet: str = "") -> ClipboardOffer:
    """Classify what is on the clipboard for the step in front of you.

    Order matters and is the same order the guided session uses when it takes
    an answer. Packet detection runs before answer extraction, because a
    packet contains its own literal "### Hardened final" heading and would
    otherwise be offered back as though it were an answer to itself.
    """

    held = (text or "").strip()
    if not held:
        return ClipboardOffer(Holding.NOTHING, label="Clipboard: empty")

    if looks_like_packet_text(held, packet):
        return ClipboardOffer(
            Holding.OUR_PACKET,
            label="Clipboard: the packet this tool copied",
        )

    # Before the triage branch: a reply sheet is unambiguous (its Post
    # beneath lines appear in nothing else), and a sheet naming handles in
    # its own headings must not read as a triage list. Shape only — the
    # session validates the sheet against the packet's target ids when it
    # is submitted; deciding that here would mean two places owning one
    # rule.
    if looks_like_batch_reply_sheet(held):
        usable = WANTED.get(step) is Holding.ANSWER
        return ClipboardOffer(
            Holding.ANSWER,
            usable=usable,
            label=("Clipboard: a reply sheet from your model"
                   if usable else
                   "Clipboard: a reply sheet, but this step is not waiting "
                   "for one"),
            payload=held,
            raw=held,
        )

    # Only where it is wanted: a triage answer is prose with handles in it,
    # and prose is exactly what would otherwise fall through to "something
    # else".
    if WANTED.get(step) is Holding.TRIAGE_ANSWER:
        chosen = parse_triage_selection(held)
        if chosen:
            return ClipboardOffer(
                Holding.TRIAGE_ANSWER,
                usable=True,
                label=(f"Clipboard: {len(chosen)} "
                       f"{'person' if len(chosen) == 1 else 'people'} chosen"),
                payload=", ".join(chosen),
                raw=held,
            )

    # A comment answer is not a reply sheet: it carries a Hardened final,
    # not Post-beneath lines. Dropping this branch with the batch change
    # left the chip calling a perfectly good comment answer "something
    # else" (harsh-critic review, finding 10).
    if extract_hardened_final(held):
        usable = WANTED.get(step) is Holding.ANSWER
        return ClipboardOffer(
            Holding.ANSWER,
            usable=usable,
            label=("Clipboard: an answer from your model"
                   if usable else
                   "Clipboard: an answer, but this step is not waiting for "
                   "one"),
            payload=held,
            raw=held,
        )

    video = find_video_reference(held)
    if video:
        usable = WANTED.get(step) is Holding.VIDEO
        return ClipboardOffer(
            Holding.VIDEO,
            usable=usable,
            label=f"Clipboard: a video link ({video})",
            payload=video,
            raw=held,
        )

    return ClipboardOffer(
        Holding.OTHER,
        label="Clipboard: no supported YouTube video or model answer detected",
    )


@dataclass
class RailEntry:
    """One row of the step rail."""

    step: Step
    label: str
    done: bool = False
    current: bool = False

    @property
    def marker(self) -> str:
        """Tick, pointer or nothing. ASCII: this is read in a Tk label on a
        Windows box where a missing glyph draws as a hollow box."""

        if self.done:
            return "+"
        return ">" if self.current else " "


@dataclass
class SequenceView:
    """Everything the right pane draws, decided here."""

    step: Step = Step.BUILD
    rail: tuple[RailEntry, ...] = ()
    title: str = ""
    detail: str = ""
    primary_label: str = ""
    primary_enabled: bool = True
    copy_label: str = ""
    copy_enabled: bool = False
    offer: ClipboardOffer = field(default_factory=ClipboardOffer)
    person: str = ""
    person_said: str = ""
    progress: str = ""
    can_go_back: bool = False
    can_skip: bool = False


@dataclass
class ReplySequence:
    """The path, and what it looks like from wherever you are on it.

    Holds no session and does no work: the window owns the session and calls
    these to decide what to draw. That keeps every rule about which control is
    live testable without a display, the same split `view_models` uses for the
    comment flow.
    """

    step: Step = Step.BUILD
    people: tuple[str, ...] = ()
    index: int = 0
    accepted: int = 0
    triage_done: bool = False

    def advance_to(self, step: Step) -> None:
        """Move deliberately. Nothing in this module moves on its own."""

        self.step = step

    def next_person(self) -> None:
        if self.index + 1 < len(self.people):
            self.index += 1
        else:
            self.step = Step.FINISH

    def view(
        self,
        clipboard: str = "",
        *,
        packet: str = "",
        said: str = "",
        building: bool = False,
    ) -> SequenceView:
        order = list(Step)
        reached = order.index(self.step)

        rail = tuple(
            RailEntry(
                step=entry,
                label=STEP_RAIL[entry],
                done=order.index(entry) < reached,
                current=entry is self.step,
            )
            for entry in order
        )

        person = self.people[self.index] if self.index < len(self.people) else ""
        offer = read_clipboard(clipboard, step=self.step, packet=packet)

        view = SequenceView(
            step=self.step,
            rail=rail,
            title=STEP_TITLE[self.step],
            detail=STEP_DETAIL[self.step],
            offer=offer,
            person=person,
            person_said=said,
            # Going back re-copies a template; it never un-saves a draft, so
            # it is safe from every step except the first.
            can_go_back=self.step is not Step.BUILD,
            # Triage is skippable too: "work through everyone" is a perfectly
            # good answer to "which of these are worth answering", and the
            # operator should not have to run a model to say it.
            can_skip=(self.step in (Step.TRIAGE, Step.PEOPLE)
                      and bool(self.people)),
        )

        if self.step is Step.BUILD:
            view.primary_label = "Find who needs a reply"
            view.primary_enabled = not building
            view.detail = (
                "Scanning..." if building else STEP_DETAIL[Step.BUILD]
            )
        elif self.step is Step.TRIAGE:
            view.primary_label = "Use the answer on the clipboard"
            view.primary_enabled = offer.offered
            view.copy_label = "Copy triage template"
            view.copy_enabled = True
            view.progress = f"{len(self.people)} people found"
        elif self.step is Step.PEOPLE:
            view.primary_label = "Use the answer on the clipboard"
            view.primary_enabled = offer.offered
            view.copy_label = "Copy this person's packet"
            view.copy_enabled = bool(person)
            view.progress = (
                f"{self.index + 1} of {len(self.people)}, "
                f"{self.accepted} saved"
            ) if self.people else "nobody is waiting"
        else:
            view.primary_label = "Open the replies"
            view.copy_enabled = False
            view.progress = f"{self.accepted} saved"

        return view
