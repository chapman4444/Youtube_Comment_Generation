"""The infrequently changed retrieval and filesystem settings."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .options import PacketOptionsModel, WHISPER_POLICIES
from .widgets import Tooltip

PADDING = 8


class AdvancedDialog:                       # pragma: no cover - opens a dialog
    FIELDS = (
        ("output_directory", "Output folder", str),
        ("languages", "Transcript languages", str),
        ("proxy_url", "Proxy URL", str),
        ("whisper_model", "Whisper model", str),
        ("whisper_maximum_minutes", "Whisper maximum minutes", int),
        ("whisper_maximum_audio_mib", "Whisper maximum audio MiB", int),
        ("my_handle", "Your @username", str),
        ("max_top", "Relevance comments", int),
        ("max_recent", "Recent comments", int),
        ("max_threads", "Reply threads to retrieve", int),
        ("max_replies", "Replies to retrieve per thread", int),
        ("packet_characters", "Packet characters", int),
    )
    FIELD_HELP = {
        "output_directory": "Where completed run folders are saved.",
        "languages": "Preferred transcript language codes, separated by commas.",
        "proxy_url": "Optional proxy used for transcript and video retrieval.",
        "whisper_model": "The local Whisper model used for audio transcription.",
        "whisper_maximum_minutes": "Refuse Whisper above this video duration.",
        "whisper_maximum_audio_mib": "Stop the audio download above this size.",
        "my_handle": "Your YouTube @username, used to find replies to you.",
        "max_top": "Maximum relevance-ranked comments to retain.",
        "max_recent": "Maximum newest comments to retain.",
        "max_threads": "Maximum comment threads whose replies are retrieved.",
        "max_replies": (
            "Maximum replies fetched and offered to the packet from each "
            "selected thread. The packet budget decides how many fit and "
            "reports any omissions."
        ),
        "packet_characters": "Maximum total size of the generated model packet.",
    }

    def __init__(self, parent, options: PacketOptionsModel, on_close=None):
        self.options = options
        self.on_close = on_close or (lambda: None)
        self.top = tk.Toplevel(parent)
        self.top.title("Advanced")
        self.top.transient(parent)
        # Closing with the title-bar X is the same act as pressing Done.
        # Without this, edits were copied back only by the Done button and
        # an X-close silently discarded them (harsh-critic review,
        # finding 10).
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.variables: dict[str, tk.Variable] = {}
        self._tooltips: list[Tooltip] = []

        frame = ttk.Frame(self.top, padding=PADDING)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        for row, (name, label, kind) in enumerate(self.FIELDS):
            label_widget = ttk.Label(frame, text=f"{label}:")
            label_widget.grid(
                row=row, column=0, sticky="w", pady=2
            )
            variable: tk.Variable = (
                tk.IntVar(value=getattr(options, name))
                if kind is int
                else tk.StringVar(value=getattr(options, name))
            )
            self.variables[name] = variable
            widget = (
                ttk.Spinbox(
                    frame,
                    from_=0,
                    to=2_000_000,
                    increment=10,
                    textvariable=variable,
                    width=14,
                )
                if kind is int
                else ttk.Entry(frame, textvariable=variable, width=44)
            )
            widget.grid(
                row=row, column=1, sticky="ew", padx=(6, 0), pady=2
            )
            help_text = self.FIELD_HELP[name]
            self._tooltips.extend((
                Tooltip(label_widget, lambda value=help_text: value),
                Tooltip(widget, lambda value=help_text: value),
            ))

        row = len(self.FIELDS)
        self.include_replies = tk.BooleanVar(value=options.include_replies)
        retrieve_replies = ttk.Checkbutton(
            frame, text="Retrieve replies", variable=self.include_replies
        )
        retrieve_replies.grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        self._tooltips.append(Tooltip(
            retrieve_replies,
            lambda: "Include replies beneath the selected top-level comments.",
        ))
        ttk.Label(frame, text="When no transcript is available:").grid(
            row=row + 1, column=0, columnspan=2, sticky="w", pady=(8, 2)
        )
        policy = str(getattr(options, "whisper_policy", "") or "").lower()
        if policy not in WHISPER_POLICIES:
            policy = "automatic" if options.transcribe_locally else "ask"
        self.whisper_policy = tk.StringVar(value=policy)
        choices = (
            ("ignore", "Ignore — build without a transcript and do not ask"),
            ("ask", "Ask before using local Whisper"),
            ("automatic", "Automatically use local Whisper"),
        )
        for offset, (value, label) in enumerate(choices, 2):
            choice = ttk.Radiobutton(
                frame,
                text=label,
                value=value,
                variable=self.whisper_policy,
            )
            choice.grid(
                row=row + offset,
                column=0,
                columnspan=2,
                sticky="w",
                padx=(12, 0),
            )
            help_text = {
                "ignore": "Continue without a transcript and do not ask.",
                "ask": "Show a confirmation before starting local Whisper.",
                "automatic": "Start local Whisper automatically within its limits.",
            }[value]
            self._tooltips.append(Tooltip(
                choice, lambda text=help_text: text
            ))

        done = ttk.Button(frame, text="Done", command=self.close)
        done.grid(
            row=row + 5, column=1, sticky="e", pady=(10, 0)
        )
        self._tooltips.append(Tooltip(
            done, lambda: "Save these settings and close the Advanced window."
        ))

    def close(self) -> None:
        for name, variable in self.variables.items():
            try:
                setattr(self.options, name, variable.get())
            except tk.TclError:
                continue
        self.options.include_replies = self.include_replies.get()
        self.options.whisper_policy = self.whisper_policy.get()
        self.options.transcribe_locally = (
            self.options.whisper_policy == "automatic"
        )
        self.top.destroy()
        self.on_close()
