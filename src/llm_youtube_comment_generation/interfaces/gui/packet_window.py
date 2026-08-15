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

**Activity is visible.** Retrieval and processing messages live in the
default Activity tab. Transcript evidence has its own tab, while the bottom
bar remains a compact summary of transcript state, progress, and status.

Two rules this window is built around, both of them the operator's:

**It opens without a video.** The old one, and the first rebuilt one, resolved
a video before a window existed—so a window could not be opened to look at,
and "nothing is on the clipboard" was a reason to refuse rather than a state to
show. The read-only selection starts empty, the clipboard is inspected on open
and focus, and a valid video can arrive whenever.

**Watching the clipboard never advances the workflow.** It may fill an empty
video slot, but it never replaces a selected video or consumes a model answer
without an explicit action.
"""

from __future__ import annotations

import copy
import json
import os
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from ...domain.writing_options import DIALS, dial_choice_label
from ...domain.writing_presets import BUILT_IN_PRESETS, WritingPreset
from ...domain.errors import ConfigurationError
from ...domain.ids import extract_video_id
from ...domain.video import format_timestamp, watch_url
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
from .layout import initial_size, valid_saved_geometry
from .run_receipt import (
    comment_receipt,
    reply_receipt,
    transcript_notification,
)
from .evidence_views import (
    comments_text,
    description_text,
    metadata_text,
    replies_text,
)
from .widgets import TextContextMenu, Tooltip
from .advanced_dialog import AdvancedDialog

PADDING = 8
LEFT_WIDTH = 440
WINDOW_WIDTH = 1024
WINDOW_HEIGHT = 700
CURRENT_PRESET = "Current settings"

#: How often the clipboard chip refreshes. Slow enough to cost nothing, fast
#: enough that copying an answer and looking up feels immediate.
CLIPBOARD_POLL_MS = 700


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
        preset_store: Any = None,
        ask_preset_name: Callable[[], str | None] | None = None,
        confirm_delete_preset: Callable[[str], bool] | None = None,
        confirm_record_posted: Callable[[str], bool] | None = None,
        confirm_whisper: Callable[[str], bool] | None = None,
        notify: Callable[[str, str], None] | None = None,
        poll: bool = True,
        mode: str = "comment",
    ) -> None:
        self._owns_root = root is None
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
        self._preset_store = preset_store
        self._ask_preset_name = (
            ask_preset_name or self._default_ask_preset_name
        )
        self._confirm_delete_preset = (
            confirm_delete_preset or self._default_confirm_delete_preset
        )
        self._confirm_record_posted = (
            confirm_record_posted or self._default_confirm_record_posted
        )
        self._confirm_whisper = (
            confirm_whisper or self._default_confirm_whisper
        )
        self._presets: dict[str, WritingPreset] = {}
        self._reload_presets()
        self.comment_session: Any = None
        # Injected: the default is a modal dialog, and a modal dialog blocks
        # the event loop until somebody clicks it. That is untestable and it
        # hangs an automated run.
        self._notify = notify or self._default_notify
        self.job = BackgroundJob()
        self.sequence = ReplySequence()
        self.generated_packet = ""
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
        self.debug_build = tk.BooleanVar(value=False)
        self.run_receipt = tk.StringVar(value="")
        self.approach_summary = tk.StringVar(value="")
        self.approach_filter = tk.StringVar(value="")
        self.preset_name = tk.StringVar(value=CURRENT_PRESET)
        # Retained as model compatibility only. There are no mode radio
        # buttons: checkbox count is the visible and authoritative mode.
        self.approach_mode = tk.StringVar(value="default")
        self.resolution_summary = tk.StringVar(value="")
        self.help_text = tk.StringVar(value="")
        self.progress_value = tk.DoubleVar(value=0.0)
        self.transcript_notice = tk.StringVar(
            value="Not checked yet."
        )
        self._tooltips: list[Tooltip] = []
        self._approach_tooltips: list[Tooltip] = []
        self._display_mode = self.mode.get()
        self._suppressed_clipboard_video = ""
        self._active_job_generation = 0
        self._live_transcript_started = False
        self._pending_build_signature = ""
        self._completed_build_signature = ""
        self._message = initial_video_error
        self._text_context_menus: list[TextContextMenu] = []
        self.evidence_tabs: dict[str, ttk.Frame] = {}
        self.evidence_views: dict[str, tk.Text] = {}
        self.evidence_copy_buttons: dict[str, ttk.Button] = {}

        self.root.title("YouTube packet builder")
        self.root.minsize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        self._compose()
        if self._owns_root:
            self._apply_initial_geometry()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Control-b>", self._shortcut_build, add="+")
        self.root.bind("<Control-Shift-C>", self._shortcut_copy, add="+")
        self.refresh()
        self.root.bind("<FocusIn>", self._window_focused, add="+")
        if poll:
            self._poll()

    # -- composition -------------------------------------------------------

    def _compose(self) -> None:
        self._build_top()

        middle = ttk.Panedwindow(self.root, orient="horizontal")
        middle.grid(row=1, column=0, sticky="nsew", padx=PADDING)
        left = self._build_left(middle)
        right = self._build_right(middle)
        middle.add(left, weight=0)
        middle.add(right, weight=1)
        self.middle_panes = middle

        self._build_bottom()

    def _tip(self, widget: tk.Misc, text: str | Callable[[], str]) -> None:
        provider = text if callable(text) else (lambda value=text: value)
        self._tooltips.append(Tooltip(widget, provider))

    def _apply_initial_geometry(self) -> None:
        saved = str(self.options.window_geometry or "").strip()
        if valid_saved_geometry(saved):
            self.root.geometry(saved)
            return
        width, height = initial_size(
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
        )
        self.root.geometry(f"{width}x{height}")

    def close(self) -> None:
        """Cancel active work before destroying the Tk event loop."""

        for event in self.job.drain():
            if event.kind == "confirmation":
                request = event.value
                if hasattr(request, "resolve"):
                    request.resolve(False)
        if self.job.running:
            self.job.cancel()
            self._active_job_generation = -1
            self.status.set("Stopping before closing...")
            self.root.after(50, self.close)
            return

        try:
            self.options.window_geometry = self.root.geometry()
        except tk.TclError:
            pass
        self.root.destroy()

    def _shortcut_build(self, _event=None) -> str:
        if (
            getattr(self, "comment_session", None) is None
            and getattr(self, "session", None) is None
        ):
            self.do_primary()
        return "break"

    def _shortcut_copy(self, _event=None) -> str:
        self.do_copy()
        return "break"

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
        self._tip(
            self.video_url_label,
            "The YouTube video currently selected for the next build.",
        )

        self.paste_button = ttk.Button(
            bar, text="Paste video", command=self.paste_video
        )
        self.paste_button.grid(row=0, column=2, padx=(0, 6))
        self._tip(
            self.paste_button,
            "Select the YouTube link or video ID currently on the clipboard.",
        )
        self.clear_video_button = ttk.Button(
            bar, text="Clear video", command=self.clear_video
        )
        self.clear_video_button.grid(row=0, column=3, padx=(0, 6))
        self._tip(
            self.clear_video_button,
            "Clear only the selected video and its current packet.",
        )
        self.clip_chip = ttk.Label(bar, textvariable=self.clip_label,
                                   foreground="#4a4a4a")
        self.clip_chip.grid(row=1, column=1, columnspan=3, sticky="e")
        self.use_button = ttk.Button(bar, text="Use clipboard video", width=18,
                                     command=self.use_clipboard,
                                     state="disabled")
        self.use_button.grid(row=2, column=2, columnspan=2, sticky="e")
        self._tip(
            self.use_button,
            "Use the detected clipboard video. If another video is selected, "
            "this replaces it.",
        )

        workflow = ttk.Frame(bar)
        workflow.grid(row=2, column=1, sticky="w", pady=(4, 0))
        self.build_button = ttk.Button(
            workflow,
            text="Build",
            command=self.build_packet,
        )
        self.build_button.pack(side="left")
        self.stop_button = ttk.Button(
            workflow,
            text="Stop",
            command=self.stop_build,
            state="disabled",
        )
        self.stop_button.pack(side="left", padx=(6, 0))
        self.reset_button = ttk.Button(
            workflow,
            text="Reset",
            command=self.reset_all,
        )
        self.reset_button.pack(side="left", padx=(14, 0))
        self.debug_build_check = ttk.Checkbutton(
            workflow,
            text="Debug build",
            variable=self.debug_build,
            command=self.refresh,
        )
        self.debug_build_check.pack(side="left", padx=(14, 0))
        self._tip(
            self.build_button,
            "Retrieve the selected video evidence, create the packet, and "
            "copy it to the clipboard.",
        )
        self._tip(
            self.stop_button,
            "Stop the active retrieval or transcription at the next safe point.",
        )
        self._tip(
            self.reset_button,
            "Return the whole window to its opening state and clear every tab.",
        )
        self._tip(
            self.debug_build_check,
            "For this one build, add a diagnostic request and save a bundle "
            "with safe settings, the packet, and the full model response. "
            "The bundle is unredacted: review it before sharing it.",
        )

    def _build_left(self, parent: ttk.Frame) -> ttk.Frame:
        left = ttk.Frame(parent, width=LEFT_WIDTH)
        left.grid_propagate(False)
        left.columnconfigure(0, weight=1)

        modes = ttk.Frame(left)
        modes.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.mode_bar = modes
        self.mode_buttons: list[ttk.Radiobutton] = []
        for text, value in (("Comment", "comment"), ("Reply", "reply")):
            button = ttk.Radiobutton(
                modes,
                text=text,
                value=value,
                variable=self.mode,
                command=self._mode_changed,
            )
            button.pack(side="left", padx=(0, 12))
            self.mode_buttons.append(button)
            self._tip(
                button,
                "Build a new top-level comment."
                if value == "comment"
                else "Find replies to your comments and draft responses.",
            )
        self.reset_options_button = ttk.Button(
            modes, text="Reset writing options", command=self.reset_options
        )
        self.reset_options_button.pack(side="right")
        self._tip(
            self.reset_options_button,
            "Reset only approaches, writing choices, and length.",
        )
        self.advanced_button = ttk.Button(
            modes, text="Advanced...", command=self.open_advanced
        )
        self.advanced_button.pack(side="right", padx=(0, 6))
        self._tip(
            self.advanced_button,
            "Open retrieval, transcript, account, and output settings.",
        )

        self._build_reply_face(left)

        presets = ttk.LabelFrame(left, text="Writing preset")
        presets.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        presets.columnconfigure(0, weight=1)
        self.preset_box = ttk.Combobox(
            presets,
            textvariable=self.preset_name,
            state="readonly",
            values=self._preset_names(),
            width=23,
        )
        self.preset_box.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.preset_box.bind(
            "<<ComboboxSelected>>", lambda _event: self.apply_selected_preset()
        )
        self.save_preset_button = ttk.Button(
            presets, text="Save preset...", command=self.save_current_preset,
        )
        self.save_preset_button.grid(
            row=0, column=1, padx=(4, 0), pady=4
        )
        self.delete_preset_button = ttk.Button(
            presets, text="Delete", command=self.delete_selected_preset,
        )
        self.delete_preset_button.grid(
            row=0, column=2, padx=(4, 4), pady=4
        )
        self._tip(
            self.preset_box,
            lambda: (
                f"{self._selected_preset_help()} Selecting it immediately "
                "changes the approaches, writing choices, and length."
            ),
        )
        self._tip(
            self.save_preset_button,
            "Save the approaches, writing choices, and length currently shown.",
        )
        self._tip(
            self.delete_preset_button,
            "Delete the selected custom preset. Built-in presets are protected.",
        )

        approaches = ttk.LabelFrame(left, text="Registers and approaches")
        approaches.grid(row=3, column=0, sticky="ew")
        approaches.columnconfigure(0, weight=1)
        search = ttk.Frame(approaches)
        search.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text="Find:").grid(row=0, column=0, sticky="w")
        self.approach_search = ttk.Entry(
            search, textvariable=self.approach_filter
        )
        self.approach_search.grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )
        self._tip(
            self.approach_search,
            "Filter the approach list by name, category, or description.",
        )
        self.approach_filter.trace_add(
            "write", lambda *_args: self._render_approaches()
        )
        canvas_frame = ttk.Frame(approaches)
        canvas_frame.grid(row=1, column=0, sticky="ew", padx=4, pady=(4, 0))
        canvas_frame.columnconfigure(0, weight=1)
        self.approach_canvas = tk.Canvas(
            canvas_frame,
            height=190,
            highlightthickness=0,
            width=400,
            yscrollincrement=20,
        )
        approach_scroll = ttk.Scrollbar(
            canvas_frame, orient="vertical", command=self.approach_canvas.yview
        )
        self.approach_canvas.configure(yscrollcommand=approach_scroll.set)
        self.approach_canvas.grid(row=0, column=0, sticky="ew")
        self._bind_approach_wheel(self.approach_canvas)
        self._bind_approach_wheel(approaches)
        self._bind_approach_wheel(canvas_frame)
        self._bind_approach_wheel(approach_scroll)
        approach_scroll.grid(row=0, column=1, sticky="ns")
        self.approach_frame = ttk.Frame(self.approach_canvas)
        self._bind_approach_wheel(self.approach_frame)
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
        ).grid(row=2, column=0, sticky="ew", padx=4, pady=(2, 0))
        summary_buttons = ttk.Frame(approaches)
        summary_buttons.grid(row=3, column=0, sticky="ew", padx=4, pady=(2, 0))
        self.clear_approaches_button = ttk.Button(
            summary_buttons, text="Clear selections",
            command=self.clear_custom_approaches,
        )
        self.clear_approaches_button.pack(side="left")
        self._tip(
            self.clear_approaches_button,
            "Clear every checked approach and return to the default set.",
        )
        ttk.Label(
            approaches, textvariable=self.resolution_summary,
            foreground="#805000", wraplength=LEFT_WIDTH - 30, justify="left",
        ).grid(row=4, column=0, sticky="ew", padx=4, pady=(2, 4))

        dials = ttk.LabelFrame(left, text="How the answer is written")
        dials.grid(row=4, column=0, sticky="ew", pady=(8, 0))
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
        length.grid(row=5, column=0, sticky="ew", pady=(8, 0))
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
            "<KeyRelease>", lambda _e: (
                self._mark_current_preset(), self.refresh()
            )
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

        return left

    def _build_reply_face(self, left: ttk.Frame) -> None:
        """The old application's reply tab, on the reply mode of this window.

        Same layout the operator worked with for a year: username on the
        face, the numbered do-these-in-order buttons, the recovery row, the
        two automation checkboxes, and the manual controls. Every button
        drives the guided session machinery that already runs this flow; the
        panel adds no second implementation of any rule.
        """

        face = ttk.Frame(left)
        face.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        face.columnconfigure(0, weight=1)
        self.reply_face = face

        handle_row = ttk.Frame(face)
        handle_row.grid(row=0, column=0, sticky="ew")
        handle_row.columnconfigure(1, weight=1)
        ttk.Label(handle_row, text="Your @username:").grid(
            row=0, column=0, sticky="w")
        self.my_handle_var = tk.StringVar(
            value=str(getattr(self.options, "my_handle", "") or ""))
        self.my_handle_var.trace_add(
            "write",
            lambda *_args: setattr(
                self.options, "my_handle", self.my_handle_var.get().strip()
            ),
        )
        self.my_handle_entry = ttk.Entry(
            handle_row, textvariable=self.my_handle_var)
        self.my_handle_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ttk.Label(
            face,
            text="for example @goss4444 - how the script knows which "
                 "comments are yours",
            foreground="#666666",
        ).grid(row=1, column=0, sticky="w", pady=(0, 4))

        steps = ttk.LabelFrame(face, text="Do these in order")
        steps.grid(row=2, column=0, sticky="ew")
        steps.columnconfigure(2, weight=1)
        self.reply_step_markers: list[ttk.Label] = []
        self.reply_step_buttons: dict[str, ttk.Button] = {}

        def step_row(row: int, number: str) -> ttk.Frame:
            marker = ttk.Label(steps, text=" ", width=2)
            marker.grid(row=row, column=0, sticky="w", padx=(4, 0))
            self.reply_step_markers.append(marker)
            ttk.Label(steps, text=number, width=3).grid(
                row=row, column=1, sticky="w")
            holder = ttk.Frame(steps)
            holder.grid(row=row, column=2, sticky="ew", pady=1)
            return holder

        def step_button(holder, key, text, command, tip):
            button = ttk.Button(holder, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self.reply_step_buttons[key] = button
            self._tip(button, tip)

        one = step_row(0, "1.")
        step_button(
            one, "build", "Build and find who needs a reply",
            self.build_packet,
            "Scan this video for your comments and everyone still owed a "
            "reply, then prepare the triage template.",
        )
        two = step_row(1, "2.")
        step_button(
            two, "copy_triage", "Copy triage template", self.do_copy,
            "Copy the triage packet asking which people are worth answering.",
        )
        step_button(
            two, "paste_triage", "Paste GPT answer from the triage template",
            self.take_triage,
            "Take the triage answer from the box or the clipboard and narrow "
            "the queue to the people it chose.",
        )
        three = step_row(2, "3.")
        step_button(
            three, "copy_reply", "Copy reply template", self.do_copy,
            "Copy this thread's reply packet. One packet now covers every "
            "response in the thread.",
        )
        step_button(
            three, "paste_reply", "Paste GPT answer for each person",
            self.take_answer,
            "Take the reply sheet from the box or the clipboard. One paste "
            "carries the reply for every person in the thread.",
        )
        four = step_row(3, "4.")
        step_button(
            four, "open_finished", "Open the finished replies",
            self._open_finished_replies,
            "Open the saved file of paste-ready replies. Nothing is posted.",
        )

        self.reply_face_hint = tk.StringVar(value="Press 1 to begin.")
        ttk.Label(steps, textvariable=self.reply_face_hint).grid(
            row=4, column=0, columnspan=3, sticky="w", padx=4, pady=(4, 2))

        recovery = ttk.Frame(steps)
        recovery.grid(row=5, column=0, columnspan=3, sticky="ew", padx=2,
                      pady=(0, 4))
        step_button(
            recovery, "skip", "Skip this person", self.skip,
            "Skip the current thread without saving a reply.",
        )
        step_button(
            recovery, "start_over", "Start over", self.reset_all,
            "Return the whole window to its opening state.",
        )
        step_button(
            recovery, "open_so_far", "Open replies so far",
            self._open_finished_replies,
            "Open what has been accepted so far. Nothing is posted.",
        )
        step_button(
            recovery, "open_packet", "Open this person's packet",
            self._open_person_packet,
            "Show the packet for the thread in front of you.",
        )

        # No automation checkboxes. Wired 2026-08-13 and removed the same
        # day at the operator's direction: nothing advances a step without a
        # press. The clipboard still auto-captures a video link into an
        # empty slot, and a built packet still lands on the clipboard by
        # itself — those are fills, not advances.
        manual = ttk.LabelFrame(
            face, text="Manual controls, not needed for the steps above")
        manual.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        manual.columnconfigure(1, weight=1)

        ttk.Label(manual, text="Answer one person:").grid(
            row=0, column=0, sticky="w", padx=4)
        self.answer_one_var = tk.StringVar()
        answer_one = ttk.Entry(manual, textvariable=self.answer_one_var)
        answer_one.grid(row=0, column=1, columnspan=3, sticky="ew",
                        padx=(4, 4), pady=2)
        self._tip(answer_one, "Type a handle, then press step 1: the run "
                              "goes straight to that person's thread.")

        find_button = ttk.Button(
            manual, text="Find who needs a reply", command=self.build_packet)
        find_button.grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.reply_step_buttons["find"] = find_button
        self._tip(find_button, "The same scan as step 1.")
        self.reply_people_box = ttk.Combobox(manual, state="readonly")
        self.reply_people_box.grid(row=1, column=1, columnspan=3,
                                   sticky="ew", padx=(4, 4), pady=2)
        self.reply_people_box.bind(
            "<<ComboboxSelected>>", self._person_chosen_from_list)
        self._tip(self.reply_people_box,
                  "Everyone the scan found waiting. Choosing somebody fills "
                  "Answer one person for the next step 1.")

        ttk.Label(manual, text="Only replies since:").grid(
            row=2, column=0, sticky="w", padx=4)
        self.since_var = tk.StringVar(
            value=str(getattr(self.options, "since", "") or ""))
        self.since_var.trace_add(
            "write",
            lambda *_args: setattr(
                self.options, "since", self.since_var.get().strip()),
        )
        since_entry = ttk.Entry(manual, textvariable=self.since_var, width=8)
        since_entry.grid(row=2, column=1, sticky="w", padx=(4, 4), pady=2)
        self._tip(since_entry,
                  "A day count, an ISO date, or an ISO datetime.")

        ttk.Label(manual, text="Or top repliers:").grid(
            row=2, column=2, sticky="e")
        self.top_repliers_var = tk.StringVar(
            value=str(int(getattr(self.options, "top_repliers", 0) or 0)))

        def _store_top(*_args):
            try:
                self.options.top_repliers = max(
                    0, int(self.top_repliers_var.get() or 0))
            except ValueError:
                self.options.top_repliers = 0

        self.top_repliers_var.trace_add("write", _store_top)
        top_spin = ttk.Spinbox(manual, from_=0, to=99, width=4,
                               textvariable=self.top_repliers_var)
        top_spin.grid(row=2, column=3, sticky="w", padx=(4, 4))
        self._tip(top_spin,
                  "Keep only the N people whose message the room liked "
                  "most. 0 keeps everybody.")

        self.per_thread_var = tk.BooleanVar(
            value=bool(getattr(self.options, "per_thread", False)))
        per_thread = ttk.Checkbutton(
            manual,
            text="Also write a separate packet for each of my comments",
            variable=self.per_thread_var,
            command=lambda: setattr(
                self.options, "per_thread", self.per_thread_var.get()),
        )
        per_thread.grid(row=3, column=0, columnspan=4, sticky="w", padx=4)
        self._tip(per_thread,
                  "Include every thread of yours that drew a response, not "
                  "only the ones where somebody is still owed an answer.")

        self.include_answered_var = tk.BooleanVar(
            value=bool(getattr(self.options, "include_answered", False)))
        include_answered = ttk.Checkbutton(
            manual, text="Include people I already answered",
            variable=self.include_answered_var,
            command=lambda: setattr(
                self.options, "include_answered",
                self.include_answered_var.get()),
        )
        include_answered.grid(row=4, column=0, columnspan=4, sticky="w",
                              padx=4, pady=(0, 4))
        self._tip(include_answered,
                  "Step 1 also lists people whose replies you already "
                  "answered.")

        if self.mode.get() != "reply":
            face.grid_remove()

    def _refresh_reply_face(self, view: Any) -> None:
        face = getattr(self, "reply_face", None)
        if face is None:
            return
        step = self.sequence.step
        session = getattr(self, "session", None)
        building = self.job.running
        for index, marker in enumerate(self.reply_step_markers):
            entry = view.rail[index] if index < len(view.rail) else None
            if entry is None:
                marker.configure(text=" ")
            elif entry.current:
                marker.configure(text=">")
            elif entry.done:
                marker.configure(text="*")
            else:
                marker.configure(text=" ")
        buttons = self.reply_step_buttons
        self._enable(buttons["build"], not building)
        self._enable(buttons["find"], not building)
        at_triage = session is not None and step is Step.TRIAGE
        at_people = session is not None and step is Step.PEOPLE
        self._enable(buttons["copy_triage"], at_triage)
        self._enable(buttons["paste_triage"], at_triage)
        self._enable(buttons["copy_reply"], at_people)
        self._enable(buttons["paste_reply"], at_people)
        accepted = bool(session is not None and getattr(
            session, "accepted", ()))
        self._enable(buttons["open_finished"],
                     accepted or step is Step.FINISH)
        self._enable(buttons["open_so_far"], accepted)
        self._enable(buttons["skip"], view.can_skip)
        self._enable(buttons["start_over"], True)
        self._enable(buttons["open_packet"], bool(self.last_packet))
        self.reply_face_hint.set(view.progress or "Press 1 to begin.")

    def _show_what_they_said(self, targets: Any) -> None:
        """Fill the panel from the packet's own targets.

        Read from the targets rather than re-derived from the thread: the
        panel must show exactly who the packet answers, or it becomes a
        second opinion about the queue.
        """

        widget = getattr(self, "their_text", None)
        if widget is None:
            return
        lines = []
        for target in targets or ():
            body = " ".join(str(getattr(target, "text", "")).split())
            lines.append(
                f"{target.response_number}. "
                f"{getattr(target, 'author_display_name', '')} "
                f"({getattr(target, 'relationship', '')}, "
                f"{getattr(target, 'like_count', 0):,} likes)\n"
                f"   {body[:240]}"
            )
        self._set_text(
            widget,
            "\n\n".join(lines) or "This thread has no responses to answer.",
        )

    def _open_finished_replies(self) -> None:
        session = getattr(self, "session", None)
        if session is None:
            self.say("Nothing has been built yet. Press 1 to begin.")
            return
        # The session names its own review file; this window only opens
        # what it is handed, falling back to the run folder.
        path_of = getattr(session, "review_path", None)
        review = path_of() if callable(path_of) else ""
        target = (review if review and os.path.isfile(review)
                  else str(getattr(session.artifacts, "root", "") or ""))
        if not target:
            self.say("No replies have been saved yet.")
            return
        message = self._open_path(target)
        if message:
            self.say(message)

    def _open_person_packet(self) -> None:
        if not self.last_packet:
            self.say("No packet has been built yet. Press 1 to begin.")
            return
        self._set_text(self.packet_preview, self.last_packet)
        self.output_tabs.select(self.packet_tab)

    def _person_chosen_from_list(self, _event=None) -> None:
        chosen = self.reply_people_box.get().strip()
        if not chosen:
            return
        self.answer_one_var.set(chosen)
        self.say(f"Step 1 will go straight to {chosen}'s thread.")

    def _build_right(self, parent: ttk.Frame) -> ttk.Frame:
        right = ttk.Frame(parent)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.output_tabs = ttk.Notebook(right)
        self.output_tabs.grid(row=0, column=0, sticky="nsew")

        activity_tab = ttk.Frame(self.output_tabs, padding=PADDING)
        activity_tab.columnconfigure(0, weight=1)
        activity_tab.rowconfigure(1, weight=1)
        self.output_tabs.add(activity_tab, text="Activity")
        self.activity_tab = activity_tab
        ttk.Label(
            activity_tab,
            text=(
                "Retrieval and processing activity appears here, including "
                "comments, replies, transcript checks, and packet assembly."
            ),
            foreground="#444444",
            wraplength=700,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.log = tk.Text(
            activity_tab,
            wrap="word",
            state="disabled",
            background="#f6f6f6",
        )
        self.log.grid(row=1, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(
            activity_tab,
            orient="vertical",
            command=self.log.yview,
        )
        log_scroll.grid(row=1, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)
        self._add_text_context_menu(self.log)
        self._tip(
            self.log,
            "Build progress and retrieval details. Select text and right-click "
            "to copy it.",
        )

        self._add_evidence_tab(
            "metadata",
            "Metadata",
            "Video title, URL, channel, date, duration, and public counts.",
        )
        self._add_evidence_tab(
            "description",
            "Description",
            "The description published beneath the video.",
        )

        transcript_tab = ttk.Frame(self.output_tabs, padding=PADDING)
        transcript_tab.columnconfigure(0, weight=1)
        transcript_tab.rowconfigure(1, weight=1)
        self.output_tabs.add(transcript_tab, text="Transcript")
        self.transcript_tab = transcript_tab
        ttk.Label(
            transcript_tab,
            text=(
                "Published captions appear here after retrieval. During "
                "local Whisper transcription, completed segments appear "
                "here as they are created."
            ),
            foreground="#444444",
            wraplength=700,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.transcript_preview = tk.Text(
            transcript_tab,
            wrap="word",
            state="disabled",
            background="#f6f6f6",
        )
        self.transcript_preview.grid(row=1, column=0, sticky="nsew")
        transcript_scroll = ttk.Scrollbar(
            transcript_tab,
            orient="vertical",
            command=self.transcript_preview.yview,
        )
        transcript_scroll.grid(row=1, column=1, sticky="ns")
        self.transcript_preview.configure(
            yscrollcommand=transcript_scroll.set
        )
        self._add_text_context_menu(self.transcript_preview)
        self._tip(
            self.transcript_preview,
            "The retrieved or locally transcribed video transcript.",
        )
        self.evidence_views["transcript"] = self.transcript_preview
        transcript_actions = ttk.Frame(transcript_tab)
        transcript_actions.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        transcript_copy = ttk.Button(
            transcript_actions,
            text="Copy transcript",
            command=lambda: self.copy_evidence("transcript"),
            state="disabled",
        )
        transcript_copy.pack(side="left")
        self._tip(
            transcript_copy,
            "Copy the transcript shown in this tab.",
        )
        self.evidence_copy_buttons["transcript"] = transcript_copy
        self.transcript_api_button = ttk.Button(
            transcript_actions,
            text="1. Transcript API",
            command=lambda: self.build_from_transcript_route("api"),
            state="disabled",
        )
        self.transcript_api_button.pack(side="left", padx=(6, 0))
        self._tip(
            self.transcript_api_button,
            "Retry using YouTube's published transcript service only.",
        )
        self.ytdlp_captions_button = ttk.Button(
            transcript_actions,
            text="2. yt-dlp captions",
            command=lambda: self.build_from_transcript_route("ytdlp"),
            state="disabled",
        )
        self.ytdlp_captions_button.pack(side="left", padx=(6, 0))
        self._tip(
            self.ytdlp_captions_button,
            "Retry published captions using yt-dlp only.",
        )
        self.saved_transcript_button = ttk.Button(
            transcript_actions,
            text="3. Saved transcript",
            command=lambda: self.build_from_transcript_route("saved"),
            state="disabled",
        )
        self.saved_transcript_button.pack(side="left", padx=(6, 0))
        self._tip(
            self.saved_transcript_button,
            "Reuse a transcript already saved for this video.",
        )
        self.run_whisper_button = ttk.Button(
            transcript_actions,
            text="4. Whisper",
            command=lambda: self.build_from_transcript_route("whisper"),
            state="disabled",
        )
        self.run_whisper_button.pack(side="left", padx=(6, 0))
        self._tip(
            self.run_whisper_button,
            "Download the audio and create a local Whisper transcript within "
            "the limits set in Advanced.",
        )

        self._add_evidence_tab(
            "comments",
            "Comments",
            "All top-level comments retained by this retrieval.",
        )
        self._add_evidence_tab(
            "replies",
            "Replies",
            "All replies retained from the selected comment threads.",
        )
        self._add_evidence_tab(
            "debug",
            "Debug",
            "Before validation, this tab shows the diagnostic packet sent to "
            "the model. After validation, it shows the completed bundle with "
            "the model response and result. It includes retained commenter "
            "names and text. Review it before sharing it.",
        )

        packet_tab = ttk.Frame(self.output_tabs, padding=PADDING)
        packet_tab.columnconfigure(0, weight=1)
        packet_tab.rowconfigure(2, weight=1)
        self.output_tabs.add(packet_tab, text="Generated packet")
        self.packet_tab = packet_tab
        ttk.Label(
            packet_tab, text="The complete packet appears here after Build.",
            foreground="#444444",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.run_receipt_label = ttk.Label(
            packet_tab,
            textvariable=self.run_receipt,
            foreground="#444444",
            justify="left",
            wraplength=700,
        )
        self.run_receipt_label.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.packet_preview = tk.Text(
            packet_tab, wrap="word", state="disabled", background="#f6f6f6"
        )
        self.packet_preview.grid(row=2, column=0, sticky="nsew")
        self._add_text_context_menu(self.packet_preview)
        self._tip(
            self.packet_preview,
            "The ordinary generated packet. Debug instructions and results "
            "appear separately in the Debug tab.",
        )
        packet_actions = ttk.Frame(packet_tab)
        packet_actions.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.packet_copy_button = ttk.Button(
            packet_actions,
            text="Copy again",
            command=self.copy_generated_packet,
            state="disabled",
        )
        self.packet_copy_button.pack(side="left")
        self._tip(
            self.packet_copy_button,
            "Copy the generated packet to the clipboard again.",
        )
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
        self.answer_tab = card
        card.columnconfigure(0, weight=1)
        card.rowconfigure(4, weight=1)

        self.card_title = ttk.Label(card, text="", font=("TkDefaultFont", 10, "bold"))
        self.card_title.grid(row=0, column=0, sticky="w")
        self.card_detail = ttk.Label(card, text="", wraplength=460,
                                     justify="left", foreground="#444444")
        self.card_detail.grid(row=1, column=0, sticky="ew", pady=(4, 6))

        # What the thread actually said, so the operator can judge whether a
        # packet is worth spending without opening it. The legacy window had
        # this panel and the rebuild dropped it (spec M4).
        theirs = ttk.LabelFrame(card, text="What they said")
        theirs.grid(row=2, column=0, sticky="nsew", pady=(0, 6))
        theirs.columnconfigure(0, weight=1)
        self.their_text = tk.Text(
            theirs, height=5, width=35, wrap="word", state="disabled",
            relief="flat", background="#f6f6f6",
        )
        self.their_text.grid(row=0, column=0, sticky="nsew")
        self._add_text_context_menu(self.their_text)
        self._tip(
            self.their_text,
            "Every response this packet answers, newest last. Judge the "
            "thread from here rather than opening the packet.",
        )
        self._set_text(self.their_text, "No thread has been built yet.")

        saved = ttk.LabelFrame(card, text="Saved final draft")
        saved.grid(row=3, column=0, sticky="nsew", pady=(0, 6))
        saved.columnconfigure(0, weight=1)
        self.said = tk.Text(
            saved,
            height=4,
            width=35,
            wrap="word",
            state="disabled",
            relief="flat",
            background="#f6f6f6",
        )
        self.said.grid(row=0, column=0, sticky="nsew")
        self._add_text_context_menu(self.said)
        self._tip(
            self.said,
            "The final draft appears here after it passes validation and is saved.",
        )
        self._set_text(self.said, "No answer has been saved yet.")

        answer = ttk.LabelFrame(card, text="Model answer")
        answer.grid(row=4, column=0, sticky="nsew", pady=(0, 6))
        answer.columnconfigure(0, weight=1)
        answer.rowconfigure(0, weight=1)
        self.answer_input = tk.Text(
            answer, height=10, width=35, wrap="word", undo=True
        )
        self.answer_input.grid(row=0, column=0, sticky="nsew")
        answer_scroll = ttk.Scrollbar(
            answer, orient="vertical", command=self.answer_input.yview
        )
        answer_scroll.grid(row=0, column=1, sticky="ns")
        self.answer_input.configure(yscrollcommand=answer_scroll.set)
        self._add_text_context_menu(self.answer_input)
        self._tip(
            self.answer_input,
            "Paste the model's complete answer here, then click Validate and "
            "save answer.",
        )
        self.answer_input.bind("<KeyRelease>", lambda _event: self.refresh())
        self.answer_input.bind(
            "<Control-Return>", lambda _event: self.do_primary()
        )

        actions = ttk.Frame(card)
        actions.grid(row=5, column=0, sticky="ew")
        self.primary = ttk.Button(actions, text="", command=self.do_primary)
        self.primary.pack(side="left")
        self._tip(
            self.primary,
            "Check the complete model answer and save its Hardened final draft.",
        )
        self.paste_answer_button = ttk.Button(
            actions, text="Paste answer", command=self.paste_answer
        )
        self.paste_answer_button.pack(side="left", padx=(6, 0))
        self._tip(
            self.paste_answer_button,
            "Paste the clipboard into the model-answer box without saving it.",
        )
        self.copy_button = ttk.Button(actions, text="", command=self.do_copy,
                                      state="disabled")
        self.copy_button.pack(side="left", padx=(6, 0))
        self._tip(
            self.copy_button,
            "Copy the current packet to the clipboard again.",
        )
        self.record_button = ttk.Button(
            actions,
            text="Record as posted",
            command=self.record_posted,
            state="disabled",
        )
        self.record_button.pack(side="left", padx=(6, 0))
        self._tip(
            self.record_button,
            "After you manually post the saved draft on YouTube, record that "
            "fact in local history.",
        )
        self.cancel_button = self.stop_button

        footer = ttk.Frame(card)
        footer.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        self.back_button = ttk.Button(footer, text="Back", command=self.go_back)
        self.back_button.pack(side="left")
        self._tip(
            self.back_button,
            "Return to the previous person in a reply workflow.",
        )
        self.skip_button = ttk.Button(footer, text="Skip", command=self.skip)
        self.skip_button.pack(side="left", padx=(6, 0))
        self._tip(
            self.skip_button,
            "Skip the current person without saving a reply.",
        )
        self.progress_label = ttk.Label(footer, text="", foreground="#666666")
        self.progress_label.pack(side="right")
        self.packet_size_label = ttk.Label(
            footer, text="", foreground="#666666"
        )
        self.packet_size_label.pack(side="right", padx=(0, 12))
        return right

    def _add_text_context_menu(self, widget: tk.Text) -> None:
        self._text_context_menus.append(
            TextContextMenu(widget, self._write_selected_text)
        )

    def _write_selected_text(self, text: str) -> None:
        if self.clipboard is None:
            self.say("No clipboard service is available.")
            return
        self.clipboard.write(text)

    def _add_evidence_tab(
        self,
        key: str,
        title: str,
        description: str,
    ) -> ttk.Frame:
        tab = ttk.Frame(self.output_tabs, padding=PADDING)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        self.output_tabs.add(tab, text=title)
        ttk.Label(
            tab,
            text=description,
            foreground="#444444",
            wraplength=700,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        view = tk.Text(
            tab,
            wrap="word",
            state="disabled",
            background="#f6f6f6",
        )
        view.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(tab, orient="vertical", command=view.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        view.configure(yscrollcommand=scroll.set)
        self._add_text_context_menu(view)
        self._tip(
            view,
            f"The retrieved {title.lower()} for the selected video.",
        )
        actions = ttk.Frame(tab)
        actions.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        button = ttk.Button(
            actions,
            text=f"Copy {title.lower()}",
            command=lambda name=key: self.copy_evidence(name),
            state="disabled",
        )
        button.pack(side="left")
        self._tip(
            button,
            f"Copy the {title.lower()} shown in this tab.",
        )
        self.evidence_tabs[key] = tab
        self.evidence_views[key] = view
        self.evidence_copy_buttons[key] = button
        return tab

    def _build_bottom(self) -> None:
        bottom = ttk.Frame(self.root, padding=(PADDING, 4, PADDING, PADDING))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(1, weight=1)
        bottom.columnconfigure(3, weight=2)

        self.transcript_indicator = ttk.Label(
            bottom,
            text="●",
            foreground="#777777",
            font=("TkDefaultFont", 11, "bold"),
        )
        self.transcript_indicator.grid(row=0, column=0, sticky="w")
        self.transcript_notice_label = ttk.Label(
            bottom,
            textvariable=self.transcript_notice,
            justify="left",
            wraplength=400,
        )
        self.transcript_notice_label.grid(
            row=0, column=1, sticky="ew", padx=(3, 10)
        )
        self._tip(
            self.transcript_indicator,
            "Green means a transcript is ready, yellow means Whisper is "
            "working, red means no transcript is available, and gray means "
            "it has not been checked.",
        )
        self._tip(
            self.transcript_notice_label,
            lambda: self.transcript_notice.get(),
        )

        self.progress_caption = ttk.Label(bottom, text="Progress:")
        self.progress_caption.grid(
            row=0, column=2, sticky="w"
        )
        self.progress_bar = ttk.Progressbar(
            bottom,
            orient="horizontal",
            mode="determinate",
            maximum=1.0,
            variable=self.progress_value,
        )
        self.progress_bar.grid(
            row=0, column=3, sticky="ew", padx=(8, 8)
        )
        self.status_label = ttk.Label(bottom, textvariable=self.status)
        self.status_label.grid(row=0, column=4, sticky="e")
        self._tip(
            self.progress_bar,
            "Estimated progress for the active retrieval or transcription.",
        )
        self._tip(
            self.status_label,
            lambda: self.status.get(),
        )

    # -- state -------------------------------------------------------------

    def _set_transcript_status(self, state: str, message: str) -> None:
        colors = {
            "ready": "#16833b",
            "missing": "#b42318",
            "working": "#b77900",
            "unknown": "#777777",
        }
        self.transcript_indicator.configure(
            foreground=colors.get(state, colors["unknown"])
        )
        self.transcript_notice.set(message)

    def _clear_transcript_preview(self) -> None:
        self._set_evidence_view("transcript", "")

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _set_evidence_view(self, key: str, text: str) -> None:
        view = self.evidence_views.get(key)
        if view is None:
            return
        view.configure(state="normal")
        view.delete("1.0", "end")
        if text:
            view.insert("1.0", text)
        view.configure(state="disabled")
        button = self.evidence_copy_buttons.get(key)
        if button is not None:
            button.configure(state=("normal" if text else "disabled"))

    def _set_debug_view(self, text: str, *, complete: bool) -> None:
        """Show whether Debug contains the outgoing packet or final bundle."""

        tab = self.evidence_tabs.get("debug")
        if tab is not None:
            self.output_tabs.tab(
                tab,
                text="Debug bundle" if complete else "Debug packet",
            )
        button = self.evidence_copy_buttons.get("debug")
        if button is not None:
            button.configure(
                text="Copy debug bundle" if complete else "Copy debug packet"
            )
        self._set_evidence_view("debug", text)

    def _clear_evidence_views(self) -> None:
        for key in tuple(self.evidence_views):
            self._set_evidence_view(key, "")
        tab = self.evidence_tabs.get("debug")
        if tab is not None:
            self.output_tabs.tab(tab, text="Debug")
        button = self.evidence_copy_buttons.get("debug")
        if button is not None:
            button.configure(text="Copy debug")

    def _show_evidence(self, evidence: Any) -> None:
        evidence = evidence if isinstance(evidence, dict) else {}
        video = evidence.get("video")
        video = video if isinstance(video, dict) else {}
        comments = evidence.get("comments")
        comments = comments if isinstance(comments, (list, tuple)) else ()
        replies = evidence.get("replies")
        replies = replies if isinstance(replies, (list, tuple)) else ()
        self._set_evidence_view("metadata", metadata_text(video))
        self._set_evidence_view("description", description_text(video))
        self._set_evidence_view("comments", comments_text(comments))
        self._set_evidence_view("replies", replies_text(replies))

    def copy_evidence(self, key: str) -> None:
        view = self.evidence_views.get(key)
        if view is None:
            return
        text = view.get("1.0", "end-1c")
        if not text:
            self.say(f"No {key} is available to copy.")
            return
        try:
            if self.clipboard is None:
                raise RuntimeError("no clipboard service is available")
            self.clipboard.write(text)
        except Exception as failure:        # noqa: BLE001 - visible copy error
            self.say(f"Could not copy {key}: {failure}")
            return
        self.say(f"Copied {key}: {len(text):,} characters.")

    def _append_transcript_entry(self, entry: dict[str, Any]) -> None:
        text = " ".join(str(entry.get("text") or "").split())
        if not text:
            return
        line = f"[{format_timestamp(entry.get('start'))}] {text}\n"
        self.transcript_preview.configure(state="normal")
        self.transcript_preview.insert("end", line)
        self.transcript_preview.see("end")
        self.transcript_preview.configure(state="disabled")
        self.evidence_copy_buttons["transcript"].configure(state="normal")

    def _show_transcript(self, transcript: Any) -> None:
        self._clear_transcript_preview()
        if isinstance(transcript, dict):
            entries = tuple(transcript.get("entries_data", ()) or ())
            available = transcript.get("availability") == "available"
        else:
            entries = tuple(getattr(transcript, "entries", ()) or ())
            available = bool(getattr(transcript, "available", False))
        for entry in entries:
            self._append_transcript_entry(dict(entry))
        notice = transcript_notification(transcript)
        self._set_transcript_status(
            "ready" if available else "missing",
            notice,
        )
        if not entries:
            self.transcript_preview.configure(state="normal")
            self.transcript_preview.insert("1.0", notice)
            self.transcript_preview.configure(state="disabled")

    @staticmethod
    def _eta_text(seconds: Any) -> str:
        try:
            remaining = max(0, int(float(seconds)))
        except (TypeError, ValueError):
            return "estimating time remaining"
        hours, remainder = divmod(remaining, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"about {hours:d}:{minutes:02d}:{secs:02d} remaining"
        return f"about {minutes:d}:{secs:02d} remaining"

    def _reload_presets(self) -> None:
        presets = (
            tuple(self._preset_store.all())
            if self._preset_store is not None
            else BUILT_IN_PRESETS
        )
        self._presets = {preset.name: preset for preset in presets}
        if hasattr(self, "preset_box"):
            self.preset_box.configure(values=self._preset_names())

    def _preset_names(self) -> tuple[str, ...]:
        return (CURRENT_PRESET,) + tuple(self._presets)

    def _selected_preset_help(self) -> str:
        preset = self._presets.get(self.preset_name.get())
        return preset.description if preset is not None else (
            "The writing choices currently shown."
        )

    def _mark_current_preset(self) -> None:
        if hasattr(self, "preset_name"):
            self.preset_name.set(CURRENT_PRESET)

    def apply_selected_preset(self) -> None:
        selected = self.preset_name.get()
        preset = self._presets.get(selected)
        if preset is None:
            return
        # Capture the video and other fields before replacing the model.
        self.gather()
        self.options = self.options.apply_writing_preset(preset)
        self.length.set(self.options.length)
        self.custom_length.set(self.options.custom_length)
        for name, box in self.dial_boxes.items():
            box.set(dial_choice_label(self.options.dial_values()[name]))
        self._fill_approaches()
        self.preset_name.set(preset.name)
        count = len(self.options.registers_for(self.mode.get()))
        noun = "approach" if count == 1 else "approaches"
        self.say(f"Applied preset: {preset.name} ({count} {noun}).")
        self.refresh()

    def save_current_preset(self) -> None:
        if self._preset_store is None:
            self.say("Custom preset storage is not available.")
            return
        name = self._ask_preset_name()
        if name is None:
            return
        try:
            preset = self.gather().as_writing_preset(name)
            saved = self._preset_store.save(preset)
        except Exception as failure:        # noqa: BLE001 - visible refusal
            self.say(f"Preset was not saved: {failure}")
            return
        self._reload_presets()
        self.preset_name.set(saved.name)
        self.say(f"Saved custom preset: {saved.name}.")
        self.refresh()

    def delete_selected_preset(self) -> None:
        selected = self.preset_name.get()
        preset = self._presets.get(selected)
        if preset is None:
            self.say("Choose a custom preset to delete.")
            return
        if preset.builtin:
            self.say("Built-in presets cannot be deleted.")
            return
        if self._preset_store is None or not self._confirm_delete_preset(
            preset.name
        ):
            return
        try:
            deleted = self._preset_store.delete(preset.name)
        except Exception as failure:        # noqa: BLE001 - visible refusal
            self.say(f"Preset was not deleted: {failure}")
            return
        if deleted:
            self._reload_presets()
            self.preset_name.set(CURRENT_PRESET)
            self.say(f"Deleted custom preset: {preset.name}.")
        self.refresh()

    def _fill_approaches(self) -> None:
        """Replace the mode's variables, then render the current filter."""

        mode = self.mode.get()
        selected = set(
            self.options.reply_variations if mode == "reply"
            else self.options.comment_variations
        )
        self.approach_vars = {
            key: tk.BooleanVar(value=key in selected)
            for key, _label, _dimension, _description in approach_choices(mode)
        }
        self.approach_mode.set("custom" if selected else "default")
        self._render_approaches()
        self._apply_resolved_approaches()
        self._update_approach_state()

    def _render_approaches(self) -> None:
        """Render matching choices without dropping hidden selections."""

        if not hasattr(self, "approach_frame"):
            return
        for tooltip in self._approach_tooltips:
            tooltip.destroy()
        self._approach_tooltips = []
        for child in self.approach_frame.winfo_children():
            child.destroy()
        self.approach_checks = {}
        mode = self.mode.get()
        wanted = self.approach_filter.get().strip().casefold()
        row = 0
        last_dimension = ""
        for key, label, dimension, description in approach_choices(mode):
            searchable = f"{key} {label} {dimension} {description}".casefold()
            if wanted and wanted not in searchable:
                continue
            if dimension != last_dimension:
                dimension_label = ttk.Label(
                    self.approach_frame,
                    text=dimension.title(),
                    foreground="#555555",
                )
                dimension_label.grid(
                    row=row, column=0, sticky="w", padx=2, pady=(5, 1)
                )
                self._bind_approach_wheel(dimension_label)
                row += 1
                last_dimension = dimension
            variable = self.approach_vars[key]
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
            self._bind_approach_wheel(check)
            self._approach_tooltips.append(
                Tooltip(check, lambda value=help_text: value))
            self.approach_checks[key] = check
            row += 1
        if not self.approach_checks:
            empty_label = ttk.Label(
                self.approach_frame,
                text="No approaches match that search.",
                foreground="#666666",
            )
            empty_label.grid(row=0, column=0, sticky="w", padx=2, pady=6)
            self._bind_approach_wheel(empty_label)
        self.approach_canvas.yview_moveto(0)

    def _bind_approach_wheel(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._scroll_approaches, add="+")
        widget.bind("<Button-4>", self._scroll_approaches, add="+")
        widget.bind("<Button-5>", self._scroll_approaches, add="+")

    def _scroll_approaches(self, event) -> str:
        delta = int(getattr(event, "delta", 0) or 0)
        number = int(getattr(event, "num", 0) or 0)
        if delta > 0 or number == 4:
            direction = -1
        elif delta < 0 or number == 5:
            direction = 1
        else:
            return "break"
        self.approach_canvas.yview_scroll(direction * 3, "units")
        return "break"
        self._apply_resolved_approaches()
        self._update_approach_state()

    def _mode_changed(self) -> None:
        old_mode = self._display_mode
        self._store_approaches(old_mode)
        self._display_mode = self.mode.get()
        self._fill_approaches()
        face = getattr(self, "reply_face", None)
        if face is not None:
            if self.mode.get() == "reply":
                face.grid()
            else:
                face.grid_remove()
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
        self._mark_current_preset()
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
        total = len(self.approach_vars)
        if count == 0:
            summary = "No approaches selected — defaults will be used."
        elif count == total:
            summary = f"All {total} approaches selected."
        else:
            summary = f"{count} of {total} approaches selected."
        self.approach_summary.set(summary)
        self._apply_resolved_approaches()

    def clear_custom_approaches(self) -> None:
        self._mark_current_preset()
        for variable in self.approach_vars.values():
            variable.set(False)
        self._store_approaches()
        self._update_approach_state()
        self.refresh()

    def use_default_approaches(self) -> None:
        self._mark_current_preset()
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
        self._mark_current_preset()
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
        self._mark_current_preset()
        self.refresh()

    def gather(self) -> PacketOptionsModel:
        """Read the widgets back into the model. One direction, one place."""

        self.options.video = self.video.get().strip()
        self.options.length = self.length.get()
        self.options.custom_length = self.custom_length.get()
        self.options.debug_build = bool(self.debug_build.get())
        self._store_approaches()
        return self.options

    @staticmethod
    def _build_signature(options: PacketOptionsModel, mode: str) -> str:
        """The inputs that make one packet distinct from another."""

        return json.dumps(
            {"mode": mode, "options": vars(options)},
            sort_keys=True,
            default=str,
        )

    def refresh(self) -> None:
        options = self.gather()
        signature = self._build_signature(options, self.mode.get())
        blockers = options.problems(mode=self.mode.get())
        typed_answer = self._answer_text()
        if hasattr(self, "delete_preset_button"):
            selected_preset = self._presets.get(self.preset_name.get())
            self._enable(
                self.delete_preset_button,
                bool(selected_preset and not selected_preset.builtin),
            )
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
        preview_packet = self.generated_packet or self.last_packet
        self.packet_preview.configure(state="normal")
        self.packet_preview.delete("1.0", "end")
        self.packet_preview.insert(
            "1.0", preview_packet or "Build a packet first."
        )
        self.packet_preview.configure(state="disabled")
        self.packet_count.configure(
            text=(f"{len(preview_packet):,} characters"
                  if preview_packet else "")
        )
        self._enable(self.packet_copy_button, bool(preview_packet))
        self.output_tabs.tab(
            self.answer_tab,
            state=("normal" if self.last_packet else "disabled"),
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
            if self.sequence.step is Step.TRIAGE:
                self.primary.configure(text="Use selected people")
            elif self.sequence.step is Step.PEOPLE:
                self.primary.configure(text="Validate and save reply")
            self.copy_button.configure(
                text=(
                    "Copy packet again"
                    if self.last_packet
                    else (view.copy_label or "Copy packet")
                )
            )
            self.progress_label.configure(text=view.progress)
            self._enable(self.back_button, view.can_go_back)
            self._enable(self.skip_button, view.can_skip)
            self._refresh_reply_face(view)
        else:
            waiting = getattr(self, "comment_session", None) is not None
            saved = bool(
                waiting
                and getattr(self.comment_session, "accepted", ())
            )
            offer = getattr(self, "_offer", None)
            self.card_title.configure(
                text=("Answer saved" if saved else
                      "Paste the model answer, then save it" if waiting
                      else "Build a comment packet"))
            self.card_detail.configure(
                text=("The final draft is shown below. Nothing was posted. "
                      "Use Record as posted only after you post it yourself."
                      if saved else
                      "1. Paste the complete model answer into the box. "
                      "2. Click Validate and save answer. The Hardened final "
                      "will appear above after it is saved; nothing is posted."
                      if waiting else
                      "Builds from this video's transcript and comment "
                      "section. The packet lands on your clipboard.")
            )
            self.primary.configure(
                text=("Validate and save answer" if waiting else "Build")
            )
            self.copy_button.configure(
                text=(
                    "Copy packet again" if self.last_packet else "Copy packet"
                )
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
        can_retry_transcript = (
            has_video and not self.job.running and not blockers
        )
        for button in (
            self.transcript_api_button,
            self.ytdlp_captions_button,
            self.saved_transcript_button,
            self.run_whisper_button,
        ):
            self._enable(button, can_retry_transcript)
        # Once a packet exists the button means "take the answer", and that
        # is dead until the clipboard actually holds one.
        if self.mode.get() == "comment" and \
                getattr(self, "comment_session", None) is not None:
            inputs_changed = bool(
                self._completed_build_signature
                and signature != self._completed_build_signature
            )
            offer = getattr(self, "_offer", None)
            self._enable(self.primary,
                         not saved and bool(typed_answer or (
                             offer is not None and offer.offered
                         )))
            self._enable(self.copy_button, bool(self.last_packet))
            self._enable(
                self.record_button,
                self._record_available(self.comment_session),
            )
            self._update_record_button(self.comment_session)
            can_stop = self.job.running and not self.job.cancelled
            self._enable(self.cancel_button, can_stop)
            self._enable(self.stop_button, can_stop)
            self._enable(
                self.build_button,
                inputs_changed and not self.job.running and not blockers,
            )
            self.status.set(
                "Video or settings changed. Build a new packet when ready."
                if inputs_changed
                else (self._message or "Packet built and copied.")
            )
            return

        self._enable(
            self.primary,
            has_video and not self.job.running and not blockers,
        )
        if (
            reply_mode
            and getattr(self, "session", None) is not None
            and self.sequence.step in (Step.TRIAGE, Step.PEOPLE)
        ):
            offer = getattr(self, "_offer", None)
            self._enable(
                self.primary,
                bool(typed_answer or (offer is not None and offer.offered)),
            )
        self._enable(
            self.build_button,
            has_video and not self.job.running and not blockers,
        )
        self._enable(self.copy_button, bool(self.last_packet))
        active_session = (
            getattr(self, "session", None) if self.mode.get() == "reply"
            else getattr(self, "comment_session", None)
        )
        self._enable(
            self.record_button,
            self._record_available(active_session),
        )
        self._update_record_button(active_session)
        can_stop = self.job.running and not self.job.cancelled
        self._enable(self.cancel_button, can_stop)
        self._enable(self.stop_button, can_stop)

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
        if offer is None:
            return
        if offer.holding.name == "VIDEO":
            if not offer.payload:
                return
            self._suppressed_clipboard_video = ""
            self.video.set(offer.payload)
            self.video_url.set(watch_url(offer.payload))
        elif offer.offered:
            self.say(f"Took an answer of {len(offer.payload):,} characters.")
        else:
            return
        self.refresh()

    def _answer_text(self) -> str:
        if not hasattr(self, "answer_input"):
            return ""
        return self.answer_input.get("1.0", "end-1c").strip()

    def _clear_answer(self) -> None:
        if hasattr(self, "answer_input"):
            self.answer_input.delete("1.0", "end")

    def _show_saved_draft(self, text: str = "") -> None:
        if hasattr(self, "said"):
            self._set_text(
                self.said,
                text or "No answer has been saved yet.",
            )

    def _show_refusal(self, reason: str) -> None:
        """Put a refused answer's reason where the operator is looking.

        A refusal used to go only to the status bar along the bottom edge,
        while this panel kept saying "No answer has been saved yet." Both
        statements were true and the combination read as a dead button: the
        one place that reports the outcome of pressing it said nothing had
        happened, and the explanation sat in the least prominent strip of the
        window. Validation was working and being reported, and the report was
        still missed.
        """

        if hasattr(self, "said"):
            self._set_text(
                self.said,
                "Not saved. " + (reason or "That paste could not be used."),
            )

    def paste_answer(self) -> None:
        """Paste explicitly into the visible answer field."""

        text = self.read_clipboard().strip()
        if not text:
            self.say("The clipboard is empty.")
            return
        self.answer_input.delete("1.0", "end")
        self.answer_input.insert("1.0", text)
        self.say(
            f"Pasted {len(text):,} characters. "
            "Click Validate and save answer."
        )
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
        self.clip_label.set("Clipboard: not read yet")
        self.comment_session = None
        self.session = None
        self.sequence = ReplySequence()
        self.result = None
        self.triage_packet = ""
        self.current_packet = ""
        self.generated_packet = ""
        self.last_packet = ""
        self._pending_build_signature = ""
        self._completed_build_signature = ""
        self.run_receipt.set("")
        self._set_transcript_status("unknown", "Transcript not checked yet.")
        self._clear_evidence_views()
        self._clear_answer()
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

        self.build_packet()

    def build_packet(self) -> None:
        """Build from the current video/settings, even if an older packet exists."""

        self._start_packet_build(copy.deepcopy(self.gather()))

    def build_from_transcript_route(self, route: str) -> None:
        """Build using exactly one manually selected transcript source."""

        options = copy.deepcopy(self.gather())
        options.transcript_route = route
        options.whisper_policy = (
            "automatic" if route == "whisper" else "ignore"
        )
        options.transcribe_locally = route == "whisper"
        self._start_packet_build(options, force=True)

    def _start_packet_build(
        self,
        options: PacketOptionsModel,
        *,
        force: bool = False,
    ) -> None:
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
        signature = self._build_signature(options, mode)
        if (
            not force
            and
            getattr(self, "comment_session", None) is not None
            and signature == self._completed_build_signature
        ):
            self.say("This packet already matches the current video and settings.")
            return
        snapshot = copy.deepcopy(options)
        snapshot._activity_preset = self.preset_name.get()
        started = self.job.start(
            lambda job: self._build_packet(snapshot, mode, job)
        )
        if not started:
            self.say("A build is already running.")
        else:
            self._active_job_generation = self.job.generation
            self._pending_build_signature = signature
            self._live_transcript_started = False
            self._clear_evidence_views()
            self._set_transcript_status(
                "working",
                "Checking available transcript sources.",
            )
            self.output_tabs.select(self.activity_tab)
        self.refresh()

    def take_answer(self) -> None:
        """Hand the visible or clipboard answer to the session.

        The session decides whether it is an answer at all — packet detection
        before extraction, the same order everywhere — so a refusal here is
        the product working and is shown rather than swallowed.
        """

        session = getattr(self, "session", None)
        offer = getattr(self, "_offer", None)
        typed = self._answer_text()
        if session is None:
            return
        if not typed and (offer is None or not offer.offered):
            self.say("Paste an answer into the box or copy one to the clipboard.")
            return

        try:
            # The raw clipboard, not the extracted draft. The session owns
            # what counts as an answer; handing it an already-extracted one
            # made it extract a second time from text whose heading had gone.
            result = session.submit(typed or offer.raw)
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
            if getattr(session, "debug_build", False):
                self._set_debug_view(session.debug_bundle(), complete=True)
            reason = session.state.last_error or "That paste could not be used."
            self.say(reason)
            self._show_refusal(reason)
            self.refresh()
            return

        self.sequence.accepted = len(session.accepted)
        batch = len(getattr(session, "current_targets", ()) or ()) or 1
        drafts = list(session.accepted)[-batch:]
        if drafts:
            self._show_saved_draft("\n\n----\n\n".join(
                f"{getattr(d, 'author', '')}:\n{getattr(d, 'draft', '')}"
                for d in drafts
            ))
        self._clear_answer()
        self.say(
            f"Saved {len(drafts)} repl{'ies' if len(drafts) != 1 else 'y'} "
            f"for this thread; {len(session.accepted)} in total."
        )
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

        self.run_receipt.set(comment_receipt(
            getattr(packet, "run_record", {}) or {},
            str(getattr(getattr(packet, "artifacts", None), "root", "") or ""),
        ))
        run_record = getattr(packet, "run_record", {}) or {}
        transcript = getattr(packet, "transcript", None)
        if transcript is None:
            transcript = (
                run_record.get("transcript", {})
                if isinstance(run_record, dict)
                else {}
            )
        self._show_evidence(getattr(packet, "evidence", {}) or {})
        self._show_transcript(transcript)
        debug_packet = str(getattr(packet, "debug_packet", "") or "")
        if debug_packet:
            self._set_debug_view(debug_packet, complete=False)
        else:
            self._set_debug_view(
                "Debug build was not selected for this packet.",
                complete=False,
            )
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
        """Save the model's comment from the visible box or clipboard."""

        session = getattr(self, "comment_session", None)
        offer = getattr(self, "_offer", None)
        typed = self._answer_text()
        if session is None:
            self.say("Build a packet first.")
            return
        if not typed and (offer is None or not offer.offered):
            self.say("Paste an answer into the box or copy one to the clipboard.")
            return

        try:
            # The raw clipboard: the session owns what counts as an answer.
            result = session.submit(typed or offer.raw)
        except Exception as refusal:        # noqa: BLE001 - reported
            self.say(f"{refusal} Copy the packet first.")
            return

        if getattr(getattr(result, "status", None), "value", "") == "refused":
            if getattr(session, "debug_build", False):
                self._set_debug_view(session.debug_bundle(), complete=True)
            reason = session.state.last_error or "That paste could not be used."
            self.say(reason)
            self._show_refusal(reason)
            self.refresh()
            return

        session.finish()
        if session.accepted:
            self._show_saved_draft(
                str(getattr(session.accepted[-1], "draft", "") or "")
            )
        if getattr(session, "debug_build", False):
            self._set_debug_view(session.debug_bundle(), complete=True)
        self._clear_answer()
        self.say(
            f"Draft saved. {len(session.accepted)} so far. Nothing was posted."
        )
        self.refresh()

    @staticmethod
    def _thread_labels(candidates: Any) -> tuple[str, ...]:
        """One rail entry per owner thread, named by its people.

        The session walks threads. A rail counting people advanced out of
        step with it — the commissioned review reproduced a window that
        showed a second person while the session was already finished, still
        holding the previous thread's packet.
        """

        grouped: dict[str, list[str]] = {}
        for candidate in candidates:
            thread_id = str(getattr(candidate, "thread_id", "") or "")
            grouped.setdefault(thread_id, []).append(
                str(getattr(candidate, "author", "") or "") or "someone"
            )
        return tuple(
            authors[0] if len(authors) == 1
            else f"{authors[0]} +{len(authors) - 1} more"
            for authors in grouped.values()
        )

    def _adopt_session(self, run: Any) -> None:
        """Take the session and the triage packet a reply scan produced."""

        self.session = run.session
        self.run_receipt.set(reply_receipt(
            getattr(run, "receipt", {}) or {}
        ))
        receipt = getattr(run, "receipt", {}) or {}
        transcript = getattr(run, "transcript", None)
        if transcript is None:
            transcript = (
                receipt.get("transcript", {})
                if isinstance(receipt, dict)
                else {}
            )
        threads = list(getattr(run.session, "threads", {}).values())
        self._show_evidence({
            "video": receipt.get("video", {}),
            # The evidence tabs must show what the build gathered; a reply
            # run gathered the owner's comments and every reply in their
            # threads, and showing an empty pane instead reads as a failed
            # scan.
            "comments": [t.comment for t in threads
                         if getattr(t, "comment", None)],
            "replies": [reply for t in threads
                        for reply in getattr(t, "replies", ())],
        })
        self._show_transcript(transcript)
        self.triage_packet = run.triage_packet
        people = [getattr(t, "author", "") for t in run.session.targets]

        # "Answer one person" narrows the run to that handle's thread and
        # skips triage: naming somebody is the answer triage would give.
        wanted = ""
        entry_var = getattr(self, "answer_one_var", None)
        if entry_var is not None:
            wanted = entry_var.get().strip().lstrip("@").casefold()
        if wanted and people:
            named = [
                t for t in run.session.targets
                if str(getattr(t, "author", "")).lstrip("@").casefold()
                == wanted
            ]
            if named:
                # Their whole thread, said plainly: the packet answers
                # every response in it, and pretending otherwise is how a
                # one-person label produced replies for two people.
                chosen = {t.thread_id for t in named}
                kept = [t for t in run.session.targets
                        if t.thread_id in chosen]
                run.session.targets = kept
                people = [getattr(t, "author", "") for t in kept]
                self.triage_packet = ""
                others = [p for p in people
                          if p.lstrip("@").casefold() != wanted]
                self.say(
                    f"Answering {named[0].author}'s whole thread"
                    + (f", which also covers {', '.join(others)}."
                       if others else ".")
                )
            else:
                self.say(
                    f"@{wanted} is not among the {len(people)} people "
                    "waiting, so everyone is shown."
                )

        box = getattr(self, "reply_people_box", None)
        if box is not None:
            box["values"] = people
        self.sequence = ReplySequence(
            people=self._thread_labels(run.session.targets))

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
        typed = self._answer_text()
        if session is None or (
            not typed and (offer is None or not offer.offered)
        ):
            self.say("Paste a triage answer into the box or copy one.")
            return

        wanted = {handle.lstrip("@").casefold()
                  for handle in parse_triage_selection(typed or offer.raw)}
        if not wanted:
            self.say("No handles were found in that answer. The queue is "
                     "unchanged.")
            return

        named = [t for t in session.targets
                 if str(getattr(t, "author", "")).lstrip("@").casefold()
                 in wanted]
        if not named:
            self.say(
                f"That answer named {len(wanted)} people, none of them in "
                "this queue. The queue is unchanged."
            )
            return

        # A thread is answered whole: one packet replies to everybody in
        # it, so keeping only the named person would still produce replies
        # for their thread-mates while the label claimed otherwise. Keep
        # the whole threads and say who came along.
        chosen_threads = {t.thread_id for t in named}
        kept = [t for t in session.targets if t.thread_id in chosen_threads]
        extras = [t.author for t in kept if t not in named]
        session.targets = kept
        self._clear_answer()
        self.sequence = ReplySequence(people=self._thread_labels(kept))
        self.sequence.advance_to(Step.PEOPLE)
        message = (
            f"Working through {len(chosen_threads)} "
            f"thread{'s' if len(chosen_threads) != 1 else ''} covering "
            f"{len(kept)} people."
        )
        if extras:
            message += (
                " A thread is answered whole, so this also covers "
                + ", ".join(extras) + "."
            )
        self.say(message)
        self._start_person()

    def _start_person(self) -> None:
        """Move the session to the thread the rail is showing.

        The rail advances only when the session does. At exhaustion the
        stale packet is cleared — the review reproduced a window that showed
        the next name while copying the previous thread's packet.
        """

        session = getattr(self, "session", None)
        if session is None:
            return
        try:
            if session.state.phase.value == "idle":
                session.start()
            person = session.next_person()
        except Exception as refusal:        # noqa: BLE001 - reported, not raised
            self.say(str(refusal))
            return
        if person is None:
            self.last_packet = ""
            self.sequence.advance_to(Step.FINISH)
            self.say("Every thread in the queue is done.")
            return
        self.last_packet = session.current_packet
        self._show_what_they_said(getattr(session, "current_targets", ()))

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
        self.copy_button.configure(text="Copy packet again")
        self.refresh()
        return True

    def do_copy(self) -> None:
        self._copy_current_packet(auto=False)

    def copy_generated_packet(self) -> None:
        """Copy exactly what the Generated packet tab displays."""

        text = self.generated_packet or self.last_packet
        if not text:
            self.say("Build a packet first.")
            return
        try:
            if self.clipboard is None:
                raise RuntimeError("no clipboard service is available")
            self.clipboard.write(text)
        except Exception as failure:        # noqa: BLE001 - visible copy error
            self.say(f"Could not copy the generated packet: {failure}")
            return
        self.say(f"Generated packet copied: {len(text):,} characters.")
        self.refresh()

    def stop_build(self) -> None:
        """Request cancellation from either visible Stop button."""

        if not self.job.running:
            return
        self.job.cancel()
        self.say("Stopping at the next safe point...")
        self.refresh()

    @staticmethod
    def _unrecorded_indexes(session: Any) -> list[int]:
        return [
            index
            for index, item in enumerate(
                list(getattr(session, "accepted", ()) or ()))
            if not getattr(item, "posted_recorded", False)
        ]

    def record_posted(self) -> None:
        """Mark the next unrecorded accepted draft as manually posted.

        One row per posted reply, in acceptance order. A batch accepts
        several drafts at once, and recording only the last one left every
        earlier reply unrecordable — the review's finding.
        """

        session = (
            getattr(self, "session", None) if self.mode.get() == "reply"
            else getattr(self, "comment_session", None)
        )
        if session is None or not getattr(session, "accepted", ()):
            self.say("There is no accepted draft to record.")
            self.refresh()
            return
        pending = self._unrecorded_indexes(session)
        if not pending:
            self.say("Every accepted draft is already recorded.")
            self.refresh()
            return
        index = pending[0]
        item = session.accepted[index]
        draft = str(getattr(item, "draft", "") or "")
        target = str(getattr(item, "author", "") or "")
        preview = " ".join(draft.split())[:320]
        target_line = f"\n\nTarget: {target}" if target else ""
        prompt = (
            f"Record accepted {'reply' if target else 'comment'} "
            f"{index + 1} of {len(session.accepted)} as posted?"
            f"{target_line}\n\n{preview}"
            "\n\nThis updates local history only. It does not post to YouTube."
        )
        if not self._confirm_record_posted(prompt):
            self.say("Posting record cancelled.")
            self.refresh()
            return
        try:
            added = session.record_posted(index)
        except Exception as failure:        # noqa: BLE001 - visible refusal
            self.say(f"The draft was saved, but history was not updated: {failure}")
        else:
            remaining = len(self._unrecorded_indexes(session))
            self.say(
                (f"Recorded as posted. {remaining} still unrecorded."
                 if remaining else "Recorded as posted. All caught up.")
                if added else "That posting event was already recorded."
            )
        self.refresh()

    @staticmethod
    def _record_available(session: Any) -> bool:
        return bool(PacketWindow._unrecorded_indexes(session))

    def _update_record_button(self, session: Any) -> None:
        accepted = list(getattr(session, "accepted", ()) or ())
        pending = self._unrecorded_indexes(session)
        if not accepted:
            label = "Record as posted"
        elif not pending:
            label = "Postings recorded"
        elif len(accepted) > 1:
            label = (f"Record {pending[0] + 1} of {len(accepted)} as posted")
        else:
            label = "Record as posted"
        self.record_button.configure(text=label)

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
            # The session keeps the skipped ledger the review file prints;
            # skipping only the rail hid every GUI skip from that record.
            session = getattr(self, "session", None)
            if session is not None and self.sequence.step is Step.PEOPLE:
                try:
                    session.skip_person()
                except Exception as refusal:  # noqa: BLE001 - reported
                    self.say(str(refusal))
            self.sequence.next_person()
            if self.sequence.step is Step.PEOPLE:
                self._start_person()
        self.refresh()

    def start_over(self) -> None:
        if self.job.running:
            self.job.cancel()
            self._active_job_generation = -1
        self.comment_session = None
        self.session = None
        self.sequence = ReplySequence()
        self.result = None
        self.triage_packet = ""
        self.current_packet = ""
        self.generated_packet = ""
        self.last_packet = ""
        self._pending_build_signature = ""
        self._completed_build_signature = ""
        self.run_receipt.set("")
        self._set_transcript_status("unknown", "Transcript not checked yet.")
        self._clear_evidence_views()
        self._clear_answer()
        self._offer = None
        self.progress_value.set(0.0)
        self._message = ""
        self.refresh()

    def reset_all(self) -> None:
        """Return the entire window to its safe opening state."""

        if self.job.running:
            self.job.cancel()
            self._active_job_generation = -1
        offer = read_clipboard(
            self.read_clipboard(),
            step=Step.BUILD,
            packet=self.last_packet,
        )
        self._suppressed_clipboard_video = (
            offer.payload if offer.holding.name == "VIDEO" else ""
        )
        self.options = self.options.apply_writing_preset(BUILT_IN_PRESETS[0])
        self.options.video = ""
        self.debug_build.set(False)
        self.mode.set("comment")
        self.video.set("")
        self.video_url.set("")
        self.length.set(self.options.length)
        self.custom_length.set(self.options.custom_length)
        self.approach_filter.set("")
        for name, box in self.dial_boxes.items():
            box.set(dial_choice_label(DIALS[name].default))
        self._fill_approaches()
        self.preset_name.set("Default")
        self.comment_session = None
        self.session = None
        self.sequence = ReplySequence()
        self.result = None
        self.triage_packet = ""
        self.current_packet = ""
        self.generated_packet = ""
        self.last_packet = ""
        self._pending_build_signature = ""
        self._completed_build_signature = ""
        self.run_receipt.set("")
        self._set_transcript_status("unknown", "Transcript not checked yet.")
        self._clear_evidence_views()
        self._clear_answer()
        self._show_saved_draft()
        self._offer = None
        self.progress_value.set(0.0)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.output_tabs.select(self.activity_tab)
        self._message = "Reset complete."
        self.refresh()

    def reset_options(self) -> None:
        self.options = self.options.apply_writing_preset(BUILT_IN_PRESETS[0])
        self.length.set(self.options.length)
        self.custom_length.set(self.options.custom_length)
        for name, box in self.dial_boxes.items():
            box.set(dial_choice_label(DIALS[name].default))
        self._fill_approaches()
        self.preset_name.set("Default")
        self.refresh()

    def open_advanced(self) -> None:        # pragma: no cover - opens a dialog
        AdvancedDialog(self.root, self.options, on_close=self.refresh)

    # -- worker events -----------------------------------------------------

    def _on_event(self, event) -> None:
        if event.generation != self._active_job_generation:
            if event.kind == "confirmation":
                request = event.value
                if hasattr(request, "resolve"):
                    request.resolve(False)
            return
        if event.kind == "progress":
            # A blank message still moves the bar but must not write a line.
            # Reply retrieval emits one event per thread with nothing to say,
            # and a live build filled the log with ten empty rows.
            if event.message.strip():
                self.say(event.message)
            if event.fraction is not None:
                self.progress_value.set(event.fraction)
            payload = event.value if isinstance(event.value, dict) else {}
            step = str(payload.get("step") or "")
            data = payload.get("data")
            data = data if isinstance(data, dict) else {}
            entry = data.get("transcript_entry")
            if step == "transcribe" and isinstance(entry, dict):
                if not self._live_transcript_started:
                    self._live_transcript_started = True
                    self.output_tabs.select(self.transcript_tab)
                self._append_transcript_entry(entry)
                self._set_transcript_status(
                    "working",
                    "Local Whisper is transcribing — "
                    f"{self._eta_text(data.get('eta_seconds'))}.",
                )
            elif step == "transcribe":
                self._set_transcript_status(
                    "working",
                    "Local Whisper is starting.",
                )
        elif event.kind == "confirmation":
            request = event.value
            reason = transcript_notification(
                getattr(request, "payload", {})
            )
            self._set_transcript_status("missing", reason)
            accepted = False
            try:
                accepted = bool(self._confirm_whisper(reason))
            except Exception as failure:    # noqa: BLE001 - refuse safely
                self.say(f"Whisper confirmation could not open: {failure}")
            finally:
                request.resolve(accepted)
            if accepted:
                self._set_transcript_status(
                    "working",
                    "Local Whisper was approved and is starting.",
                )
                self.say("Starting local Whisper transcription.")
            else:
                self._set_transcript_status(
                    "missing",
                    f"{reason} Local Whisper was not started.",
                )
                self.say("Continuing without local Whisper.")
        elif event.kind == "done":
            self._completed_build_signature = self._pending_build_signature
            self._pending_build_signature = ""
            self.result = event.value
            if hasattr(event.value, "session"):
                # A reply run hands back a guided session rather than a
                # packet: it owns every rule about who gets which packet and
                # what counts as an answer, so the window drives it instead
                # of deciding any of that a second time.
                self.generated_packet = ""
                self._adopt_session(event.value)
            else:
                self.generated_packet = str(
                    getattr(event.value, "text", "") or ""
                )
                self.last_packet = str(
                    getattr(event.value, "model_text", "")
                    or getattr(event.value, "debug_packet", "")
                    or self.generated_packet
                )
                self._adopt_comment(event.value)
                self._copy_current_packet(auto=True)
            self.output_tabs.select(self.packet_tab)
            # Completion is already stated in the status line. Leaving a
            # permanently full bar makes an idle window look busy.
            self.progress_value.set(0.0)
            if not self.last_packet:
                self.say(event.message)
        elif event.kind == "cancelled":
            self._pending_build_signature = ""
            self.progress_value.set(0.0)
            self._set_transcript_status(
                "missing",
                "The transcript check or local transcription was stopped.",
            )
            self.say("Stopped.")
        else:
            self._pending_build_signature = ""
            self.progress_value.set(0.0)
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

    def _default_ask_preset_name(self) -> str | None:  # pragma: no cover
        from tkinter import simpledialog

        return simpledialog.askstring(
            "Save custom preset",
            "Preset name:",
            parent=self.root,
        )

    def _default_confirm_delete_preset(self, name: str) -> bool:  # pragma: no cover
        from tkinter import messagebox

        return bool(messagebox.askyesno(
            "Delete custom preset",
            f"Delete {name!r}?",
            parent=self.root,
        ))

    def _default_confirm_record_posted(self, message: str) -> bool:  # pragma: no cover
        from tkinter import messagebox

        return bool(messagebox.askyesno(
            "Record as posted",
            message,
            parent=self.root,
        ))

    def _default_confirm_whisper(self, reason: str) -> bool:  # pragma: no cover
        from tkinter import messagebox

        return bool(messagebox.askyesno(
            "Use local Whisper?",
            (
                f"{reason}\n\n"
                "Use local Whisper to download the audio and create a "
                "machine transcript?\n\n"
                "Long videos can take a long time. You can stop the work "
                "from the main window."
            ),
            parent=self.root,
        ))


def launch(**kwargs) -> PacketWindow:       # pragma: no cover - real Tk
    window = PacketWindow(**kwargs)
    window.root.deiconify()
    window.root.lift()
    window.root.mainloop()
    return window
