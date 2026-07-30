"""The infrequently changed retrieval and filesystem settings."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .options import PacketOptionsModel, WHISPER_POLICIES

PADDING = 8


class AdvancedDialog:                       # pragma: no cover - opens a dialog
    FIELDS = (
        ("output_directory", "Output folder", str),
        ("editor_path", "Open files with", str),
        ("languages", "Transcript languages", str),
        ("proxy_url", "Proxy URL", str),
        ("whisper_model", "Whisper model", str),
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
            ttk.Label(frame, text=f"{label}:").grid(
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

        row = len(self.FIELDS)
        self.include_replies = tk.BooleanVar(value=options.include_replies)
        ttk.Checkbutton(
            frame, text="Retrieve replies", variable=self.include_replies
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.overwrite = tk.BooleanVar(value=options.overwrite)
        ttk.Checkbutton(
            frame,
            text="Overwrite a previous output folder",
            variable=self.overwrite,
        ).grid(row=row + 1, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text="When no transcript is available:").grid(
            row=row + 2, column=0, columnspan=2, sticky="w", pady=(8, 2)
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
        for offset, (value, label) in enumerate(choices, 3):
            ttk.Radiobutton(
                frame,
                text=label,
                value=value,
                variable=self.whisper_policy,
            ).grid(
                row=row + offset,
                column=0,
                columnspan=2,
                sticky="w",
                padx=(12, 0),
            )

        ttk.Button(frame, text="Done", command=self.close).grid(
            row=row + 6, column=1, sticky="e", pady=(10, 0)
        )

    def close(self) -> None:
        for name, variable in self.variables.items():
            try:
                setattr(self.options, name, variable.get())
            except tk.TclError:
                continue
        self.options.include_replies = self.include_replies.get()
        self.options.overwrite = self.overwrite.get()
        self.options.whisper_policy = self.whisper_policy.get()
        self.options.transcribe_locally = (
            self.options.whisper_policy == "automatic"
        )
        self.top.destroy()
        self.on_close()
