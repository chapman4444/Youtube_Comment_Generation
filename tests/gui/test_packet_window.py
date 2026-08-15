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

from llm_youtube_comment_generation.domain.statuses import (
    TranscriptAvailability,
    TranscriptResult,
)
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
from llm_youtube_comment_generation.interfaces.gui.worker import (
    ConfirmationRequest,
    WorkerEvent,
)
from llm_youtube_comment_generation.infrastructure.json_preset_store import (
    JsonPresetStore,
)

VIDEO_URL = "https://www.youtube.com/watch?v=gC-J7zwYMAM"
ANSWER = (
    "# Copy/Paste Replies\n\n"
    "**Post beneath comment ID:** AAA.111\n\n"
    "```text\nThe reply I would send.\n```\n"
)


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


def test_advanced_and_reset_are_in_the_always_visible_top_row(window):
    window.root.geometry("1400x850")
    window.root.update_idletasks()

    assert window.advanced_button.winfo_parent() == str(window.mode_bar)
    assert window.reset_options_button.winfo_parent() == str(window.mode_bar)
    assert window.advanced_button.winfo_manager() == "pack"
    assert window.reset_options_button.winfo_manager() == "pack"
    assert window.advanced_button.winfo_y() >= 0
    assert (
        window.advanced_button.winfo_y()
        + window.advanced_button.winfo_reqheight()
        <= window.mode_bar.winfo_height()
    )


def test_build_stop_and_reset_are_together_beside_the_video(window):
    assert window.build_button.cget("text") == "Build"
    assert window.stop_button.master == window.build_button.master
    assert window.reset_button.master == window.build_button.master
    assert window.build_button.master.master == window.video_url_label.master


def test_debug_build_is_a_one_run_checkbox_beside_build(window):
    assert window.debug_build_check.master == window.build_button.master
    assert window.debug_build.get() is False
    assert any(
        window.output_tabs.tab(tab, "text") == "Debug"
        for tab in window.output_tabs.tabs()
    )


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


def test_replace_works_after_a_packet_has_already_been_built(window):
    window.video.set("gC-J7zwYMAM")
    window.comment_session = object()
    window.last_packet = "the old packet"
    window.clipboard.value = "https://youtu.be/FVG5m_NG5Ak"
    window.poll_clipboard()

    assert window.use_button.cget("text") == "Replace"
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


def test_every_main_workflow_control_has_a_tooltip(window):
    covered = {tooltip.widget for tooltip in window._tooltips}
    controls = {
        window.paste_button,
        window.clear_video_button,
        window.use_button,
        window.build_button,
        window.stop_button,
        window.reset_button,
        window.advanced_button,
        window.reset_options_button,
        window.preset_box,
        window.save_preset_button,
        window.delete_preset_button,
        window.approach_search,
        window.clear_approaches_button,
        window.transcript_api_button,
        window.ytdlp_captions_button,
        window.saved_transcript_button,
        window.run_whisper_button,
        window.packet_copy_button,
        window.answer_input,
        window.primary,
        window.paste_answer_button,
        window.copy_button,
        window.record_button,
        window.back_button,
        window.skip_button,
        window.progress_bar,
    }

    assert controls <= covered


def test_preset_selection_is_immediate_and_has_no_ambiguous_apply_button(window):
    button_text = {
        child.cget("text")
        for child in window.preset_box.master.winfo_children()
        if child.winfo_class() == "TButton"
    }

    assert "Apply" not in button_text
    assert "Save preset..." in button_text


def test_applying_a_preset_reports_how_many_approaches_it_selected(window):
    window.preset_name.set("Concise and direct")
    window.apply_selected_preset()

    assert "3 approaches" in window.status.get()


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
    assert window.copy_button.cget("text") == "Copy packet again"
    assert "20 characters" in window.packet_count.cget("text")
    assert window.packet_preview.get("1.0", "end-1c") == packet
    assert str(window.packet_preview.cget("state")) == "disabled"
    assert "✓ Build" in window.rail_labels[0].cget("text")
    assert "● Answer" in window.rail_labels[1].cget("text")


def test_debug_build_displays_normal_packet_but_copies_diagnostic_packet(window):
    ordinary = "ordinary generated packet"
    diagnostic = "ordinary generated packet\n\n## Debug-build instructions"

    class Session:
        accepted = []
        state = None
        debug_build = True

        def start(self):
            return None

        def copy_packet(self):
            window.clipboard.write(diagnostic)
            return diagnostic

    run = SimpleNamespace(
        text=ordinary,
        model_text=diagnostic,
        debug_packet=diagnostic,
        variations=(),
        run_record={},
        evidence={},
        transcript=None,
        artifacts=None,
    )
    window._comment_session_factory = lambda _packet: Session()

    window._on_event(WorkerEvent("done", "done", run))

    assert window.packet_preview.get("1.0", "end-1c") == ordinary
    assert window.clipboard.value == diagnostic
    assert window.last_packet == diagnostic
    assert window.generated_packet == ordinary
    assert (
        window.output_tabs.tab(window.evidence_tabs["debug"], "text")
        == "Debug packet"
    )
    assert window.evidence_views["debug"].get("1.0", "end-1c") == diagnostic

    window.packet_copy_button.invoke()

    assert window.clipboard.value == ordinary


def test_rejected_debug_answer_replaces_debug_packet_with_completed_bundle(
    window,
):
    diagnostic = "diagnostic packet"

    class Session:
        accepted = []
        debug_build = True
        state = SimpleNamespace(last_error="Two format problems were found.")

        def start(self):
            return None

        def copy_packet(self):
            window.clipboard.write(diagnostic)
            return diagnostic

        def submit(self, _text):
            return SimpleNamespace(
                status=SimpleNamespace(value="refused")
            )

        def debug_bundle(self):
            return "# Debug build bundle\n\nTwo format problems were found."

    run = SimpleNamespace(
        text="ordinary packet",
        model_text=diagnostic,
        debug_packet=diagnostic,
        variations=(),
        run_record={},
        evidence={},
        transcript=None,
        artifacts=None,
    )
    window._comment_session_factory = lambda _packet: Session()
    window._on_event(WorkerEvent("done", "done", run))
    window.answer_input.insert("1.0", "malformed model answer")

    window.take_comment_answer()

    assert (
        window.output_tabs.tab(window.evidence_tabs["debug"], "text")
        == "Debug bundle"
    )
    assert "# Debug build bundle" in window.evidence_views["debug"].get(
        "1.0", "end-1c"
    )


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
    assert window.approach_summary.get() == (
        f"1 of {len(window.approach_vars)} approaches selected."
    )

    window.clear_custom_approaches()

    assert window.options.comment_approach_mode == "default"
    assert window.options.comment_variations == ()


def test_approach_summary_says_when_every_approach_is_selected(window):
    for variable in window.approach_vars.values():
        variable.set(True)

    window._approach_selected()

    assert window.approach_summary.get() == (
        f"All {len(window.approach_vars)} approaches selected."
    )


def test_register_search_preserves_hidden_selections(window):
    window.approach_vars["short_hook"].set(True)
    window._approach_selected()

    window.approach_filter.set("historical")
    window.root.update_idletasks()

    assert "short_hook" not in window.approach_checks
    assert window.approach_vars["short_hook"].get()
    assert window.options.comment_variations == ("short_hook",)


def test_built_in_preset_applies_registers_dials_and_length(window):
    window.preset_name.set("Evidence first")

    window.apply_selected_preset()

    assert "timestamp_callout" in window.options.comment_variations
    assert window.options.dials["humor"] == "none"
    assert window.length.get() == "medium"
    assert window.video.get() == ""


def test_custom_preset_can_be_saved_and_reapplied(tk_root, tmp_path):
    top = tk.Toplevel(tk_root)
    top.withdraw()
    store = JsonPresetStore(tmp_path / "writing_presets.json")
    names = iter(["My saved settings"])
    built = PacketWindow(
        root=top,
        options=PacketOptionsModel(video="gC-J7zwYMAM"),
        clipboard=FakeClipboard(),
        preset_store=store,
        ask_preset_name=lambda: next(names),
        poll=False,
        notify=lambda title, message: None,
    )
    try:
        built.approach_vars["short_hook"].set(True)
        built._approach_selected()
        built.length.set("long")
        built._length_changed()
        built.save_current_preset()

        built.reset_options()
        built.preset_name.set("My saved settings")
        built.apply_selected_preset()

        assert built.options.comment_variations == ("short_hook",)
        assert built.length.get() == "long"
        assert built.options.video == "gC-J7zwYMAM"
        assert store.path.is_file()
    finally:
        top.destroy()


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
        assert built.copy_button.cget("text") in (
            "Copy packet",
            "Copy packet again",
        )
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
            # None means the queue is exhausted, so a live thread must be
            # returned — the window clears the packet otherwise.
            self.current_packet = "reply packet"
            return self.targets[0]

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
    assert window.primary.cget("text") == "Build"
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


def test_reset_returns_the_whole_gui_to_its_opening_state(window):
    window.video.set("gC-J7zwYMAM")
    window.options.comment_variations = ("dry_joke",)
    window.options.dials = {"ending": "flat"}
    window.length.set("long")
    window.last_packet = "old packet"
    window.comment_session = object()
    window._set_evidence_view("description", "old description")
    window._set_text(window.said, "old saved draft")
    window.answer_input.insert("1.0", "old answer")
    window.say("old activity")
    window.output_tabs.select(window.answer_tab)

    window.reset_all()

    assert window.video.get() == ""
    assert window.last_packet == ""
    assert window.comment_session is None
    assert window.options.comment_variations == ()
    assert window.options.dials == {}
    assert window.length.get() == "auto"
    assert window.preset_name.get() == "Default"
    assert window.log.get("1.0", "end-1c") == ""
    assert window._answer_text() == ""
    assert window.said.get("1.0", "end-1c") == "No answer has been saved yet."
    assert window.evidence_views["description"].get("1.0", "end-1c") == ""
    assert window.output_tabs.select() == str(window.activity_tab)
    assert window.status.get() == "Reset complete."


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
    assert window._active_job_generation == -1


def test_stop_button_is_visible_only_during_a_running_build(window):
    class RunningJob:
        running = True
        cancelled = False

        def cancel(self):
            self.cancelled = True

    job = RunningJob()
    window.job = job
    window.video.set("gC-J7zwYMAM")
    window.refresh()

    assert window.stop_button.winfo_manager() == "pack"
    assert str(window.stop_button.cget("state")) == "normal"

    window.stop_button.invoke()

    assert job.cancelled
    assert str(window.stop_button.cget("state")) == "disabled"
    assert "Stopping" in window.status.get()


def test_cancelled_build_clears_progress_and_reports_stopped(window):
    window.progress_value.set(0.8)

    window._on_event(WorkerEvent("cancelled"))

    assert window.progress_value.get() == 0.0
    assert window.status.get() == "Stopped."


@pytest.mark.parametrize(
    "event",
    [
        WorkerEvent("progress", "stale progress", fraction=0.9, generation=1),
        WorkerEvent("done", "stale done", value="wrong", generation=1),
        WorkerEvent("failed", "stale failure", generation=1),
        WorkerEvent("cancelled", "stale cancellation", generation=1),
    ],
)
def test_stale_job_events_cannot_change_the_current_build(window, event):
    window._active_job_generation = 2
    window.progress_value.set(0.2)
    window.status.set("current build")
    window.result = "current result"

    window._on_event(event)

    assert window.progress_value.get() == 0.2
    assert window.status.get() == "current build"
    assert window.result == "current result"


def test_stale_confirmation_is_declined_without_opening_a_dialog(window):
    shown = []
    window._confirm_whisper = lambda reason: shown.append(reason) or True
    window._active_job_generation = 2
    request = ConfirmationRequest("old job")

    window._on_event(WorkerEvent(
        "confirmation",
        value=request,
        generation=1,
    ))

    assert request.answered.is_set()
    assert not request.accepted
    assert shown == []


def test_close_cancels_and_resolves_confirmation_before_destroying_tk():
    request = ConfirmationRequest("waiting")

    class Job:
        running = True
        cancelled = False

        def drain(self):
            return [WorkerEvent("confirmation", value=request, generation=1)]

        def cancel(self):
            self.cancelled = True

    class Root:
        destroyed = False
        callback = None

        def geometry(self):
            return "1000x700+0+0"

        def after(self, _milliseconds, callback):
            self.callback = callback

        def destroy(self):
            self.destroyed = True

    root = Root()
    job = Job()
    built = object.__new__(PacketWindow)
    built.root = root
    built.job = job
    built.options = SimpleNamespace(window_geometry="")
    built.status = SimpleNamespace(set=lambda _message: None)
    built._active_job_generation = 1

    built.close()

    assert job.cancelled
    assert request.answered.is_set()
    assert not request.accepted
    assert not root.destroyed

    job.running = False
    root.callback()

    assert root.destroyed


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


def test_activity_is_the_default_output_tab(window):
    selected = window.output_tabs.select()

    assert window.output_tabs.tab(selected, "text") == "Activity"
    assert window.log.winfo_manager() == "grid"


def test_tab_text_views_have_a_right_click_copy_menu(window):
    views = (
        window.log,
        window.packet_preview,
        window.transcript_preview,
        window.answer_input,
        *window.evidence_views.values(),
    )

    assert all(view.bind("<Button-3>") for view in views)


def test_mouse_wheel_is_bound_to_the_approach_children(window):
    assert window.approach_checks
    assert all(
        check.bind("<MouseWheel>")
        for check in window.approach_checks.values()
    )


def test_mouse_wheel_moves_the_approach_list(window):
    window.root.update_idletasks()
    window.approach_canvas.yview_moveto(0)
    before = window.approach_canvas.yview()

    result = window._scroll_approaches(
        SimpleNamespace(delta=-120, num=0)
    )

    after = window.approach_canvas.yview()
    assert result == "break"
    assert after[0] > before[0]


def test_retrieved_elements_have_separate_tabs_and_copy_buttons(window):
    window._show_evidence({
        "video": {
            "video_id": "gC-J7zwYMAM",
            "title": "A video",
            "description": "Description text",
        },
        "comments": [{"comment_id": "c1", "text": "A comment"}],
        "replies": [{
            "comment_id": "r1",
            "parent_comment_id": "c1",
            "text": "A reply",
        }],
    })

    assert "Title: A video" in window.evidence_views["metadata"].get(
        "1.0", "end"
    )
    assert "Description text" in window.evidence_views["description"].get(
        "1.0", "end"
    )
    assert "A comment" in window.evidence_views["comments"].get("1.0", "end")
    assert "A reply" in window.evidence_views["replies"].get("1.0", "end")

    window.copy_evidence("description")

    assert window.clipboard.value == "Description text"


def test_manual_transcript_buttons_force_one_source_only(window):
    requested = []
    window.video.set("gC-J7zwYMAM")
    window._start_packet_build = (
        lambda options, force=False: requested.append((options, force))
    )

    for button in (
        window.transcript_api_button,
        window.ytdlp_captions_button,
        window.saved_transcript_button,
        window.run_whisper_button,
    ):
        button.configure(state="normal")
        button.invoke()

    assert [options.transcript_route for options, _force in requested] == [
        "api",
        "ytdlp",
        "saved",
        "whisper",
    ]
    assert all(force for _options, force in requested)
    assert window.options.transcript_route == "automatic"


def test_progress_is_a_label_not_a_log_checkbox(window):
    bottom = window.root.winfo_children()[-1]
    bottom_text = [
        str(child.cget("text"))
        for child in bottom.winfo_children()
        if "text" in child.keys()
    ]

    assert "Progress:" in bottom_text
    assert not hasattr(window, "log_open")


def test_transcript_confirmation_shows_reason_and_records_answer(window):
    shown = []
    window._confirm_whisper = lambda reason: shown.append(reason) or True
    request = ConfirmationRequest(TranscriptResult(
        availability=TranscriptAvailability.NOT_PUBLISHED,
        detail="no caption tracks were published",
    ))

    window._on_event(WorkerEvent("confirmation", value=request))

    assert request.answered.is_set()
    assert request.accepted
    assert shown and "No transcript was published" in shown[0]
    assert "Whisper was approved" in window.transcript_notice.get()


def test_live_whisper_segments_appear_in_the_transcript_tab(window):
    window._on_event(WorkerEvent(
        "progress",
        value={
            "step": "transcribe",
            "data": {
                "transcript_entry": {
                    "text": "the first completed segment",
                    "start": 12.0,
                    "end": 16.0,
                },
                "eta_seconds": 75.0,
            },
        },
        fraction=0.8,
    ))

    assert "the first completed segment" in window.transcript_preview.get(
        "1.0", "end"
    )
    assert "1:15 remaining" in window.transcript_notice.get()
    assert window.output_tabs.select() == str(window.transcript_tab)


def test_missing_transcript_uses_the_red_status_indicator(window):
    window._show_transcript(TranscriptResult(
        availability=TranscriptAvailability.FETCH_FAILED,
        detail="IpBlocked",
    ))

    assert "blocked or failed" in window.transcript_notice.get()
    assert str(window.transcript_indicator.cget("foreground")) == "#b42318"


def test_changing_video_reenables_build_without_discarding_old_packet(window):
    window.video.set("gC-J7zwYMAM")
    window.comment_session = SimpleNamespace(accepted=[])
    window.last_packet = "old packet"
    window._completed_build_signature = window._build_signature(
        window.gather(),
        "comment",
    )
    window.refresh()

    assert str(window.build_button.cget("state")) == "disabled"

    window.video.set("FVG5m_NG5Ak")
    window.refresh()

    assert str(window.build_button.cget("state")) == "normal"
    assert window.last_packet == "old packet"
    assert "settings changed" in window.status.get()


def test_changing_advanced_settings_reenables_build(window):
    window.video.set("gC-J7zwYMAM")
    window.comment_session = SimpleNamespace(accepted=[])
    window._completed_build_signature = window._build_signature(
        window.gather(),
        "comment",
    )

    window.options.max_recent += 1
    window.refresh()

    assert str(window.build_button.cget("state")) == "normal"


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


def test_a_visible_pasted_answer_works_without_clipboard_detection(window):
    submitted = []

    class Session:
        accepted: list = []
        state = SimpleNamespace(last_error="")

        def submit(self, text):
            submitted.append(text)
            self.accepted.append(
                SimpleNamespace(draft="The reply I would send.")
            )
            return SimpleNamespace(status=SimpleNamespace(value="ok"))

        def finish(self):
            return None

    window.comment_session = Session()
    window.video.set("gC-J7zwYMAM")
    window.answer_input.insert("1.0", ANSWER)
    window.refresh()

    assert str(window.primary.cget("state")) == "normal"
    assert window.primary.cget("text") == "Validate and save answer"
    assert "Click Validate and save answer" in window.card_detail.cget("text")

    window.take_comment_answer()

    assert submitted == [ANSWER.strip()]
    assert window._answer_text() == ""
    assert (
        window.said.get("1.0", "end-1c")
        == "The reply I would send."
    )
    assert "Nothing was posted" in window.status.get()


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


# --------------------------------------------------------------------------
# A refused answer has to be visible where the result is read
#
# Validation reported a refusal only in the status bar along the bottom edge,
# while the saved-draft panel kept saying "No answer has been saved yet."
# Both were true, and together they read as a dead button: the panel that
# reports what pressing it achieved said nothing had happened, and the reason
# sat in the least prominent strip of the window. The button was working and
# the explanation was still missed.
# --------------------------------------------------------------------------

REFUSAL = (
    "The Video line must contain the YouTube URL exactly once as plain "
    "text; found 2 copies. Do not wrap it in Markdown brackets, "
    "parentheses, or link syntax."
)


def refusing_session():
    class Session:
        accepted: list = []
        state = SimpleNamespace(last_error=REFUSAL)

        def submit(self, text):
            return SimpleNamespace(status=SimpleNamespace(value="refused"))

        def finish(self):
            return None

    return Session()


def test_a_refused_comment_answer_says_so_in_the_draft_panel(window):
    window.comment_session = refusing_session()
    window.video.set("gC-J7zwYMAM")
    window.answer_input.insert("1.0", ANSWER)

    window.take_comment_answer()

    panel = window.said.get("1.0", "end-1c")
    assert "Not saved" in panel, "the panel does not report the refusal at all"
    assert "exactly once as plain text" in panel, (
        "the panel does not say why the answer was refused"
    )
    assert panel != "No answer has been saved yet.", (
        "a refusal still reads as though the button did nothing"
    )


def test_a_refused_comment_answer_still_reaches_the_status_bar(window):
    """The status bar keeps its message; the panel is added, not swapped."""

    window.comment_session = refusing_session()
    window.video.set("gC-J7zwYMAM")
    window.answer_input.insert("1.0", ANSWER)

    window.take_comment_answer()

    assert "exactly once as plain text" in window.status.get()


def test_a_refused_answer_does_not_discard_what_was_pasted(window):
    """The text must survive so the operator can correct it in place."""

    window.comment_session = refusing_session()
    window.video.set("gC-J7zwYMAM")
    window.answer_input.insert("1.0", ANSWER)

    window.take_comment_answer()

    assert window._answer_text() == ANSWER.strip()


def test_a_saved_answer_replaces_an_earlier_refusal_in_the_panel(window):
    """The panel must not keep showing a refusal that no longer applies."""

    window.comment_session = refusing_session()
    window.video.set("gC-J7zwYMAM")
    window.answer_input.insert("1.0", ANSWER)
    window.take_comment_answer()
    assert "Not saved" in window.said.get("1.0", "end-1c")

    class Accepting:
        accepted: list = []
        state = SimpleNamespace(last_error="")

        def submit(self, text):
            self.accepted.append(SimpleNamespace(draft="The saved comment."))
            return SimpleNamespace(status=SimpleNamespace(value="ok"))

        def finish(self):
            return None

    window.comment_session = Accepting()
    window.answer_input.insert("1.0", ANSWER)
    window.take_comment_answer()

    assert window.said.get("1.0", "end-1c") == "The saved comment."


# -- the reply face: the old application's tab, restored -------------------


def test_the_reply_face_shows_the_numbered_steps(window):
    """The operator's screenshot: username on the face, then 1-4 in a
    "Do these in order" panel, then recovery buttons. Every button drives
    the session machinery; none is decoration."""

    for key in ("build", "copy_triage", "paste_triage", "copy_reply",
                "paste_reply", "open_finished", "skip", "start_over",
                "open_so_far", "open_packet", "find"):
        assert key in window.reply_step_buttons, key
    assert window.reply_step_buttons["build"].cget("text") \
        == "Build and find who needs a reply"
    assert window.reply_step_buttons["open_finished"].cget("text") \
        == "Open the finished replies"
    assert "Press 1 to begin." in window.reply_face_hint.get()


def test_the_reply_face_appears_only_in_reply_mode(window):
    window.mode.set("comment")
    window._mode_changed()
    assert window.reply_face.grid_info() == {}

    window.mode.set("reply")
    window._mode_changed()
    assert window.reply_face.grid_info() != {}


def test_the_username_field_writes_the_shared_setting(window):
    window.my_handle_var.set("@goss4444")

    assert window.options.my_handle == "@goss4444"


def test_no_control_advertises_unfinished_work(window):
    """A disabled control whose tooltip says "still being ported" is a
    promise the window cannot keep. Controls appear when they work."""

    import pathlib

    source = pathlib.Path(
        window.__class__.__module__.replace(".", "/") + ".py")
    if not source.exists():                       # installed layout
        import llm_youtube_comment_generation.interfaces.gui.packet_window \
            as module
        source = pathlib.Path(module.__file__)
    text = source.read_text(encoding="utf-8")

    for phrase in ("still being ported", "Not restored yet",
                   "not restored yet", "coming soon"):
        assert phrase not in text, phrase


def test_nothing_on_the_reply_face_advances_without_a_press(window):
    """Wired and removed the same day at the operator's direction. The
    checkboxes are gone and no code path submits an answer or starts a
    build off the clipboard poll."""

    assert not hasattr(window, "auto_run_var")
    assert not hasattr(window, "auto_watch_var")
    assert not hasattr(window, "_maybe_auto_advance")


def test_step_buttons_follow_the_sequence(window):
    """Step 2 and 3 buttons are dead until their step is in front of you."""

    window.mode.set("reply")
    window._mode_changed()
    window.refresh()

    assert str(window.reply_step_buttons["copy_triage"].cget("state")) \
        == "disabled"
    assert str(window.reply_step_buttons["paste_reply"].cget("state")) \
        == "disabled"
    assert str(window.reply_step_buttons["build"].cget("state")) == "normal"


def test_choosing_a_person_from_the_list_fills_answer_one(window):
    window.reply_people_box["values"] = ("@alice", "@bob")
    window.reply_people_box.set("@bob")
    window._person_chosen_from_list()

    assert window.answer_one_var.get() == "@bob"


def test_triage_keeps_the_whole_thread_of_a_chosen_person(window):
    """The second review's probe: choosing Alice while Bob shares her
    thread must keep Bob — the packet answers the thread whole — and the
    window must say so instead of labelling it a one-person run."""

    from fakes import FakeArtifactStore, FakeClipboard, FakeEventSink
    from llm_youtube_comment_generation.application.guided_session import (
        GuidedSession,
    )
    from llm_youtube_comment_generation.domain.candidates import (
        build_reply_candidates,
    )
    from llm_youtube_comment_generation.domain.threads import OwnerThread
    from llm_youtube_comment_generation.infrastructure import prompt_resources

    owner = "UC" + "o" * 22

    def msg(cid, author, text, channel=None):
        return {
            "comment_id": cid, "author": author, "text": text,
            "author_channel_id": channel
            or ("UC" + author.lstrip("@").ljust(22, "z"))[:24],
            "like_count": 0, "published_at": "2026-07-02T00:00:00Z",
        }

    replies = [
        msg("r1", "@alice", "a challenge"),
        msg("r2", "@bob", "a separate question"),
    ]
    thread = OwnerThread(
        comment=msg("mine", "@owner", "my comment", owner), replies=replies)
    window.session = GuidedSession(
        targets=build_reply_candidates(owner, "@owner", replies, "mine"),
        threads={"mine": thread},
        owner_channel_id=owner,
        video={"video_id": "gC-J7zwYMAM", "title": "A video"},
        templates={
            "reply_workflow.md":
                prompt_resources.load("reply_workflow.md").text,
            "reply_final_check.md":
                prompt_resources.load("reply_final_check.md").text,
        },
        artifacts=FakeArtifactStore(), clipboard=FakeClipboard(),
        events=FakeEventSink(),
    )
    window.mode.set("reply")
    window._mode_changed()
    window.sequence.people = ("@alice", "@bob")
    window.sequence.advance_to(Step.TRIAGE)
    window.answer_input.insert("1.0", "@alice | 1 | worth answering\n")

    window.take_triage()

    assert {t.author for t in window.session.targets} == {"@alice", "@bob"}
    assert "answered whole" in window.status.get() \
        or "covering 2 people" in window.status.get()
