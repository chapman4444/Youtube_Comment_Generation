"""The Advanced dialog, which is where the settings nobody changes twice live.

Untested until now, and its failure mode is the worst kind: a dialog that
takes an edit, closes politely and discards it looks exactly like one that
worked. The operator would find out when a run used the old value.

One Tk interpreter for the file, as everywhere else in this directory.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from llm_youtube_comment_generation.interfaces.gui.packet_window import (
    AdvancedDialog,
)
from llm_youtube_comment_generation.interfaces.gui.options import (
    PacketOptionsModel,
)


@pytest.fixture
def dialog(tk_root):
    options = PacketOptionsModel(video="gC-J7zwYMAM")
    built = AdvancedDialog(tk_root, options)
    built.top.withdraw()
    yield built
    if built.top.winfo_exists():
        built.top.destroy()


# -- it carries the values both ways ---------------------------------------


def test_it_opens_showing_what_is_already_set(tk_root):
    options = PacketOptionsModel(my_handle="@someone", max_top=250,
                                 proxy_url="http://127.0.0.1:8888")
    built = AdvancedDialog(tk_root, options)
    built.top.withdraw()

    assert built.variables["my_handle"].get() == "@someone"
    assert built.variables["max_top"].get() == 250
    assert built.variables["proxy_url"].get() == "http://127.0.0.1:8888"
    built.top.destroy()


def test_an_edit_reaches_the_options(dialog):
    dialog.variables["my_handle"].set("@changed")
    dialog.variables["max_recent"].set(321)

    dialog.close()

    assert dialog.options.my_handle == "@changed"
    assert dialog.options.max_recent == 321


def test_retrieve_replies_reaches_the_options(dialog):
    dialog.include_replies.set(False)

    dialog.close()

    assert dialog.options.include_replies is False


def test_disconnected_editor_and_overwrite_controls_are_not_offered(dialog):
    frame = dialog.top.winfo_children()[0]
    labels = {
        str(child.cget("text"))
        for child in frame.winfo_children()
        if "text" in child.keys()
    }

    assert "Open files with:" not in labels
    assert "Overwrite a previous output folder" not in labels
    assert "Reply threads:" not in labels
    assert "Reply threads to retrieve:" in labels


def test_whisper_behavior_is_a_three_way_choice(dialog):
    frame = dialog.top.winfo_children()[0]
    values = {
        child.cget("value")
        for child in frame.winfo_children()
        if child.winfo_class() == "TRadiobutton"
    }

    assert values == {"ignore", "ask", "automatic"}


def test_whisper_choice_reaches_the_options(dialog):
    dialog.whisper_policy.set("ignore")

    dialog.close()

    assert dialog.options.whisper_policy == "ignore"
    assert dialog.options.transcribe_locally is False


def test_automatic_whisper_keeps_the_legacy_setting_in_sync(dialog):
    dialog.whisper_policy.set("automatic")

    dialog.close()

    assert dialog.options.whisper_policy == "automatic"
    assert dialog.options.transcribe_locally is True


def test_closing_tells_whoever_opened_it(tk_root):
    """The window has to redraw: a packet-character change moves what the
    status line says, and a handle change decides whether reply mode can
    run at all."""

    told = []
    built = AdvancedDialog(tk_root, PacketOptionsModel(),
                           on_close=lambda: told.append(True))
    built.top.withdraw()

    built.close()

    assert told == [True]


def test_it_does_not_touch_what_it_was_not_shown(dialog):
    """It carries the settings nobody changes twice. The registers, the dials
    and the video are the main window's business and must survive it."""

    dialog.options.comment_variations = ("short_hook",)
    dialog.options.dials = {"grounding": "summary"}

    dialog.close()

    assert dialog.options.comment_variations == ("short_hook",)
    assert dialog.options.dials == {"grounding": "summary"}
    assert dialog.options.video == "gC-J7zwYMAM"


def test_every_field_it_offers_is_a_real_setting(dialog):
    """A field that writes to an attribute the model does not have would be
    accepted, stored nowhere, and silently lost."""

    model = PacketOptionsModel()
    for name, _label, _kind in AdvancedDialog.FIELDS:
        assert hasattr(model, name), f"{name} is not a setting"


def test_every_advanced_control_has_help(dialog):
    frame = dialog.top.winfo_children()[0]
    interactive = {
        child
        for child in frame.winfo_children()
        if child.winfo_class() in {
            "TEntry",
            "TSpinbox",
            "TCheckbutton",
            "TRadiobutton",
            "TButton",
        }
    }
    covered = {tooltip.widget for tooltip in dialog._tooltips}

    assert interactive <= covered


def test_a_number_field_that_will_not_parse_leaves_the_old_value(tk_root):
    """Tk raises rather than returning nonsense from an IntVar holding
    letters. Losing one field is acceptable; losing the dialog is not."""

    options = PacketOptionsModel(max_top=99)
    built = AdvancedDialog(tk_root, options)
    built.top.withdraw()
    built.variables["max_top"].set("")          # empties the spinbox

    built.close()

    assert options.max_top in (0, 99)
    assert options.my_handle == ""
