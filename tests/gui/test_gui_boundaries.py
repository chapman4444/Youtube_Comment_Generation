"""The three boundary rules, checked by parsing the GUI rather than running it.

Source-level on purpose. These are structural rules, and a structural rule
checked structurally needs no display — which matters because Tk interpreter
creation is flaky on this machine and every test that needs one is another
chance to fail for a reason unrelated to the code.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

GUI = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "llm_youtube_comment_generation" / "interfaces" / "gui"
)

MODULES = sorted(GUI.glob("*.py"))
PURE_MODULES = [m for m in MODULES if m.name in ("view_models.py",
                                                 "controllers.py")]


def source(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def test_there_is_a_gui_to_check():
    assert MODULES, f"no GUI modules under {GUI}"
    assert PURE_MODULES


# --------------------------------------------------------------------------
# 1. The GUI owns no workflow transitions
# --------------------------------------------------------------------------


def test_the_window_never_sets_workflow_state_directly():
    """Exactly one layer owns transitions.

    The legacy window inferred and mutated its own notion of where the
    workflow was, which meant two answers to every question about it.
    """

    for module in MODULES:
        text = source(module)
        assert ".phase =" not in text, f"{module.name} assigns a phase"
        assert "WorkflowState(" not in text, f"{module.name} builds its own state"
        assert "TRANSITIONS" not in text, f"{module.name} reads the table itself"


def test_the_window_asks_which_actions_are_allowed_rather_than_deciding():
    """Enablement comes from next_allowed_actions and nowhere else."""

    view_models = source(GUI / "view_models.py")

    assert "next_allowed_actions" in view_models
    window = source(GUI / "main_window.py")
    # The window reads `action.enabled`; it must not compute enablement.
    assert "action.enabled" in window
    assert "next_allowed_actions" not in window


def test_the_window_calls_no_session_method_that_bypasses_the_controller():
    """A direct call into the session would skip the state machine."""

    window = source(GUI / "main_window.py")

    for bypass in ("session.submit", "session.next_person", "session.start",
                   "session.cancel", "session.skip_person",
                   "accept_answer", "reject_answer"):
        assert bypass not in window, f"main_window calls {bypass} directly"


# --------------------------------------------------------------------------
# 2. No clipboard except through the port
# --------------------------------------------------------------------------


def test_the_window_never_touches_tks_own_clipboard():
    """Tk's clipboard is unreliable mid-run, and reaching for it here would
    put an untestable dependency in the path that decides what gets posted."""

    for module in MODULES:
        text = source(module)
        for forbidden in ("clipboard_get", "clipboard_append", "clipboard_clear",
                          "selection_get"):
            assert forbidden not in text, f"{module.name} uses {forbidden}"


def test_the_clipboard_is_reached_only_through_the_port():
    controllers = source(GUI / "controllers.py")

    assert "self.session.clipboard" in controllers
    assert "import pyperclip" not in controllers


# --------------------------------------------------------------------------
# 3. No output filename is decided in the GUI
# --------------------------------------------------------------------------


def test_the_gui_names_no_output_file():
    """Filenames are the artifact store's business.

    A window that knew a filename would be a second place the output layout
    is defined, and the two would drift.
    """

    for module in MODULES:
        text = source(module)
        for name in (".md\"", ".md'", ".json\"", ".json'", ".csv\"", ".txt\""):
            assert name not in text, f"{module.name} names an output file"


# --------------------------------------------------------------------------
# The pure layer really is pure
# --------------------------------------------------------------------------


@pytest.mark.parametrize("module", PURE_MODULES, ids=lambda p: p.name)
def test_the_logic_layer_imports_no_tkinter(module):
    """This is what makes the GUI testable without a display."""

    tree = ast.parse(source(module))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "tkinter" not in imported


#: The only modules allowed to draw. Everything else in this package decides
#: what a window shows without being able to show it, which is what keeps the
#: rules testable on a machine where Tk interpreter creation is flaky.
WINDOW_MODULES = {
    "advanced_dialog.py",
    "launcher.py",
    "main_window.py",
    "packet_window.py",
    "widgets.py",
}


def test_only_the_window_modules_import_tkinter():
    windowed = {m.name for m in MODULES if "import tkinter" in source(m)}

    assert windowed == WINDOW_MODULES, (
        "a module outside the window layer imports tkinter, which makes its "
        "rules untestable without a display"
    )


def test_every_intent_the_window_offers_has_a_label():
    """A button with no text is a button nobody presses on purpose."""

    from llm_youtube_comment_generation.domain.workflow import Intent
    from llm_youtube_comment_generation.interfaces.gui.view_models import (
        BUTTON_LABELS,
        INTERNAL_INTENTS,
    )

    for intent in Intent:
        assert intent in BUTTON_LABELS
        if intent not in INTERNAL_INTENTS:
            assert BUTTON_LABELS[intent], f"{intent.value} has no label"
