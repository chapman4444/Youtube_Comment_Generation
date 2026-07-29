"""The packet window against real Tk.

Few, and only what genuinely needs widgets. Every rule that can be checked
without a display is checked in test_options.py and test_sequence.py, because
interpreter creation is the flaky part on this machine.

One Tk interpreter for the whole file: each test takes a Toplevel from a
single shared root rather than building its own.
"""

from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace

import pytest

from llm_youtube_comment_generation.interfaces.gui.packet_window import (
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
    PacketWindow,
)
from llm_youtube_comment_generation.interfaces.gui.options import (
    LENGTH_HINTS,
    PacketOptionsModel,
)
from llm_youtube_comment_generation.interfaces.gui.sequence import Step
from llm_youtube_comment_generation.interfaces.gui.worker import WorkerEvent

VIDEO_URL = "https://www.youtube.com/watch?v=gC-J7zwYMAM"
ANSWER = "Reasoning.\n\n### Hardened final\nThe reply I would send.\n"


class FakeClipboard:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def read(self) -> str:
        return self.value

    def write(self, text: str) -> None:
        self.value = text


@pytest.fixture
def window(tk_root):
    top = tk.Toplevel(tk_root)
    top.withdraw()
    built = PacketWindow(
        root=top, clipboard=FakeClipboard(), poll=False,
        notify=lambda title, message: None,
    )
    yield built
    top.destroy()


# -- it opens on its own terms ---------------------------------------------


def test_the_window_opens_with_no_video_at_all(window):
    """He should not have to have copied a link before opening it. The old
    window, and the first rebuilt one, resolved a video before a window
    existed -- so "nothing is on the clipboard" was a reason to refuse."""

    assert window.video.get() == ""
    assert "no video" in window.status.get().lower()


@pytest.mark.parametrize(
    ("initial", "identifier"),
    [
        (VIDEO_URL, "gC-J7zwYMAM"),
        ("https://youtu.be/FVG5m_NG5Ak", "FVG5m_NG5Ak"),
        ("gC-J7zwYMAM", "gC-J7zwYMAM"),
    ],
)
def test_preloaded_video_is_normalized_before_widgets_exist(
    tk_root, initial, identifier,
):
    top = tk.Toplevel(tk_root)
    top.withdraw()
    built = PacketWindow(
        root=top,
        options=PacketOptionsModel(video=initial),
        clipboard=FakeClipboard(),
        poll=False,
        notify=lambda title, message: None,
    )
    try:
        assert built.video.get() == identifier
        assert built.video_url.get() == (
            f"https://www.youtube.com/watch?v={identifier}"
        )
        assert built.gather().video == identifier
    finally:
        top.destroy()


def test_invalid_preloaded_video_is_diagnosable_and_does_not_crash(tk_root):
    top = tk.Toplevel(tk_root)
    top.withdraw()
    built = PacketWindow(
        root=top,
        options=PacketOptionsModel(video="not a youtube video"),
        clipboard=FakeClipboard(),
        poll=False,
        notify=lambda title, message: None,
    )
    try:
        assert built.video.get() == "not a youtube video"
        assert built.video_url.get() == ""
        assert "youtube" in built.status.get().lower()
        assert str(built.primary.cget("state")) == "disabled"
    finally:
        top.destroy()


def test_the_video_display_is_read_only(window):
    window.video.set("gC-J7zwYMAM")
    window.refresh()

    assert window.video_url_label.cget("text") == \
        "https://www.youtube.com/watch?v=gC-J7zwYMAM"
    assert window.video_url_label.winfo_class() == "TLabel"


def test_building_is_refused_until_there_is_a_video(window):
    assert str(window.primary.cget("state")) == "disabled"

    window.video.set("gC-J7zwYMAM")
    window.refresh()

    assert str(window.primary.cget("state")) == "normal"


def test_an_empty_clipboard_is_a_state_not_a_failure(window):
    window.poll_clipboard()

    assert "empty" in window.clip_label.get()
    assert str(window.use_button.cget("state")) == "disabled"


# -- the clipboard reports, and never acts ---------------------------------


def test_the_chip_says_what_is_on_the_clipboard(window):
    window.clipboard.value = VIDEO_URL
    window.poll_clipboard()

    assert "YouTube video detected" in window.clip_label.get()
    assert window.video.get() == "gC-J7zwYMAM"


def test_a_bare_video_id_is_detected_from_the_clipboard(window):
    window.clipboard.value = "FVG5m_NG5Ak"

    window.poll_clipboard()

    assert window.video.get() == "FVG5m_NG5Ak"
    assert window.video_url.get().endswith("watch?v=FVG5m_NG5Ak")


def test_unrelated_clipboard_text_does_not_change_a_selected_video(window):
    window.video.set("gC-J7zwYMAM")
    window.clipboard.value = "a screenshot caption"

    window.poll_clipboard()

    assert window.video.get() == "gC-J7zwYMAM"
    assert "no supported YouTube video" in window.clip_label.get()


def test_watching_the_clipboard_fills_only_an_empty_selection(window):
    """Opening/focus detection adopts a valid video only into an empty slot."""

    window.clipboard.value = VIDEO_URL
    for _ in range(10):
        window.poll_clipboard()

    assert window.video.get() == "gC-J7zwYMAM"


def test_a_different_clipboard_video_requires_explicit_replace(window):
    window.video.set("gC-J7zwYMAM")
    window.clipboard.value = "https://youtu.be/FVG5m_NG5Ak"
    window.poll_clipboard()

    assert window.video.get() == "gC-J7zwYMAM"
    assert str(window.use_button.cget("state")) == "normal"

    window.use_clipboard()

    assert window.video.get() == "FVG5m_NG5Ak"


def test_clear_does_not_immediately_reselect_the_same_clipboard_video(window):
    window.video.set("gC-J7zwYMAM")
    window.clipboard.value = VIDEO_URL

    window.clear_video()

    assert window.video.get() == ""
    assert str(window.use_button.cget("state")) == "normal"


def test_clear_then_unrelated_text_restores_automatic_video_detection(window):
    window.video.set("gC-J7zwYMAM")
    window.clipboard.value = VIDEO_URL
    window.clear_video()

    window.clipboard.value = "unrelated clipboard text"
    window.poll_clipboard()
    window.clipboard.value = "https://youtu.be/FVG5m_NG5Ak"
    window.poll_clipboard()

    assert window.video.get() == "FVG5m_NG5Ak"


def test_clear_then_a_different_video_is_adopted_automatically(window):
    window.video.set("gC-J7zwYMAM")
    window.clipboard.value = VIDEO_URL
    window.clear_video()

    window.clipboard.value = "https://youtu.be/FVG5m_NG5Ak"
    window.poll_clipboard()

    assert window.video.get() == "FVG5m_NG5Ak"


def test_watching_never_moves_the_reply_step(window):
    window.mode.set("reply")
    window.sequence.advance_to(Step.TRIAGE)
    window.clipboard.value = ANSWER

    for _ in range(10):
        window.poll_clipboard()

    assert window.sequence.step is Step.TRIAGE


def test_paste_with_nothing_useful_says_so_rather_than_clearing_the_box(window):
    window.video.set("gC-J7zwYMAM")
    window.clipboard.value = "a screenshot caption"
    window.paste_video()

    assert window.video.get() == "gC-J7zwYMAM"
    assert "Nothing to paste" in window.status.get()


# -- every option is reachable ---------------------------------------------


def test_every_register_is_in_the_list(window):
    from llm_youtube_comment_generation.domain.writing_options import (
        VARIATION_LIBRARY,
    )

    assert set(window.approach_checks) == set(VARIATION_LIBRARY)


def test_every_dial_has_a_control(window):
    from llm_youtube_comment_generation.domain.writing_options import DIALS

    assert set(window.dial_boxes) == set(DIALS)
    width = min(int(box.cget("width")) for box in window.dial_boxes.values())
    longest = max(
        len(value)
        for box in window.dial_boxes.values()
        for value in box.cget("values")
    )
    assert width >= longest


def test_writing_controls_are_wide_and_use_concise_help(window):
    box = window.dial_boxes["ending"]

    assert int(box.cget("width")) >= max(
        len(value) for value in box.cget("values")
    )
    box.set("Flat statement")
    window._dial_chosen("ending")

    assert "End on the claim itself" in window.help_text.get()
    assert "Behavior:" not in window.help_text.get()


def test_invalid_target_words_block_build_and_switching_mode_clears_it(window):
    window.video.set("gC-J7zwYMAM")
    window.length.set("exact")
    window.custom_length.set("not a number")
    window.refresh()

    assert str(window.primary.cget("state")) == "disabled"
    assert "whole number" in window.length_error.get()

    window.length.set("short")
    window.refresh()

    assert window.length_error.get() == ""
    assert str(window.primary.cget("state")) == "normal"


def test_choosing_no_register_still_means_the_defaults(window):
    from llm_youtube_comment_generation.domain.writing_options import (
        DEFAULT_VARIATIONS,
    )

    window.use_default_approaches()

    assert window.gather().registers_for("comment") == tuple(DEFAULT_VARIATIONS)


def test_the_two_modes_keep_separate_register_choices(window):
    window.mode.set("comment")
    window.approach_mode.set("custom")
    window.approach_vars["short_hook"].set(True)
    window.gather()
    comment_choice = window.options.comment_variations

    window.mode.set("reply")
    window._display_mode = "reply"
    window._fill_approaches()
    window.approach_mode.set("custom")
    window.approach_vars["dry_one_liner"].set(True)
    window.gather()

    assert window.options.comment_variations == comment_choice
    assert window.options.reply_variations != comment_choice


def test_reset_puts_the_writing_options_back_without_clearing_the_video(window):
    window.video.set("gC-J7zwYMAM")
    window.approach_mode.set("custom")
    window.approach_vars["short_hook"].set(True)
    window.gather()

    window.reset_options()

    assert window.options.comment_variations == ()
    assert window.options.comment_approach_mode == "default"
    assert window.video.get() == "gC-J7zwYMAM"


def test_custom_checkboxes_pass_exact_ids_in_library_order(window):
    window.approach_mode.set("custom")
    window.approach_vars["meta"].set(True)
    window.approach_vars["devils_advocate"].set(True)

    gathered = window.gather()

    assert gathered.registers_for("comment") == (
        "devils_advocate", "meta",
    )


def test_resolved_substitution_keeps_the_requested_selection(window):
    window.approach_mode.set("custom")
    window.approach_vars["dry_joke"].set(True)
    window.gather()
    window.options.dials["humor"] = "none"

    window._apply_resolved_approaches()
    window._update_approach_state()

    assert window.approach_vars["dry_joke"].get()
    assert not window.approach_vars["dry_observation"].get()
    assert window.options.comment_variations == ("dry_joke",)
    assert "will be replaced" in window.resolution_summary.get()
    assert "saved selection is unchanged" in window.resolution_summary.get()

    window.options.dials["humor"] = "unset"
    window._apply_resolved_approaches()

    assert window.approach_vars["dry_joke"].get()
    assert window.options.comment_variations == ("dry_joke",)
    assert window.resolution_summary.get() == ""


@pytest.mark.parametrize("mode", ["comment", "reply"])
@pytest.mark.parametrize(
    "approach",
    ["dry_joke", "dry_one_liner", "sardonic", "off_the_wall"],
)
def test_persisted_humor_conflicts_are_visible_immediately(
    tk_root, mode, approach,
):
    top = tk.Toplevel(tk_root)
    top.withdraw()
    options = PacketOptionsModel(
        video="gC-J7zwYMAM",
        comment_variations=(approach,),
        reply_variations=(approach,),
        comment_approach_mode="custom",
        reply_approach_mode="custom",
        dials={"humor": "none"},
    )
    built = PacketWindow(
        root=top, options=options, clipboard=FakeClipboard(), poll=False,
        notify=lambda title, message: None, mode=mode,
    )
    try:
        assert built.approach_vars[approach].get()
        assert "will be replaced" in built.resolution_summary.get()
        assert "saved selection is unchanged" in built.resolution_summary.get()
        requested = (
            built.options.reply_variations if mode == "reply"
            else built.options.comment_variations
        )
        assert requested == (approach,)
    finally:
        top.destroy()


def test_dynamic_tooltips_do_not_accumulate_on_refill(window):
    static_count = len(window._tooltips)
    for _ in range(10):
        window._fill_approaches()

    assert len(window._tooltips) == static_count
    assert len(window._approach_tooltips) == len(window.approach_checks)


def test_dynamic_tooltips_stay_stable_across_mode_switches(window):
    for _ in range(5):
        window.mode.set("reply")
        window._mode_changed()
        window.mode.set("comment")
        window._mode_changed()

    assert len(window._approach_tooltips) == len(window.approach_checks)


def test_every_approach_displays_its_backend_dimension(window):
    from llm_youtube_comment_generation.domain.writing_options import (
        VARIATION_LIBRARY,
    )

    for key, check in window.approach_checks.items():
        assert f"[{VARIATION_LIBRARY[key].dimension.value}]" in check.cget("text")


def test_successful_build_copies_exact_packet_and_moves_to_answer(window):
    packet = "complete packet text"

    class Session:
        accepted = []
        state = None

        def start(self):
            return None

        def copy_packet(self):
            window.clipboard.write(packet)
            return packet

    window._comment_session_factory = lambda _packet: Session()
    window._on_event(WorkerEvent(
        "done", "done", SimpleNamespace(text=packet, variations=())
    ))

    assert window.clipboard.value == packet
    assert window.last_packet == packet
    assert "built and copied" in window.status.get().lower()
    assert window.copy_button.cget("text") == "Copy again"
    assert "20 characters" in window.packet_count.cget("text")
    assert window.packet_preview.get("1.0", "end-1c") == packet
    assert str(window.packet_preview.cget("state")) == "disabled"
    assert "✓ Build" in window.rail_labels[0].cget("text")
    assert "● Answer" in window.rail_labels[1].cget("text")


def test_copy_again_restores_the_exact_packet(window):
    packet = "complete packet text"
    window._on_event(WorkerEvent(
        "done", "done", SimpleNamespace(text=packet, variations=())
    ))
    window.clipboard.value = "another application replaced it"

    window.do_copy()

    assert window.clipboard.value == packet


def test_clear_removes_packet_state_and_build_returns_for_next_video(window):
    window.video.set("gC-J7zwYMAM")
    window._on_event(WorkerEvent(
        "done", "done", SimpleNamespace(text="old packet", variations=())
    ))

    window.clear_video()

    assert window.last_packet == ""
    assert window.packet_preview.get("1.0", "end-1c") == "Build a packet first."
    assert window.packet_count.cget("text") == ""
    assert window.progress_value.get() == 0.0
    assert str(window.build_button.cget("state")) == "disabled"

    window.video.set("N80TzPCHbNg")
    window.refresh()

    assert str(window.build_button.cget("state")) == "normal"


def test_checkbox_count_alone_selects_default_or_custom_mode(window):
    assert window.options.comment_approach_mode == "default"
    assert "defaults will be used" in window.approach_summary.get()

    window.approach_vars["short_hook"].set(True)
    window._approach_selected()

    assert window.options.comment_approach_mode == "custom"
    assert window.options.comment_variations == ("short_hook",)
    assert "1 custom approach selected" in window.approach_summary.get()

    window.clear_custom_approaches()

    assert window.options.comment_approach_mode == "default"
    assert window.options.comment_variations == ()


def test_length_uses_short_inline_copy_and_long_tooltip_source(window):
    window.length.set("medium")
    window.refresh()

    assert window.length_hint.get() == "A short paragraph."
    assert "20" in LENGTH_HINTS["medium"]


def test_clipboard_copy_failure_does_not_turn_build_into_failure(tk_root):
    class FailingClipboard(FakeClipboard):
        def write(self, text):
            raise OSError("clipboard busy")

    top = tk.Toplevel(tk_root)
    top.withdraw()
    built = PacketWindow(
        root=top, clipboard=FailingClipboard(), poll=False,
        notify=lambda title, message: None,
    )
    try:
        built._on_event(WorkerEvent(
            "done", "done",
            SimpleNamespace(text="complete packet", variations=()),
        ))

        assert built.last_packet == "complete packet"
        assert "clipboard copy failed" in built.status.get().lower()
        assert built.copy_button.cget("text") in ("Copy packet", "Copy again")
    finally:
        top.destroy()


def test_failed_build_never_copies_partial_text(window):
    window.clipboard.value = "keep this"

    window._on_event(WorkerEvent("failed", "build failed after partial work"))

    assert window.clipboard.value == "keep this"
    assert window.last_packet == ""


def test_reply_build_auto_copies_the_first_person_packet(window):
    class Phase:
        value = "idle"

    class Session:
        def __init__(self):
            self.targets = [SimpleNamespace(author="@alice")]
            self.state = SimpleNamespace(phase=Phase())
            self.current_packet = ""
            self.accepted = []

        def start(self):
            self.state.phase.value = "targets_selected"

        def next_person(self):
            self.current_packet = "reply packet"

        def copy_packet(self):
            window.clipboard.write(self.current_packet)
            return self.current_packet

    window.mode.set("reply")
    run = SimpleNamespace(
        session=Session(), triage_packet="", people=("@alice",)
    )

    window._adopt_session(run)

    assert window.last_packet == "reply packet"
    assert window.clipboard.value == "reply packet"
    assert window.sequence.step is Step.PEOPLE


def test_start_over_clears_a_comment_run(window):
    window.comment_session = object()
    window.session = object()
    window.result = object()
    window.triage_packet = "triage"
    window.current_packet = "current"
    window.last_packet = "last"
    window._offer = object()
    window.progress_value.set(0.75)
    window.say("stale status")

    window.start_over()

    assert window.comment_session is None
    assert window.session is None
    assert window.result is None
    assert window.triage_packet == ""
    assert window.current_packet == ""
    assert window.last_packet == ""
    assert window._offer is None
    assert window.progress_value.get() == 0.0
    assert window.primary.cget("text") == "Build packet"
    assert window.status.get() != "stale status"


def test_start_over_clears_a_reply_run(window):
    window.mode.set("reply")
    window._display_mode = "reply"
    window.session = object()
    window.comment_session = object()
    window.result = object()
    window.triage_packet = "triage"
    window.last_packet = "reply packet"
    window.sequence = SimpleNamespace(step=Step.PEOPLE)

    window.start_over()

    assert window.session is None
    assert window.comment_session is None
    assert window.result is None
    assert window.triage_packet == ""
    assert window.last_packet == ""
    assert window.sequence.step is Step.BUILD
    assert window.primary.cget("text") == "Find who needs a reply"


def test_start_over_requests_safe_worker_cancellation(window):
    class RunningJob:
        running = True
        cancelled = False

        def cancel(self):
            self.cancelled = True

    job = RunningJob()
    window.job = job

    window.start_over()

    assert job.cancelled
    assert window._discard_job_result


# -- it fits on a screen ---------------------------------------------------


def test_the_window_is_not_taller_than_a_laptop(window):
    """The old one was taller than a 1080p screen and its own comments say
    so. A notebook takes the height of its tallest tab whichever is showing,
    which is why the modes are radios here."""

    window.root.update_idletasks()

    minimum_width, minimum_height = window.root.minsize()
    assert minimum_width <= 1024
    assert minimum_height <= 700
    assert window.root.winfo_reqwidth() <= 1200
    assert window.root.winfo_reqheight() <= 700


def test_the_log_starts_closed(window):
    """The status line is always there; the log is a disclosure."""

    assert not window.log_open.get()
    assert not window.log_frame.winfo_ismapped()


# -- the worker ------------------------------------------------------------


def test_the_button_lights_up_when_an_answer_appears(window):
    """The chip announced an answer while the button to use it stayed grey:
    enablement is decided in refresh(), and polling did not redraw."""

    class Session:
        accepted: list = []
        state = None

    window.comment_session = Session()
    window.video.set("gC-J7zwYMAM")
    window.refresh()
    assert str(window.primary.cget("state")) == "disabled"

    window.clipboard.value = ANSWER
    window.poll_clipboard()

    assert str(window.primary.cget("state")) == "normal"


def test_polling_an_unchanged_clipboard_does_not_redraw(window):
    """Refreshing twice a second would fight the operator's typing."""

    window.clipboard.value = ANSWER
    window.poll_clipboard()

    drawn = []
    original = window.refresh
    window.refresh = lambda: drawn.append(1)
    try:
        for _ in range(5):
            window.poll_clipboard()
    finally:
        window.refresh = original

    assert drawn == []


def test_a_build_with_no_builder_says_so_rather_than_pretending(window):
    window.video.set("gC-J7zwYMAM")
    window.do_primary()

    assert "No builder" in window.status.get()


def test_the_problems_are_all_reported_at_once(window):
    window.video.set("")
    window.mode.set("reply")
    window.do_primary()

    assert "video" in window.status.get().lower()
