"""The Tkinter window.

Deliberately thin. It creates widgets, renders a ``WorkflowView``, and hands
intents to the controller. It decides nothing: which buttons are enabled,
what they say, and whether the window may close are all read off the view.

Layout note that is not decoration: the log pane's row carries the only
stretch weight and a minimum size. Without the floor, adding controls above
it made the window ask for more height than the screen had, and the grid
manager took the entire shortfall out of the one row that could give — the
log disappeared while everything above it stayed put.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from ...domain.workflow import Intent
from .controllers import GuidedController
from .view_models import WorkflowView

LOG_MINIMUM_HEIGHT = 150
WINDOW_MINIMUM_WIDTH = 780
WINDOW_MINIMUM_HEIGHT = 520
BUTTONS_PER_ROW = 6


class MainWindow:
    """The operator's window over an existing guided session."""

    def __init__(
        self,
        controller: GuidedController,
        root: tk.Misc | None = None,
        *,
        open_review: Callable[[], Any] | None = None,
        notify: Callable[[str, str], None] | None = None,
        title: str = "YouTube reply packets",
    ) -> None:
        self.controller = controller
        self.root = root if root is not None else tk.Tk()
        self._open_review = open_review or (lambda: None)
        # Injected because the default is a modal dialog, and a modal dialog
        # in the close path blocks the event loop until somebody clicks it.
        # That is untestable and, worse, it hangs any automated run.
        self._notify = notify or self._default_notify
        self._buttons: dict[Intent, ttk.Button] = {}

        self.root.title(title)
        self.root.columnconfigure(0, weight=1)
        # Eleven buttons in one row make a window wider than it is tall, and
        # the grid will happily shrink it to something with no log at all.
        try:
            self.root.minsize(WINDOW_MINIMUM_WIDTH, WINDOW_MINIMUM_HEIGHT)
            ttk.Style(self.root).configure(
                "Primary.TButton", font=("TkDefaultFont", 9, "bold")
            )
        except tk.TclError:     # pragma: no cover - a themeless Tk build
            pass
        self._build()
        self.refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # -- construction ----------------------------------------------------

    def _build(self) -> None:
        self.explanation = ttk.Label(self.root, text="", anchor="w")
        self.explanation.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 2))

        self.person = ttk.Label(self.root, text="", anchor="w", justify="left")
        self.person.grid(row=1, column=0, sticky="ew", padx=8)

        actions = ttk.Frame(self.root)
        actions.grid(row=2, column=0, sticky="ew", padx=8, pady=6)
        # Wrapped rather than one row. There are eleven of these and labels
        # like "Paste triage answer" are not short, so a single row asked for
        # more width than a laptop screen has and the last buttons -- Save and
        # Open replies, the two that end a run -- went off the edge.
        for position, intent in enumerate(self._intents()):
            button = ttk.Button(
                actions, text="",
                command=lambda i=intent: self.on_intent(i),
            )
            button.grid(row=position // BUTTONS_PER_ROW,
                        column=position % BUTTONS_PER_ROW,
                        padx=2, pady=2, sticky="ew")
            self._buttons[intent] = button

        pane = ttk.LabelFrame(self.root, text="Progress")
        pane.grid(row=3, column=0, sticky="nsew", padx=8, pady=4)
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(0, weight=1)
        # Read-only, and scrollable. A tk.Text is editable by default, so the
        # progress log accepted typing — and a log with no scrollbar loses
        # everything above the fold, which is where the refusal that explains
        # the current state usually is.
        self.log = tk.Text(pane, height=8, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(pane, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

        self.command = ttk.Label(self.root, text="", anchor="w",
                                 foreground="#555")
        self.command.grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 8))

        # Load-bearing. See the module docstring.
        self.root.rowconfigure(3, weight=1, minsize=LOG_MINIMUM_HEIGHT)

    def _intents(self) -> list[Intent]:
        return [action.intent for action in self.controller.view().actions]

    # -- rendering -------------------------------------------------------

    def refresh(self) -> WorkflowView:
        view = self.controller.view()

        # The phase, and then the button to press. The explanation alone said
        # what was happening but never which of eleven controls advanced it.
        primary = next((a for a in view.actions if a.primary), None)
        self.explanation.configure(
            text=(f"{view.explanation}\nNext:  {primary.label}"
                  if primary else view.explanation)
        )
        self.person.configure(
            text=(f"{view.person}  [{view.person_status}]\n{view.person_said}"
                  if view.person else "")
        )
        self.command.configure(
            text=(f"Same thing from a terminal:  {view.equivalent_command}"
                  if view.equivalent_command else "")
        )

        for action in view.actions:
            button = self._buttons.get(action.intent)
            if button is None:
                continue
            button.configure(
                text=action.label,
                state=("normal" if action.enabled else "disabled"),
                # view_models decides exactly one next step per phase and the
                # window used to drop it, drawing eleven identical buttons and
                # leaving the operator to work out which one it wanted --
                # which is the thing the single-primary rule exists to stop.
                style=("Primary.TButton" if action.primary else "TButton"),
            )

        if self.controller.last_refusal:
            self.say(self.controller.last_refusal)
        return view

    def say(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # -- events ----------------------------------------------------------

    def on_intent(self, intent: Intent) -> WorkflowView:
        if intent is Intent.OPEN_REVIEW:
            # Whatever it returns is shown. In production this was wired to a
            # callable that did nothing and returned nothing, so the primary
            # action of four separate phases was a button with no effect and
            # no explanation. A caller that returns None still says nothing,
            # which keeps the existing fakes working.
            message = self._open_review()
            if message:
                self.say(str(message))
        self.controller.submit(intent)
        view = self.refresh()
        if view.progress:
            self.say(view.progress)
        return view

    def on_close(self) -> bool:
        """Refuse to close while accepted work is being written.

        Returns whether the window actually closed, so a test can assert the
        refusal without a real window manager.
        """

        view = self.controller.view()
        if not view.may_close:
            self.say(view.close_refusal)
            self._notify("Still saving", view.close_refusal)
            return False
        self.root.destroy()
        return True

    def _default_notify(self, title: str, message: str) -> None:   # pragma: no cover
        """The real dialog. Replaced in tests, which cannot click it."""

        messagebox.showwarning(title, message)


def launch(controller: GuidedController, **kwargs) -> MainWindow:   # pragma: no cover
    window = MainWindow(controller, **kwargs)
    window.root.deiconify()
    window.root.lift()
    window.root.mainloop()
    return window
