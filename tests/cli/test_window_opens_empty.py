"""`comment build --window` must reach a window with nothing on the clipboard.

That is the path gui.bat takes. main() resolves the video from the clipboard
before dispatching, so an empty clipboard refused before a window could exist
-- which is precisely the behaviour the operator asked to be rid of: he should
not have to have copied a link in order to open the window.

No window is opened here; the launcher is injected.
"""

from __future__ import annotations

import io
import sys

import pytest

CLI = sys.modules.get("llm_youtube_comment_generation.interfaces.cli.main")
if CLI is None:                             # imported for its side effect
    import llm_youtube_comment_generation.interfaces.cli.main  # noqa: F401

    CLI = sys.modules["llm_youtube_comment_generation.interfaces.cli.main"]


class Clipboard:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def read(self) -> str:
        return self.value

    def write(self, text: str) -> None:
        self.value = text


@pytest.fixture
def opened(monkeypatch, isolated_application_state):
    """Records what would have been launched, and launches nothing."""

    captured: dict = {}
    private_state = isolated_application_state / "explicit"
    monkeypatch.setattr(
        CLI,
        "_window_settings_path",
        lambda _configuration: private_state / "window_settings.json",
    )
    monkeypatch.setattr(
        CLI,
        "_private_state_directory",
        lambda _configuration: private_state,
    )

    def fake_launch(**kwargs):
        captured.update(kwargs)

        class Window:
            options = kwargs.get("options")

        return Window()

    original = CLI.run_packet_window

    def patched(*args, **kwargs):
        kwargs["launcher"] = fake_launch
        kwargs.setdefault("clipboard", Clipboard())
        return original(*args, **kwargs)

    monkeypatch.setattr(CLI, "run_packet_window", patched)
    return captured


def run(argv, clipboard=None):
    out = io.StringIO()
    code = CLI.main(argv, stdout=out, stderr=out,
                    clipboard=clipboard or Clipboard())
    return code, out.getvalue()


def test_an_empty_clipboard_still_opens_the_window(opened, tmp_path):
    code, printed = run(
        ["comment", "build", "--window", "--no-copy",
         "--output-dir", str(tmp_path)]
    )

    assert code == 0
    assert opened, "no window was opened"
    assert "Opening the packet window" not in printed
    assert "Window closed" not in printed


def test_the_window_opens_with_an_empty_video_box(opened, tmp_path):
    run(["comment", "build", "--window", "--no-copy",
         "--output-dir", str(tmp_path)])

    assert opened["options"].video == ""


def test_a_video_on_the_command_line_still_wins(opened, tmp_path):
    run(["comment", "build", "gC-J7zwYMAM", "--window", "--no-copy",
         "--output-dir", str(tmp_path)])

    assert opened["options"].video == "gC-J7zwYMAM"


def test_the_window_is_given_something_that_can_build(opened, tmp_path):
    """A window whose Build button has no builder behind it is a window that
    says "No builder was supplied" to somebody who wanted a packet."""

    run(["comment", "build", "--window", "--no-copy",
         "--output-dir", str(tmp_path)])

    assert callable(opened["build"])


def test_the_window_receives_private_custom_preset_storage(
    opened,
    tmp_path,
    isolated_application_state,
):
    run(["comment", "build", "--window", "--no-copy",
         "--output-dir", str(tmp_path)])

    store = opened["preset_store"]
    assert store.path.name == "writing_presets.json"
    assert store.path.is_relative_to(isolated_application_state)


def test_a_packet_on_the_clipboard_does_not_stop_the_window(opened, tmp_path):
    """The tool puts its own packet on the clipboard when a run finishes, so
    the clipboard usually holds one. Every other command refuses that, and
    correctly -- but refusing to open a window over it is absurd."""

    held = Clipboard("## BEGIN UNTRUSTED SOURCE MATERIAL\n### Hardened final\n")

    code, _ = run(["comment", "build", "--window", "--no-copy",
                   "--output-dir", str(tmp_path)], clipboard=held)

    assert code == 0
    assert opened["options"].video == ""


def test_ytcomment_gui_opens_the_new_window_on_the_reply_side(opened, tmp_path):
    """One window. The old one scanned before anything appeared and offered
    eleven equal buttons with no options on it."""

    code, _ = run(["gui", "--my-handle", "someone",
                   "--output-dir", str(tmp_path)])

    assert code == 0
    assert opened["mode"] == "reply"
    assert opened["options"].video == ""


def test_the_reply_window_does_not_demand_a_video_before_opening(opened, tmp_path):
    """The scan happens when Find who needs a reply is pressed, not before,
    so there is nothing to resolve at start-up."""

    code, _ = run(["gui", "--my-handle", "someone",
                   "--output-dir", str(tmp_path)],
                  clipboard=Clipboard("nothing useful here"))

    assert code == 0
    assert opened["options"].video == ""


def test_the_handle_reaches_the_window(
    opened,
    tmp_path,
    isolated_application_state,
):
    run(["gui", "--my-handle", "someone", "--output-dir", str(tmp_path)])

    assert opened["options"].my_handle in ("someone", "@someone")
    saved = (
        isolated_application_state
        / "explicit"
        / "window_settings.json"
    )
    assert saved.is_file()
    assert saved.resolve().is_relative_to(isolated_application_state.resolve())


def test_the_build_command_without_the_window_still_needs_a_video(tmp_path):
    """The change must not turn every other command into one that shrugs."""

    from llm_youtube_comment_generation.domain.errors import PacketError

    code, printed = run(
        ["comment", "build", "--dry-run", "--output-dir", str(tmp_path)]
    )

    assert code != 0 or "clipboard" in printed.lower()


def test_windowed_dry_run_is_refused_before_a_window_opens(opened, tmp_path):
    clipboard = Clipboard("keep this")

    code, printed = run(
        [
            "comment", "build", "--window", "--dry-run",
            "--output-dir", str(tmp_path),
        ],
        clipboard=clipboard,
    )

    assert code != 0
    assert opened == {}
    assert clipboard.value == "keep this"
    assert "cannot be combined" in printed
