"""Small reusable Tk widgets."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class Tooltip:
    """Small delayed help popup with keyboard-focus support."""

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
            self.tip,
            text=text,
            justify="left",
            wraplength=360,
            relief="solid",
            borderwidth=1,
            padding=6,
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
        self.hide()
