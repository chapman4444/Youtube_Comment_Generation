"""The last check the model reads must restate the first rule it was given.

The workflow's core requirement is that a comment "contribute a conclusion that
is not explicitly or substantially stated in the transcript". The final check
used to close with "none is primarily a summary", which is a different and
weaker test: a twenty-word deadpan restatement of a fact the video states
outright is not *primarily* a summary, so it passed.

The inversion was the sharp part. ``render_final_check`` applied the strong
wording only when some selected register was allowed to waive analysis, and
fell back to the weak wording when every register required it -- so the check
was weakest exactly where the invariant mattered most. The preset that exposed
this in practice, "Dry and sharp", waives nothing.

Both branches are proved here: the strong test when nothing waives, and the
existing per-register exemption when something does.
"""

from __future__ import annotations

from llm_youtube_comment_generation.domain.writing_options import (
    VARIATION_LIBRARY,
    render_final_check,
)

TEMPLATE = (
    "4. Substance: {check_substance} and disputed claims are "
    "attributed.{check_waiver}"
)

NON_WAIVING = ("deadpan", "sardonic", "correction", "numbers_only")
WAIVING = ("deadpan", "summary")


def test_nothing_waiving_demands_a_conclusion_the_video_did_not_state():
    assert all(
        not VARIATION_LIBRARY[key].waives_analysis for key in NON_WAIVING
    )

    check = render_final_check(TEMPLATE, NON_WAIVING)

    assert "contribute something the video did not state" in check


def test_nothing_waiving_no_longer_settles_for_not_primarily_a_summary():
    """The weaker rule must not be what the model reads last."""

    check = render_final_check(TEMPLATE, NON_WAIVING)

    assert "primarily a summary" not in check


def test_the_check_names_restatement_as_the_failure_it_is():
    check = render_final_check(TEMPLATE, NON_WAIVING)

    assert "restating what it did state more sharply" in check


def test_a_waiving_register_is_still_exempted_by_name():
    assert VARIATION_LIBRARY["summary"].waives_analysis is True

    check = render_final_check(TEMPLATE, WAIVING)

    assert "every variation except Summary" in check
    assert "Summary may be exactly what the heading says" in check


def test_a_waiver_never_exempts_the_registers_beside_it():
    check = render_final_check(TEMPLATE, WAIVING)

    assert "Deadpan may be exactly what the heading says" not in check
