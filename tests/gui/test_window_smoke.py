"""The window itself, against real Tk.

Deliberately few. Every rule that can be checked without a display is checked
without one, in the other two files. What is left is what genuinely needs
widgets: that they get created, that enablement reaches them, and that the
log pane survives the layout.

One Tk interpreter for the whole directory, from `conftest.py`. Interpreter
creation is the flaky part on this machine — a spurious TclError roughly once
per suite run — so each test takes a Toplevel from a single shared root
instead of building its own.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from fakes import FakeArtifactStore, FakeClipboard, FakeEventSink
from llm_youtube_comment_generation.application.guided_session import (
    GuidedSession,
)
from llm_youtube_comment_generation.domain.candidates import (
    build_reply_candidates,
)
from llm_youtube_comment_generation.domain.threads import OwnerThread
from llm_youtube_comment_generation.domain.workflow import (
    Intent,
    Phase,
    WorkerLifecycle,
)
from llm_youtube_comment_generation.infrastructure import prompt_resources
from llm_youtube_comment_generation.interfaces.gui.controllers import (
    GuidedController,
)
from llm_youtube_comment_generation.interfaces.gui.main_window import (
    LOG_MINIMUM_HEIGHT,
    WINDOW_MINIMUM_WIDTH,
    MainWindow,
)

OWNER = "UC" + "o" * 22


def message(cid, author, text, when, *, channel=None, likes=0):
    return {
        "comment_id": cid, "author": author,
        "author_channel_id": channel or ("UC" + author.lstrip("@").ljust(22, "z"))[:24],
        "text": text, "like_count": likes,
        "published_at": when, "updated_at": when,
    }


@pytest.fixture
def window(tk_root):
    replies = [
        message("r1", "@alice", "actually you are wrong", "2026-07-02T00:00:00Z",
                likes=9),
    ]
    thread = OwnerThread(
        comment=message("mine", "@owner", "my comment", "2026-07-01T00:00:00Z",
                        channel=OWNER),
        replies=replies,
    )
    session = GuidedSession(
        targets=build_reply_candidates(OWNER, "@owner", replies, "mine"),
        threads={"mine": thread},
        owner_channel_id=OWNER,
        video={"video_id": "gC-J7zwYMAM", "title": "A video"},
        templates={
            "reply_workflow.md": prompt_resources.load("reply_workflow.md").text,
            "reply_final_check.md":
                prompt_resources.load("reply_final_check.md").text,
        },
        artifacts=FakeArtifactStore(),
        clipboard=FakeClipboard(),
        events=FakeEventSink(),
    )
    top = tk.Toplevel(tk_root)
    top.withdraw()
    # notify is injected as a recorder. The default is a modal dialog, and a
    # test cannot click one: the first version of this fixture hung the whole
    # suite until the process was killed.
    notices: list[tuple[str, str]] = []
    built = MainWindow(
        GuidedController(session=session), root=top,
        notify=lambda title, message: notices.append((title, message)),
    )
    built.notices = notices
    yield built
    top.destroy()


def test_the_window_builds_and_shows_the_first_step(window):
    assert window.explanation.cget("text")
    assert window._buttons


def test_enablement_reaches_the_real_buttons(window):
    """The view decides; the window only renders. This checks it renders."""

    start = window._buttons[Intent.START]
    skip = window._buttons[Intent.SKIP_PERSON]

    assert str(start.cget("state")) == "normal"
    assert str(skip.cget("state")) == "disabled"

    window.on_intent(Intent.START)
    window.on_intent(Intent.NEXT_PERSON)

    assert str(window._buttons[Intent.SKIP_PERSON].cget("state")) == "normal"
    assert str(window._buttons[Intent.START].cget("state")) == "disabled"


def test_a_whole_guided_run_works_through_the_window(window):
    window.on_intent(Intent.START)
    window.on_intent(Intent.NEXT_PERSON)
    window.on_intent(Intent.COPY_CURRENT_PACKET)

    window.controller.session.clipboard.write(
        "### Hardened final\nthe reply I am sending\n"
    )
    window.on_intent(Intent.SUBMIT_PERSON_ANSWER)
    view = window.on_intent(Intent.SAVE)

    assert view.phase is Phase.COMPLETE
    assert len(window.controller.session.accepted) == 1


def test_the_one_next_step_is_the_one_that_stands_out(window):
    """view_models decides exactly one primary action per phase. The window
    dropped it and drew eleven identical buttons, which is the thing the
    single-primary rule exists to stop."""

    start = window._buttons[Intent.START]
    skip = window._buttons[Intent.SKIP_PERSON]

    assert str(start.cget("style")) == "Primary.TButton"
    assert str(skip.cget("style")) != "Primary.TButton"

    window.on_intent(Intent.START)
    window.on_intent(Intent.NEXT_PERSON)

    assert str(window._buttons[Intent.START].cget("style")) != "Primary.TButton"
    assert str(
        window._buttons[Intent.COPY_CURRENT_PACKET].cget("style")
    ) == "Primary.TButton"


def test_the_window_names_the_button_to_press(window):
    """Saying what is happening never said which of eleven controls advances
    it."""

    assert "Next:  Start" in window.explanation.cget("text")


def test_the_progress_log_cannot_be_typed_into(window):
    window.say("something happened")

    assert str(window.log.cget("state")) == "disabled"
    assert "something happened" in window.log.get("1.0", "end")


def finish_a_run(window):
    """Drive the window to COMPLETE, which is where Open replies lives.

    It is the primary action in every phase a run can end in, so this is the
    state the operator is actually in when he presses it.
    """

    window.on_intent(Intent.START)
    window.on_intent(Intent.NEXT_PERSON)
    window.on_intent(Intent.COPY_CURRENT_PACKET)
    window.controller.session.clipboard.write(
        "### Hardened final\nthe reply I am sending\n"
    )
    window.on_intent(Intent.SUBMIT_PERSON_ANSWER)
    view = window.on_intent(Intent.SAVE)
    assert view.phase is Phase.COMPLETE
    return view


def test_opening_the_replies_reports_what_happened(window):
    """It was wired to a callable that did nothing and returned nothing, so
    pressing it produced no window, no error and no log line."""

    finish_a_run(window)
    window._open_review = lambda: "Could not open it. It is written and safe."
    window.on_intent(Intent.OPEN_REVIEW)

    assert "written and safe" in window.log.get("1.0", "end")


def test_a_silent_open_says_nothing(window):
    """Success is silent: the file was handed to the desktop, which is not the
    same as promising a window appeared."""

    def written():
        return [line for line
                in window.log.get("1.0", "end").splitlines() if line.strip()]

    finish_a_run(window)
    window._open_review = lambda: ""
    before = written()
    view = window.on_intent(Intent.OPEN_REVIEW)

    # Every intent logs the progress line. Nothing else may appear: the open
    # itself is what must be silent.
    assert written()[len(before):] == [view.progress]


def test_a_caller_that_returns_nothing_still_works(window):
    """The existing fakes return None. Changing the contract must not break
    a caller that never opted into it."""

    finish_a_run(window)
    called = []
    window._open_review = lambda: called.append(1)
    window.on_intent(Intent.OPEN_REVIEW)

    assert called == [1]


def test_the_buttons_do_not_run_off_the_edge_of_the_screen(window):
    """Eleven buttons in one row asked for more width than a laptop has, and
    the two that end a run -- Save and Open replies -- were the ones that went
    over the edge."""

    window.root.update_idletasks()
    rows = {window._buttons[intent].grid_info()["row"]
            for intent in window._buttons}

    assert len(window._buttons) == 11
    assert len(rows) > 1, "still a single row"
    assert window.root.winfo_reqwidth() <= WINDOW_MINIMUM_WIDTH


def test_the_log_pane_keeps_its_floor(window):
    """minsize is load-bearing, not decoration.

    Adding controls above this pane once made the window ask for more height
    than the screen had, and the grid manager took the entire shortfall out
    of the one row that could give: the log vanished while everything above
    it stayed put.
    """

    window.root.update_idletasks()

    for height in (900, 700, 520, 420):
        window.root.geometry(f"700x{height}")
        window.root.update_idletasks()
        # grid_bbox, not winfo_height: a withdrawn window's widgets are
        # unmapped and report 1 pixel regardless of the real layout.
        assert window.root.grid_bbox(0, 3)[3] >= LOG_MINIMUM_HEIGHT, height


def test_the_window_refuses_to_close_while_saving(window):
    """Losing the process here loses accepted work."""

    window.controller.session.state.worker = WorkerLifecycle.COMMITTING

    assert window.on_close() is False
    assert window.root.winfo_exists()
    assert window.notices == [
        ("Still saving",
         "This run is saving accepted replies. Closing now would lose them.")
    ]


def test_the_window_does_close_when_nothing_is_being_written(window):
    """The refusal has to be conditional, or the window never closes."""

    assert window.on_close() is True
    assert window.notices == []


def test_a_refused_intent_is_written_to_the_log(window):
    window.on_intent(Intent.SKIP_PERSON)

    assert "not available" in window.log.get("1.0", "end")
