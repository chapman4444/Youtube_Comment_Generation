"""The packet window: options on the left, the work on the right.

The old application's window stacked everything vertically and put the modes
in a `ttk.Notebook`, which takes the height of its tallest tab whichever one is
showing. Its own comments admit the result was taller than a 1080p screen.

Four changes buy the height back, and none of them drops an option:

**Horizontal.** Screens are wide and short. Options left, the work right.

**Mode is a radio pair, not a notebook.** No tallest-tab tax, and the comment
mode stops being padded out to the reply mode's height.

**Advanced is a dialog.** The API key, output folder, editor, proxy, languages
and the four count spinboxes are set once and then never touched. Ten rows.

**Progress collapses.** The status line is always there; the log is a
disclosure the operator opens when he wants it.

Two rules this window is built around, both of them the operator's:

**It opens without a video.** The old one, and the first rebuilt one, resolved
a video before a window existed — so a window could not be opened to look at,
and "nothing is on the clipboard" was a reason to refuse rather than a state to
show. The read-only selection starts empty, the clipboard is inspected on open
and focus, and a valid video can arrive whenever.

**Watching the clipboard never advances the workflow.** It may fill an empty
video slot, but it never replaces a selected video or consumes a model answer
without an explicit action.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from ...domain.writing_options import DIALS, dial_choice_label
from ...domain.errors import ConfigurationError
from ...domain.ids import extract_video_id
from ...domain.video import watch_url
from .options import (
    LENGTH_CHOICES,
    LENGTH_HINTS,
    LENGTH_SUMMARIES,
    PacketOptionsModel,
    approach_choices,
    dial_help,
    resolved_approaches,
)
from .sequence import ReplySequence, Step, read_clipboard
from .worker import BackgroundJob

PADDING = 8
LEFT_WIDTH = 440
WINDOW_WIDTH = 1024
WINDOW_HEIGHT = 700

#: How often the clipboard chip refreshes. Slow enough to cost nothing, fast
#: enough that copying an answer and looking up feels immediate.
CLIPBOARD_POLL_MS = 700


class Tooltip:
    """Small delayed help popup using the same text as persistent help."""

    def __init__(self, widget: tk.Misc, text: Callable[[], str]) -> None:
        self.widget = widget
        self.text = text
        self.after_id: str | None = None
        self.tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<FocusIn>", self.schedule, add="+")
        widget.bind("<FocusOut>", self.hide, add="+")

    def schedule(self, _event=None) -> None:
        self.hide()
        self.after_id = self.widget.after(550, self.show)

    def show(self) -> None:
        text = self.text().strip()
        if not text:
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        x = min(
            self.widget.winfo_rootx() + 12,
            self.widget.winfo_screenwidth() - 390,
        )
        y = min(
            self.widget.winfo_rooty() + self.widget.winfo_height() + 4,
            self.widget.winfo_screenheight() - 180,
        )
        self.tip.wm_geometry(f"+{max(0, x)}+{max(0, y)}")
        ttk.Label(
            self.tip, text=text, justify="left", wraplength=360,
            relief="solid", borderwidth=1, padding=6,
        ).pack()

    def hide(self, _event=None) -> None:
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None
        if self.tip is not None:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None

    def destroy(self) -> None:
        """Cancel delayed work before the associated widget is destroyed."""

        self.hide()


class PacketWindow:
    """Everything on screen. Decides nothing it can ask another module."""

    def __init__(
        self,
        root: tk.Misc | None = None,
        *,
        options: PacketOptionsModel | None = None,
        clipboard: Any = None,
        build: Callable[[PacketOptionsModel, str, BackgroundJob], Any] | None = None,
        open_path: Callable[[str], str] | None = None,
        comment_session_factory: Callable[[Any], Any] | None = None,
        notify: Callable[[str, str], None] | None = None,
        poll: bool = True,
        mode: str = "comment",
    ) -> None:
        self.root = root if root is not None else tk.Tk()
        self.options = options or PacketOptionsModel()
        initial_video = (self.options.video or "").strip()
        initial_video_error = ""
        if initial_video:
            try:
                initial_video = extract_video_id(initial_video)
                self.options.video = initial_video
            except ConfigurationError as failure:
                # Keep the original text so the validation message can explain
                # it. Construction must remain available for correction.
                initial_video_error = str(failure)
        self.clipboard = clipboard
        self._build_packet = build
        self._open_path = open_path or (lambda path: "")
        self._comment_session_factory = comment_session_factory
        self.comment_session: Any = None
        # Injected: the default is a modal dialog, and a modal dialog blocks
        # the event loop until somebody clicks it. That is untestable and it
        # hangs an automated run.
        self._notify = notify or self._default_notify
        self.job = BackgroundJob()
        self.sequence = ReplySequence()
        self.last_packet = ""
        self.result: Any = None
        #: The last thing said, which outranks the state description in the
        #: status line until something else is said.
        self._message = ""

        self.mode = tk.StringVar(
            value=mode if mode in ("comment", "reply") else "comment")
        # Canonical value used by the controller; only its normalized URL is
        # shown, so the raw ID is no longer duplicated on screen.
        self.video = tk.StringVar(value=initial_video)
        self.video_url = tk.StringVar(
            value=watch_url(initial_video) if not initial_video_error else ""
        )
        self.status = tk.StringVar(value=initial_video_error or "Ready.")
        self.clip_label = tk.StringVar(value="Clipboard: not read yet")
        self.length = tk.StringVar(value=self.options.length)
        self.custom_length = tk.StringVar(value=self.options.custom_length)
        self.length_hint = tk.StringVar(value=self.options.length_hint())
        self.length_error = tk.StringVar(value="")
        self.approach_summary = tk.StringVar(value="")
        # Retained as model compatibility only. There are no mode radio
        # buttons: checkbox count is the visible and authoritative mode.
        self.approach_mode = tk.StringVar(value="default")
        self.resolution_summary = tk.StringVar(value="")
        self.help_text = tk.StringVar(value="")
        self.progress_value = tk.DoubleVar(value=0.0)
        self.log_open = tk.BooleanVar(value=False)
        self._tooltips: list[Tooltip] = []
        self._approach_tooltips: list[Tooltip] = []
        self._display_mode = self.mode.get()
        self._suppressed_clipboard_video = ""
        self._discard_job_result = False
        self._message = initial_video_error

        self.root.title("YouTube packet builder")
        self.root.minsize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        self._compose()
        self.refresh()
        self.root.bind("<FocusIn>", self._window_focused, add="+")
        if poll:
            self._poll()

    # -- composition -------------------------------------------------------

    def _compose(self) -> None:
        self._build_top()

        middle = ttk.Frame(self.root)
        middle.grid(row=1, column=0, sticky="nsew", padx=PADDING)
        middle.columnconfigure(1, weight=1)
        middle.rowconfigure(0, weight=1)
        self._build_left(middle)
        self._build_right(middle)

        self._build_bottom()

    def _build_top(self) -> None:
        """The video, and what the clipboard holds. Never hidden.

        The selected value is read-only. Clipboard detection can fill an empty
        selection, but replacing an existing video is always explicit.
        """

        bar = ttk.Frame(self.root, padding=(PADDING, PADDING, PADDING, 4))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)

        ttk.Label(bar, text="Video").grid(row=0, column=0, sticky="w")
        self.video_url_label = ttk.Label(
            bar, textvariable=self.video_url, anchor="w"
        )
        self.video_entry = self.video_url_label
        self.video_url_label.grid(
            row=0, column=1, sticky="ew", padx=(10, 6)
        )

        self.paste_button = ttk.Button(
            bar, text="Paste video", command=self.paste_video
        )
        self.paste_button.grid(row=0, column=2, padx=(0, 6))
        self.clear_video_button = ttk.Button(
            bar, text="Clear video", command=self.clear_video
        )
        self.clear_video_button.grid(row=0, column=3, padx=(0, 6))
        self.clip_chip = ttk.Label(bar, textvariable=self.clip_label,
                                   foreground="#4a4a4a")
        self.clip_chip.grid(row=1, column=1, columnspan=3, sticky="e")
        self.use_button = ttk.Button(bar, text="Use clipboard video", width=18,
                                     command=self.use_clipboard,
                                     state="disabled")
        self.use_button.grid(row=2, column=2, columnspan=2, sticky="e")

    def _build_left(self, parent: ttk.Frame) -> None:
        left = ttk.Frame(parent, width=LEFT_WIDTH)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, PADDING))
        left.grid_propagate(False)
        left.columnconfigure(0, weight=1)

        modes = ttk.Frame(left)
        modes.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for text, value in (("Comment", "comment"), ("Reply", "reply")):
            ttk.Radiobutton(modes, text=text, value=value, variable=self.mode,
                            command=self._mode_changed).pack(
                                side="left", padx=(0, 12))

        approaches = ttk.LabelFrame(left, text="Registers and approaches")
        approaches.grid(row=1, column=0, sticky="ew")
        approaches.columnconfigure(0, weight=1)
        canvas_frame = ttk.Frame(approaches)
        canvas_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        canvas_frame.columnconfigure(0, weight=1)
        self.approach_canvas = tk.Canvas(
            canvas_frame, height=190, highlightthickness=0, width=400
        )
        approach_scroll = ttk.Scrollbar(
            canvas_frame, orient="vertical", command=self.approach_canvas.yview
        )
        self.approach_canvas.configure(yscrollcommand=approach_scroll.set)
        self.approach_canvas.grid(row=0, column=0, sticky="ew")
        approach_scroll.grid(row=0, column=1, sticky="ns")
        self.approach_frame = ttk.Frame(self.approach_canvas)
        self.approach_window = self.approach_canvas.create_window(
            (0, 0), window=self.approach_frame, anchor="nw"
        )
        self.approach_frame.bind(
            "<Configure>",
            lambda _e: self.approach_canvas.configure(
                scrollregion=self.approach_canvas.bbox("all")
            ),
        )
        self.approach_canvas.bind(
            "<Configure>",
            lambda e: self.approach_canvas.itemconfigure(
                self.approach_window, width=e.width
            ),
        )
        self.approach_vars: dict[str, tk.BooleanVar] = {}
        self.approach_checks: dict[str, ttk.Checkbutton] = {}
        self._fill_approaches()
        ttk.Label(
            approaches, textvariable=self.approach_summary,
            foreground="#555555", wraplength=LEFT_WIDTH - 24, justify="left",
        ).grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 0))
        summary_buttons = ttk.Frame(approaches)
        summary_buttons.grid(row=2, column=0, sticky="ew", padx=4, pady=(2, 0))
        ttk.Button(
            summary_buttons, text="Clear selections",
            command=self.clear_custom_approaches,
        ).pack(side="left")
        ttk.Label(
            approaches, textvariable=self.resolution_summary,
            foreground="#805000", wraplength=LEFT_WIDTH - 30, justify="left",
        ).grid(row=3, column=0, sticky="ew", padx=4, pady=(2, 4))

        dials = ttk.LabelFrame(left, text="How the answer is written")
        dials.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        dials.columnconfigure(1, weight=1)
        self.dial_boxes: dict[str, ttk.Combobox] = {}
        self.dial_labels: dict[str, ttk.Label] = {}
        for row, (name, entry) in enumerate(DIALS.items()):
            label = ttk.Label(dials, text=f"{entry.label}:")
            label.grid(
                row=row, column=0, sticky="w", padx=(4, 8), pady=1
            )
            box = ttk.Combobox(
                dials, state="readonly", width=34,
                values=[dial_choice_label(v) for v in entry.choices],
            )
            box.set(dial_choice_label(
                self.options.dial_values().get(name, entry.default)))
            box.bind("<<ComboboxSelected>>",
                     lambda _e, dial=name: self._dial_chosen(dial))
            box.grid(row=row, column=1, sticky="ew", padx=(0, 6), pady=1)
            self.dial_boxes[name] = box
            self.dial_labels[name] = label
            for widget in (label, box):
                widget.bind(
                    "<Enter>",
                    lambda _e, dial=name: self._show_dial_help(dial),
                    add="+",
                )
                widget.bind(
                    "<FocusIn>",
                    lambda _e, dial=name: self._show_dial_help(dial),
                    add="+",
                )
                self._tooltips.append(Tooltip(
                    widget, lambda dial=name: self._dial_help(dial)
                ))

        length = ttk.LabelFrame(left, text="Length")
        length.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        row = ttk.Frame(length)
        row.pack(fill="x", padx=4, pady=(4, 0))
        for value, label in LENGTH_CHOICES:
            choice = ttk.Radiobutton(
                row, text=label, value=value, variable=self.length,
                command=self._length_changed
            )
            choice.pack(side="left", padx=(0, 8))
            self._tooltips.append(Tooltip(
                choice, lambda selected=value: LENGTH_HINTS[selected]
            ))
        custom = ttk.Frame(length)
        custom.pack(fill="x", padx=4, pady=(2, 4))
        ttk.Label(custom, text="Target words:").pack(side="left")
        self.custom_length_entry = ttk.Entry(
            custom, textvariable=self.custom_length, width=10
        )
        self.custom_length_entry.pack(side="left", padx=(4, 0))
        self.custom_length_entry.bind(
            "<KeyRelease>", lambda _e: self.refresh()
        )
        self._tooltips.append(Tooltip(
            self.custom_length_entry,
            lambda: LENGTH_HINTS["exact"],
        ))
        ttk.Label(length, textvariable=self.length_hint,
                  foreground="#666666", wraplength=LEFT_WIDTH - 24).pack(
            fill="x", padx=4, pady=(0, 4))
        ttk.Label(length, textvariable=self.length_error,
                  foreground="#a00000", wraplength=LEFT_WIDTH - 24).pack(
            fill="x", padx=4, pady=(0, 4))

        buttons = ttk.Frame(left)
        buttons.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="Advanced...",
                   command=self.open_advanced).pack(side="left")
        ttk.Button(buttons, text="Reset writing options",
                   command=self.reset_options).pack(side="left", padx=(6, 0))

    def _build_right(self, parent: ttk.Frame) -> None:
        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.output_tabs = ttk.Notebook(right)
        self.output_tabs.grid(row=0, column=0, sticky="nsew")

        packet_tab = ttk.Frame(self.output_tabs, padding=PADDING)
        packet_tab.columnconfigure(0, weight=1)
        packet_tab.rowconfigure(1, weight=1)
        self.output_tabs.add(packet_tab, text="Generated packet")
        ttk.Label(
            packet_tab, text="The complete packet appears here after Build.",
            foreground="#444444",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.packet_preview = tk.Text(
            packet_tab, wrap="word", state="disabled", background="#f6f6f6"
        )
        self.packet_preview.grid(row=1, column=0, sticky="nsew")
        packet_actions = ttk.Frame(packet_tab)
        packet_actions.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.build_button = ttk.Button(
            packet_actions, text="Build and copy packet",
            command=self.do_primary,
        )
        self.build_button.pack(side="left")
        self.packet_copy_button = ttk.Button(
            packet_actions, text="Copy again", command=self.do_copy,
            state="disabled",
        )
        self.packet_copy_button.pack(side="left", padx=(6, 0))
        self.packet_count = ttk.Label(packet_actions, text="")
        self.packet_count.pack(side="right")

        # Retained for reply-sequence compatibility; tabs replace this old
        # pseudo-navigation visually.
        self.rail_labels: list[ttk.Label] = []
        for index in range(4):
            label = ttk.Label(right, text="")
            self.rail_labels.append(label)

        card = ttk.LabelFrame(right, text="", padding=PADDING)
        self.output_tabs.add(card, text="Paste answer")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        self.card_title = ttk.Label(card, text="", font=("TkDefaultFont", 10, "bold"))
        self.card_title.grid(row=0, column=0, sticky="w")
        self.card_detail = ttk.Label(card, text="", wraplength=460,
                                     justify="left", foreground="#444444")
        self.card_detail.grid(row=1, column=0, sticky="ew", pady=(4, 6))

        self.said = tk.Text(card, height=4, width=35, wrap="word", state="disabled",
                            relief="flat", background="#f6f6f6")
        self.said.grid(row=2, column=0, sticky="nsew", pady=(0, 6))

        actions = ttk.Frame(card)
        actions.grid(row=3, column=0, sticky="ew")
        self.primary = ttk.Button(actions, text="", command=self.do_primary)
        self.primary.pack(side="left")
        self.copy_button = ttk.Button(actions, text="", command=self.do_copy,
                                      state="disabled")
        self.copy_button.pack(side="left", padx=(6, 0))
        self.cancel_button = ttk.Button(actions, text="Cancel",
                                        command=self.job.cancel,
                                        state="disabled")
        self.cancel_button.pack(side="right")

        footer = ttk.Frame(card)
        footer.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.back_button = ttk.Button(footer, text="Back", command=self.go_back)
        self.back_button.pack(side="left")
        self.skip_button = ttk.Button(footer, text="Skip", command=self.skip)
        self.skip_button.pack(side="left", padx=(6, 0))
        ttk.Button(footer, text="Start over",
                   command=self.start_over).pack(side="left", padx=(6, 0))
        self.progress_label = ttk.Label(footer, text="", foreground="#666666")
        self.progress_label.pack(side="right")
        self.packet_size_label = ttk.Label(
            footer, text="", foreground="#666666"
        )
        self.packet_size_label.pack(side="right", padx=(0, 12))

    def _build_bottom(self) -> None:
        bottom = ttk.Frame(self.root, padding=(PADDING, 4, PADDING, PADDING))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(1, weight=1)

        ttk.Checkbutton(bottom, text="Progress", variable=self.log_open,
                        command=self._toggle_log).grid(row=0, column=0,
                                                       sticky="w")
        ttk.Progressbar(bottom, orient="horizontal", mode="determinate",
                        maximum=1.0, variable=self.progress_value).grid(
            row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Label(bottom, textvariable=self.status).grid(row=0, column=2,
                                                         sticky="e")

        self.log_frame = ttk.Frame(bottom)
        self.log_frame.grid(row=1, column=0, columnspan=3, sticky="ew",
                            pady=(4, 0))
        self.log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(self.log_frame, height=5, wrap="word",
                           state="disabled")
        self.log.grid(row=0, column=0, sticky="ew")
        log_scroll = ttk.Scrollbar(self.log_frame, orient="vertical",
                                   command=self.log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log_frame.grid_remove()

    # -- state -------------------------------------------------------------

    def _fill_approaches(self) -> None:
        for tooltip in self._approach_tooltips:
            tooltip.destroy()
        self._approach_tooltips = []
        for child in self.approach_frame.winfo_children():
            child.destroy()
        self.approach_vars = {}
        self.approach_checks = {}
        mode = self.mode.get()
        selected = set(
            self.options.reply_variations if mode == "reply"
            else self.options.comment_variations
        )
        self.approach_mode.set("custom" if selected else "default")
        for row, (key, label, dimension, description) in enumerate(
            approach_choices(mode)
        ):
            variable = tk.BooleanVar(value=key in selected)
            text = f"{label}  [{dimension}]"
            check = ttk.Checkbutton(
                self.approach_frame,
                text=text,
                variable=variable,
                command=self._approach_selected,
            )
            check.grid(row=row, column=0, sticky="w", padx=2, pady=1)
            help_text = description
            check.bind(
                "<Enter>",
                lambda _e, value=help_text: self._show_help(value),
                add="+",
            )
            check.bind(
                "<FocusIn>",
                lambda _e, value=help_text: self._show_help(value),
                add="+",
            )
            self._approach_tooltips.append(
                Tooltip(check, lambda value=help_text: value))
            self.approach_vars[key] = variable
            self.approach_checks[key] = check
        self._apply_resolved_approaches()
        self._update_approach_state()

    def _mode_changed(self) -> None:
        old_mode = self._display_mode
        self._store_approaches(old_mode)
        self._display_mode = self.mode.get()
        self._fill_approaches()
        self.refresh()

    def _store_approaches(self, mode: str | None = None) -> None:
        target = mode or self.mode.get()
        chosen = tuple(
            key for key, variable in self.approach_vars.items()
            if variable.get()
        )
        selection_mode = "custom" if chosen else "default"
        self.approach_mode.set(selection_mode)
        if target == "reply":
            self.options.reply_approach_mode = selection_mode
            self.options.reply_variations = (
                chosen if selection_mode == "custom" else ()
            )
        else:
            self.options.comment_approach_mode = selection_mode
            self.options.comment_variations = (
                chosen if selection_mode == "custom" else ()
            )

    def _approach_selected(self) -> None:
        self._store_approaches()
        self._apply_resolved_approaches()
        self._update_approach_state()
        self.refresh()

    def _apply_resolved_approaches(self) -> None:
        chosen = tuple(
            key for key, variable in self.approach_vars.items()
            if variable.get()
        ) or self.options.registers_for(self.mode.get())
        resolved = resolved_approaches(
            chosen, self.options.dial_values(), mode=self.mode.get()
        )
        if resolved == chosen:
            self.resolution_summary.set("")
            return
        labels = {key: label for key, label, _dimension, _description
                  in approach_choices(self.mode.get())}
        removed = [labels[key] for key in chosen if key not in resolved]
        added = [labels[key] for key in resolved if key not in chosen]
        self.resolution_summary.set(
            f"Packet resolution: {', '.join(removed)} will be replaced by "
            f"{', '.join(added)}.\nYour saved selection is unchanged."
        )

    def _update_approach_state(self) -> None:
        count = sum(variable.get() for variable in self.approach_vars.values())
        self.approach_summary.set(
            f"{count} custom approach{'es' if count != 1 else ''} selected."
            if count else
            "No custom approaches selected — defaults will be used."
        )
        self._apply_resolved_approaches()

    def clear_custom_approaches(self) -> None:
        for variable in self.approach_vars.values():
            variable.set(False)
        self._store_approaches()
        self._update_approach_state()
        self.refresh()

    def use_default_approaches(self) -> None:
        for variable in self.approach_vars.values():
            variable.set(False)
        self._store_approaches()
        self._update_approach_state()
        self.refresh()

    def _dial_help(self, dial: str) -> str:
        return dial_help(dial, self.options.dial_values()[dial])

    def _show_dial_help(self, dial: str) -> None:
        self._show_help(self._dial_help(dial))

    def _show_help(self, text: str) -> None:
        # Detailed help is exposed by stable tooltips; no dynamic panel means
        # changing a choice cannot move the controls below it.
        self.help_text.set(text)

    def _dial_chosen(self, dial: str) -> None:
        box = self.dial_boxes[dial]
        for value in DIALS[dial].choices:
            if dial_choice_label(value) == box.get():
                self.options.dials[dial] = value
                break
        self._show_dial_help(dial)
        self._apply_resolved_approaches()
        self._update_approach_state()
        self.refresh()

    def _length_changed(self) -> None:
        self.refresh()

    def gather(self) -> PacketOptionsModel:
        """Read the widgets back into the model. One direction, one place."""

        self.options.video = self.video.get().strip()
        self.options.length = self.length.get()
        self.options.custom_length = self.custom_length.get()
        self._store_approaches()
        return self.options

    def refresh(self) -> None:
        options = self.gather()
        self.length_hint.set(LENGTH_SUMMARIES.get(options.length, ""))
        length_problems = [
            problem for problem in options.problems(mode=self.mode.get())
            if "target word" in problem.lower()
        ]
        self.length_error.set(length_problems[0] if length_problems else "")
        self._enable(
            self.custom_length_entry, self.length.get() == "exact"
        )
        if options.video:
            try:
                identifier = extract_video_id(options.video)
            except ConfigurationError:
                self.video_url.set("")
            else:
                self.video_url.set(watch_url(identifier))
        else:
            self.video_url.set("")
        self.packet_size_label.configure(text="", foreground="#666666")
        self.packet_preview.configure(state="normal")
        self.packet_preview.delete("1.0", "end")
        self.packet_preview.insert(
            "1.0", self.last_packet or "Build a packet first."
        )
        self.packet_preview.configure(state="disabled")
        self.packet_count.configure(
            text=(f"{len(self.last_packet):,} characters"
                  if self.last_packet else "")
        )
        self._enable(self.packet_copy_button, bool(self.last_packet))
        self.output_tabs.tab(
            1, state=("normal" if self.last_packet else "disabled")
        )

        view = self.sequence.view(
            clipboard="", packet=self.last_packet,
            building=self.job.running,
        )
        reply_mode = self.mode.get() == "reply"

        for index, label in enumerate(self.rail_labels):
            if reply_mode and index < len(view.rail):
                entry = view.rail[index]
                label.configure(text=f"{entry.marker} {entry.label}")
            elif not reply_mode and index == 0:
                label.configure(text="> Build")
            else:
                label.configure(text="")

        if reply_mode:
            self.card_title.configure(text=view.title)
            self.card_detail.configure(text=view.detail)
            self.primary.configure(text=view.primary_label)
            self.copy_button.configure(
                text="Copy again" if self.last_packet else (view.copy_label or "Copy")
            )
            self.progress_label.configure(text=view.progress)
            self._enable(self.back_button, view.can_go_back)
            self._enable(self.skip_button, view.can_skip)
        else:
            waiting = getattr(self, "comment_session", None) is not None
            offer = getattr(self, "_offer", None)
            self.card_title.configure(
                text=("Paste the answer" if waiting
                      else "Build a comment packet"))
            self.card_detail.configure(
                text=("The packet is ready. Copy it, paste it into your "
                      "model, then bring the answer back here. Accepted "
                      "drafts are saved; nothing is posted."
                      if waiting else
                      "Builds from this video's transcript and comment "
                      "section. The packet lands on your clipboard.")
            )
            self.primary.configure(
                text=("Use the answer on the clipboard" if waiting
                      else "Build packet"))
            self.copy_button.configure(
                text="Copy again" if self.last_packet else "Copy packet"
            )
            self.progress_label.configure(text="")
            self._enable(self.back_button, False)
            self._enable(self.skip_button, False)
            for index, label in enumerate(self.rail_labels):
                if index == 0:
                    label.configure(text="✓ Build" if waiting else "● Build")
                elif index == 1:
                    label.configure(text="● Answer" if waiting else "○ Answer")
                else:
                    label.configure(text="")

        has_video = bool(options.video)
        # Once a packet exists the button means "take the answer", and that
        # is dead until the clipboard actually holds one.
        if self.mode.get() == "comment" and \
                getattr(self, "comment_session", None) is not None:
            offer = getattr(self, "_offer", None)
            self._enable(self.primary,
                         bool(offer is not None and offer.offered))
            self._enable(self.copy_button, bool(self.last_packet))
            self._enable(self.cancel_button, self.job.running)
            self._enable(self.build_button, False)
            self.status.set(self._message or "Packet built and copied.")
            return

        blockers = options.problems(mode=self.mode.get())
        self._enable(
            self.primary,
            has_video and not self.job.running and not blockers,
        )
        self._enable(
            self.build_button,
            has_video and not self.job.running and not blockers,
        )
        self._enable(self.copy_button, bool(self.last_packet))
        self._enable(self.cancel_button, self.job.running)

        # The last thing said wins. refresh() runs after every action, so
        # setting the status unconditionally here wiped every message a
        # microsecond after it appeared -- including "Nothing to paste", which
        # is the one the operator most needs to read.
        self.status.set(self._message or (
            blockers[0] if blockers else
            ("Ready." if has_video
             else "Copy a YouTube link or ID, or use Paste video.")
        ))

    def _enable(self, widget: Any, on: bool) -> None:
        widget.configure(state=("normal" if on else "disabled"))

    def _toggle_log(self) -> None:
        if self.log_open.get():
            self.log_frame.grid()
        else:
            self.log_frame.grid_remove()

    # -- clipboard ---------------------------------------------------------

    def read_clipboard(self) -> str:
        if self.clipboard is None:
            return ""
        try:
            return self.clipboard.read()
        except Exception:                   # noqa: BLE001 - reporting only
            return ""

    def poll_clipboard(self) -> None:
        """Report clipboard state and adopt only into an empty video slot."""

        if self.mode.get() == "reply":
            step = self.sequence.step
        elif getattr(self, "comment_session", None) is not None:
            # A packet has been built, so what this step wants is an answer to
            # it -- not another video. Asking for the wrong shape is how a
            # perfectly good answer gets reported as "something else".
            step = Step.PEOPLE
        else:
            step = Step.BUILD
        offer = read_clipboard(self.read_clipboard(), step=step,
                               packet=self.last_packet)
        previous = getattr(self, "_offer", None)
        self.clip_label.set(offer.label)
        current_video = self.video.get().strip()
        if offer.holding.name == "VIDEO":
            suppressed = offer.payload == self._suppressed_clipboard_video
            if offer.payload != self._suppressed_clipboard_video:
                self._suppressed_clipboard_video = ""
            if not current_video and not suppressed:
                self.video.set(offer.payload)
                self.video_url.set(watch_url(offer.payload))
                self.clip_label.set(
                    f"Clipboard: YouTube video detected ({offer.payload})"
                )
                self.use_button.configure(text="Use clipboard video")
                self._enable(self.use_button, False)
            elif offer.payload != current_video:
                self.clip_label.set(
                    f"Clipboard: YouTube video is available "
                    f"({offer.payload})"
                )
                self.use_button.configure(
                    text="Replace" if current_video else "Use clipboard video"
                )
                self._enable(self.use_button, True)
            else:
                self.clip_label.set(
                    f"Clipboard: selected YouTube video ({offer.payload})"
                )
                self._enable(self.use_button, False)
        else:
            # Suppression belongs only to one uninterrupted clipboard value.
            # Once the clipboard changes, that old video may be adopted again.
            self._suppressed_clipboard_video = ""
            self.use_button.configure(text="Use clipboard video")
            self._enable(self.use_button, offer.offered)
        self._offer = offer

        # The primary button's enablement is decided in refresh() from this
        # offer, so without a redraw the chip would announce an answer while
        # the button to use it stayed grey. Only on a change: refreshing on
        # every poll would fight the operator's typing twice a second.
        if previous is None or previous.offered != offer.offered:
            self.refresh()

    def _window_focused(self, _event=None) -> None:
        self.poll_clipboard()

    def _poll(self) -> None:                # pragma: no cover - timer loop
        self.poll_clipboard()
        for event in self.job.drain():
            self._on_event(event)
        self.root.after(CLIPBOARD_POLL_MS, self._poll)

    def use_clipboard(self) -> None:
        """Take what the chip is offering. Only ever pressed by hand."""

        offer = getattr(self, "_offer", None)
        if offer is None or not offer.offered:
            return
        if offer.holding.name == "VIDEO":
            self._suppressed_clipboard_video = ""
            self.video.set(offer.payload)
            self.video_url.set(watch_url(offer.payload))
        else:
            self.say(f"Took an answer of {len(offer.payload):,} characters.")
        self.refresh()

    def paste_video(self) -> None:
        """Put whatever video the clipboard holds into the box.

        Deliberately not a refusal when there is none: the selection remains
        unchanged and the window can stay open without a video.
        """

        offer = read_clipboard(self.read_clipboard(), step=Step.BUILD,
                               packet=self.last_packet)
        if offer.holding.name == "VIDEO":
            self._suppressed_clipboard_video = ""
            self.video.set(offer.payload)
            self.video_url.set(watch_url(offer.payload))
        else:
            self.say(f"Nothing to paste. {offer.label}")
        self.refresh()

    def clear_video(self) -> None:
        offer = read_clipboard(
            self.read_clipboard(), step=Step.BUILD, packet=self.last_packet)
        self._suppressed_clipboard_video = (
            offer.payload if offer.holding.name == "VIDEO" else ""
        )
        self.video.set("")
        self.video_url.set("")
        self.comment_session = None
        self.session = None
        self.sequence = ReplySequence()
        self.result = None
        self.triage_packet = ""
        self.current_packet = ""
        self.last_packet = ""
        self._offer = None
        self.progress_value.set(0.0)
        self._message = ""
        self.say("Video selection cleared.")
        self.poll_clipboard()
        self.refresh()

    # -- actions -----------------------------------------------------------

    def do_primary(self) -> None:
        # Past the first step of a reply run the primary action is "take the
        # answer on the clipboard", which is not a build and must not spend
        # a single request.
        if (self.mode.get() == "reply"
                and self.sequence.step is not Step.BUILD
                and getattr(self, "session", None) is not None):
            if self.sequence.step is Step.TRIAGE:
                self.take_triage()
            elif self.sequence.step is Step.FINISH:
                message = self._open_path(str(getattr(
                    getattr(self, "session").artifacts, "root", "")))
                if message:
                    self.say(message)
            else:
                self.take_answer()
            return

        # Comment mode has two states, not one: build a packet, then take the
        # answer to it. Without the second, the window could produce a packet
        # and had nowhere to put what came back.
        if (self.mode.get() == "comment"
                and getattr(self, "comment_session", None) is not None):
            self.take_comment_answer()
            return

        options = self.gather()
        problems = options.problems(mode=self.mode.get())
        if problems:
            for problem in problems:
                self.say(problem)
            self.status.set(problems[0])
            return
        if self._build_packet is None:
            self.say("No builder was supplied, so nothing was run.")
            return

        # Read on this thread and closed over as a plain string. Calling
        # self.mode.get() inside the lambda reads a Tk variable from the
        # worker thread, which is the rule worker.py exists to keep and which
        # fails as "main thread is not in main loop" the moment a real build
        # starts. The options object is likewise a snapshot, so editing a
        # field mid-build cannot change what is being built.
        mode = self.mode.get()
        self._discard_job_result = False
        started = self.job.start(
            lambda job: self._build_packet(options, mode, job)
        )
        if not started:
            self.say("A build is already running.")
        self.refresh()

    def take_answer(self) -> None:
        """Hand the clipboard's answer to the session. Pressed, never automatic.

        The session decides whether it is an answer at all — packet detection
        before extraction, the same order everywhere — so a refusal here is
        the product working and is shown rather than swallowed.
        """

        session = getattr(self, "session", None)
        offer = getattr(self, "_offer", None)
        if session is None:
            return
        if offer is None or not offer.offered:
            self.say("There is no answer on the clipboard to use.")
            return

        try:
            # The raw clipboard, not the extracted draft. The session owns
            # what counts as an answer; handing it an already-extracted one
            # made it extract a second time from text whose heading had gone.
            result = session.submit(offer.raw)
        except Exception as refusal:        # noqa: BLE001 - reported, not raised
            # The session refuses an answer for a person whose packet was
            # never copied, because a copy is how it knows the packet
            # actually went out. That is the product working, so it is shown
            # rather than swallowed -- and it is not fixed by copying for
            # him, which would overwrite the very answer he is submitting.
            self.say(f"{refusal} Copy this person's packet first.")
            self.refresh()
            return

        if getattr(getattr(result, "status", None), "value", "") == "refused":
            self.say(session.state.last_error
                     or "That paste could not be used.")
            self.refresh()
            return

        self.sequence.accepted = len(session.accepted)
        self.say(f"Saved. {len(session.accepted)} so far.")
        self.sequence.next_person()
        if self.sequence.step is Step.PEOPLE:
            self._start_person()
        else:
            session.finish()
        self.refresh()

    def _adopt_comment(self, packet: Any) -> None:
        """Open a session over the comment packet just built.

        Comment mode could build a packet and copy it and then had nowhere to
        put the answer, while reply mode saved every accepted draft. The same
        session type does it: same refusal order, same immediate save, same
        "nothing is ever posted".
        """

        if self._comment_session_factory is None:
            return
        try:
            self.comment_session = self._comment_session_factory(packet)
            self.comment_session.start()
        except Exception as failure:        # noqa: BLE001 - reported
            self.comment_session = None
            self.say(f"The packet was built but cannot take an answer: "
                     f"{failure}")

    def take_comment_answer(self) -> None:
        """Save the model's comment. Pressed, never automatic."""

        session = getattr(self, "comment_session", None)
        offer = getattr(self, "_offer", None)
        if session is None:
            self.say("Build a packet first.")
            return
        if offer is None or not offer.offered:
            self.say("There is no answer on the clipboard to use.")
            return

        try:
            # The raw clipboard: the session owns what counts as an answer.
            result = session.submit(offer.raw)
        except Exception as refusal:        # noqa: BLE001 - reported
            self.say(f"{refusal} Copy the packet first.")
            return

        if getattr(getattr(result, "status", None), "value", "") == "refused":
            self.say(session.state.last_error
                     or "That paste could not be used.")
            self.refresh()
            return

        session.finish()
        self.say(f"Draft saved. {len(session.accepted)} so far.")
        self.refresh()

    def _adopt_session(self, run: Any) -> None:
        """Take the session and the triage packet a reply scan produced."""

        self.session = run.session
        self.triage_packet = run.triage_packet
        people = [getattr(t, "author", "") for t in run.session.targets]
        self.sequence = ReplySequence(people=tuple(people))

        if not people:
            self.sequence.advance_to(Step.FINISH)
            self.say("Nobody on this video is waiting for an answer.")
            return

        if self.triage_packet:
            # Triage first: ask which of these are worth answering before
            # spending a packet each on all of them. Skipping straight to the
            # queue is what the Skip button on this step is for.
            self.sequence.advance_to(Step.TRIAGE)
            self.last_packet = self.triage_packet
            copied = self._copy_current_packet(auto=True)
            if not copied:
                self.say(
                    f"{len(people)} people found. The triage template is "
                    "ready; use Copy again."
                )
            return

        self.sequence.advance_to(Step.PEOPLE)
        self._start_person()
        self._copy_current_packet(auto=True)

    def take_triage(self) -> None:
        """Narrow the queue to the people the model picked out.

        A selection naming nobody we know is refused rather than emptying the
        queue: the likeliest cause is a paste from the wrong conversation, and
        silently ending the run over it would look like nobody was waiting.
        """

        from ...domain.extraction import parse_triage_selection

        offer = getattr(self, "_offer", None)
        session = getattr(self, "session", None)
        if session is None or offer is None or not offer.offered:
            self.say("There is no triage answer on the clipboard to use.")
            return

        wanted = {handle.lstrip("@").casefold()
                  for handle in parse_triage_selection(offer.raw)}
        if not wanted:
            self.say("No handles were found in that answer. The queue is "
                     "unchanged.")
            return

        kept = [t for t in session.targets
                if str(getattr(t, "author", "")).lstrip("@").casefold() in wanted]
        if not kept:
            self.say(
                f"That answer named {len(wanted)} people, none of them in "
                "this queue. The queue is unchanged."
            )
            return

        session.targets = kept
        self.sequence = ReplySequence(
            people=tuple(getattr(t, "author", "") for t in kept))
        self.sequence.advance_to(Step.PEOPLE)
        self.say(f"Working through {len(kept)} of {len(wanted)} chosen.")
        self._start_person()

    def _start_person(self) -> None:
        """Move the session to the person the rail is showing."""

        session = getattr(self, "session", None)
        if session is None:
            return
        try:
            if session.state.phase.value == "idle":
                session.start()
            session.next_person()
            self.last_packet = session.current_packet
        except Exception as refusal:        # noqa: BLE001 - reported, not raised
            self.say(str(refusal))

    def _copy_current_packet(self, *, auto: bool = False) -> bool:
        """Copy the packet in front of you.

        In a reply run this goes through the session rather than round the
        side of it: copying is how the session knows the packet went out, and
        a window that wrote to the clipboard itself would leave the session
        refusing the answer that comes back.
        """

        try:
            session = getattr(self, "session", None)
            if (self.mode.get() == "reply"
                    and self.sequence.step is Step.TRIAGE
                    and getattr(self, "triage_packet", "")):
                if self.clipboard is not None:
                    self.clipboard.write(self.triage_packet)
                self.last_packet = self.triage_packet
            elif self.mode.get() == "reply" and session is not None:
                self.last_packet = session.copy_packet()
            else:
                comment_session = getattr(self, "comment_session", None)
                if comment_session is not None:
                    self.last_packet = comment_session.copy_packet()
                elif self.last_packet and self.clipboard is not None:
                    self.clipboard.write(self.last_packet)
            if not self.last_packet:
                return False
        except Exception as failure:        # noqa: BLE001 - recoverable copy
            self.say(
                f"Packet built, but the clipboard copy failed: {failure}. "
                "Use Copy again."
            )
            self.refresh()
            return False

        prefix = "Packet built and copied" if auto else "Copied again"
        self.say(f"{prefix}: {len(self.last_packet):,} characters.")
        self.copy_button.configure(text="Copy again")
        self.refresh()
        return True

    def do_copy(self) -> None:
        self._copy_current_packet(auto=False)

    def go_back(self) -> None:
        order = list(Step)
        index = order.index(self.sequence.step)
        if index:
            self.sequence.advance_to(order[index - 1])
        self.refresh()

    def skip(self) -> None:
        """Skip this step, whatever this step is.

        On triage that means "work through everyone rather than asking which
        are worth it". On a person it means the next person.
        """

        if self.sequence.step is Step.TRIAGE:
            self.sequence.advance_to(Step.PEOPLE)
            self.say("Skipping triage; working through everyone.")
            self._start_person()
        else:
            self.sequence.next_person()
            if self.sequence.step is Step.PEOPLE:
                self._start_person()
        self.refresh()

    def start_over(self) -> None:
        if self.job.running:
            self.job.cancel()
            self._discard_job_result = True
        self.comment_session = None
        self.session = None
        self.sequence = ReplySequence()
        self.result = None
        self.triage_packet = ""
        self.current_packet = ""
        self.last_packet = ""
        self._offer = None
        self.progress_value.set(0.0)
        self._message = ""
        self.refresh()

    def reset_options(self) -> None:
        self.options = self.options.reset_output_options()
        for name, box in self.dial_boxes.items():
            box.set(dial_choice_label(DIALS[name].default))
        self._fill_approaches()
        self.refresh()

    def open_advanced(self) -> None:        # pragma: no cover - opens a dialog
        AdvancedDialog(self.root, self.options, on_close=self.refresh)

    # -- worker events -----------------------------------------------------

    def _on_event(self, event) -> None:
        if self._discard_job_result and event.kind in (
            "done", "failed", "cancelled"
        ):
            self._discard_job_result = False
            self.refresh()
            return
        if event.kind == "progress":
            # A blank message still moves the bar but must not write a line.
            # Reply retrieval emits one event per thread with nothing to say,
            # and a live build filled the log with ten empty rows.
            if event.message.strip():
                self.say(event.message)
            if event.fraction is not None:
                self.progress_value.set(event.fraction)
        elif event.kind == "done":
            self.result = event.value
            if hasattr(event.value, "session"):
                # A reply run hands back a guided session rather than a
                # packet: it owns every rule about who gets which packet and
                # what counts as an answer, so the window drives it instead
                # of deciding any of that a second time.
                self._adopt_session(event.value)
            else:
                self.last_packet = str(getattr(event.value, "text", "") or "")
                self._adopt_comment(event.value)
                self._copy_current_packet(auto=True)
            # Completion is already stated in the status line. Leaving a
            # permanently full bar makes an idle window look busy.
            self.progress_value.set(0.0)
            if not self.last_packet:
                self.say(event.message)
        elif event.kind == "cancelled":
            self.say("Stopped at the next safe point.")
        else:
            self.say(event.message)
            self._notify("That did not work", event.message)
        self.refresh()

    def say(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self._message = message.splitlines()[0][:120] if message else ""
        self.status.set(self._message)

    def clear_message(self) -> None:
        """Let the status line go back to describing the state."""

        self._message = ""
        self.refresh()

    def _default_notify(self, title: str, message: str) -> None:  # pragma: no cover
        from tkinter import messagebox

        messagebox.showwarning(title, message)


class AdvancedDialog:                       # pragma: no cover - opens a dialog
    """The settings nobody changes twice: keys, folders, counts, proxy."""

    FIELDS = (
        ("output_directory", "Output folder", str),
        ("editor_path", "Open files with", str),
        ("languages", "Transcript languages", str),
        ("proxy_url", "Proxy URL", str),
        ("my_handle", "Your @username", str),
        ("max_top", "Relevance comments", int),
        ("max_recent", "Recent comments", int),
        ("max_threads", "Reply threads", int),
        ("max_replies", "Replies per thread", int),
        ("packet_characters", "Packet characters", int),
    )

    def __init__(self, parent, options: PacketOptionsModel, on_close=None):
        self.options = options
        self.on_close = on_close or (lambda: None)
        self.top = tk.Toplevel(parent)
        self.top.title("Advanced")
        self.top.transient(parent)
        self.variables: dict[str, tk.Variable] = {}

        frame = ttk.Frame(self.top, padding=PADDING)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        for row, (name, label, kind) in enumerate(self.FIELDS):
            ttk.Label(frame, text=f"{label}:").grid(row=row, column=0,
                                                    sticky="w", pady=2)
            variable: tk.Variable = (tk.IntVar(value=getattr(options, name))
                                     if kind is int
                                     else tk.StringVar(value=getattr(options, name)))
            self.variables[name] = variable
            widget = (ttk.Spinbox(frame, from_=0, to=2_000_000, increment=10,
                                  textvariable=variable, width=14)
                      if kind is int
                      else ttk.Entry(frame, textvariable=variable, width=44))
            widget.grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=2)

        row = len(self.FIELDS)
        self.include_replies = tk.BooleanVar(value=options.include_replies)
        ttk.Checkbutton(frame, text="Retrieve replies",
                        variable=self.include_replies).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.overwrite = tk.BooleanVar(value=options.overwrite)
        ttk.Checkbutton(frame, text="Overwrite a previous output folder",
                        variable=self.overwrite).grid(
            row=row + 1, column=0, columnspan=2, sticky="w")

        ttk.Button(frame, text="Done", command=self.close).grid(
            row=row + 2, column=1, sticky="e", pady=(10, 0))

    def close(self) -> None:
        for name, variable in self.variables.items():
            try:
                setattr(self.options, name, variable.get())
            except tk.TclError:
                continue
        self.options.include_replies = self.include_replies.get()
        self.options.overwrite = self.overwrite.get()
        self.top.destroy()
        self.on_close()


def launch(**kwargs) -> PacketWindow:       # pragma: no cover - real Tk
    window = PacketWindow(**kwargs)
    window.root.deiconify()
    window.root.lift()
    window.root.mainloop()
    return window
