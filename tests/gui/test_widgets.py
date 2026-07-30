import tkinter as tk

from llm_youtube_comment_generation.interfaces.gui.widgets import (
    TextContextMenu,
)


def test_text_context_menu_copies_only_the_selected_text(tk_root):
    widget = tk.Text(tk_root)
    widget.insert("1.0", "first selected last")
    widget.tag_add("sel", "1.6", "1.14")
    copied = []

    menu = TextContextMenu(widget, copied.append)
    menu.copy()

    assert copied == ["selected"]
    assert widget.bind("<Button-3>")


def test_text_context_menu_can_select_a_read_only_view(tk_root):
    widget = tk.Text(tk_root)
    widget.insert("1.0", "all of this")
    widget.configure(state="disabled")

    menu = TextContextMenu(widget, lambda _text: None)
    menu.select_all()

    assert widget.get("sel.first", "sel.last") == "all of this"
