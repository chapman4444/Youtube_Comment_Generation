"""Diagnosing a run from its artifacts alone.

That phrase is Phase 9's acceptance criterion, so these tests are written as
the questions an operator asks when something went wrong.
"""

from __future__ import annotations

import json
import hashlib

import pytest

from llm_youtube_comment_generation.application.runs import (
    _check_transcript_provenance,
    list_runs,
    render_list,
    render_validation,
    validate_run,
)

PROVENANCE = {
    "availability": "available",
    "source": "youtube-transcript-api",
    "immediate_source": "youtube-transcript-api",
    "original_source": "youtube-transcript-api",
    "is_generated": False,
    "language": "English",
    "language_code": "en",
    "entries": 1,
    "detail": "",
    "originating_run": "",
    "attempts": [],
}


def make_run(root, name="gC-J7zwYMAM_20260727-120000", *, packet="x" * 500,
             run=None, omit=(), empty=()):
    directory = root / name
    directory.mkdir(parents=True)
    record = {
        "video_id": "gC-J7zwYMAM",
        "video_title": "A video",
        "prompt_version": "e8a7d359ad50",
        "packet_characters": len(packet),
        "budget": 280_000,
        "variations": ["short_hook", "dry_joke"],
        "variation_headings": ["### 1. Short hook", "### 2. Dry joke",
                               "### Harsh critique", "### Hardened final"],
        "retrieval": {"status": "complete", "may_conclude_absence": True},
    }
    if run is not None:
        record.update(run)

    files = {
        "packet.md": packet,
        "run.json": json.dumps(record, indent=2),
        "report.md": "# report\n",
        "evidence.json": "{}",
        "transcript_timestamped.txt": "[00:00:00] words",
    }
    for name_, content in files.items():
        if name_ in omit:
            continue
        (directory / name_).write_text(
            "" if name_ in empty else content, encoding="utf-8"
        )
    return directory


def make_reply_run(root, *, packet_name="reply_packet.md", omit=()):
    """A reply or triage run with the producer's full six-file set."""

    directory = root / f"{packet_name.split('.')[0]}_20260813-120000"
    directory.mkdir(parents=True)
    files = {
        packet_name: "x" * 500,
        "run.json": json.dumps({
            "kind": "triage" if "triage" in packet_name else "reply",
            "video_id": "gC-J7zwYMAM",
            "video_title": "A video",
            "prompt_version": "e8a7d359ad50",
        }, indent=2),
        "evidence.json": "{}",
        "transcript_timestamped.txt": "[00:00:00] words",
        "replies_to_me.csv": "comment_id,text\r\nr1,hello\r\n",
        "report.md": "# report\n",
    }
    for name, content in files.items():
        if name not in omit:
            (directory / name).write_text(content, encoding="utf-8")
    return directory


def test_a_complete_reply_run_validates(tmp_path):
    summary = validate_run(make_reply_run(tmp_path))

    assert summary.kind == "reply"
    assert not [p for p in summary.problems if p.startswith("missing")]


def test_a_complete_triage_run_validates(tmp_path):
    summary = validate_run(
        make_reply_run(tmp_path, packet_name="reply_triage_packet.md"))

    assert summary.kind == "triage"
    assert not [p for p in summary.problems if p.startswith("missing")]


@pytest.mark.parametrize("missing", [
    "evidence.json", "transcript_timestamped.txt", "replies_to_me.csv",
    "report.md",
])
def test_a_reply_run_missing_a_required_artifact_is_named(tmp_path, missing):
    """The producer refuses to commit without these; a validator that
    blessed their absence was not a gate."""

    summary = validate_run(make_reply_run(tmp_path, omit=(missing,)))

    assert f"missing {missing}" in summary.problems


def test_an_engage_run_is_a_run_this_tool_produced(tmp_path):
    """Both post-batch command families were absent from the classifier, so
    their complete runs validated as 'not a run this tool produced'."""

    directory = tmp_path / "gC-J7zwYMAM_20260815-120000"
    directory.mkdir(parents=True)
    (directory / "engage_packet.md").write_text("x" * 400, encoding="utf-8")
    (directory / "transcript_timestamped.txt").write_text(
        "[00:00:00] words", encoding="utf-8")
    (directory / "run.json").write_text(json.dumps({
        "kind": "engage", "video_id": "gC-J7zwYMAM",
        "prompt_version": "e8a7d359ad50",
    }), encoding="utf-8")

    summary = validate_run(directory)

    assert summary.kind == "engage"
    assert not any("not a run" in p for p in summary.problems)
    assert not any(p.startswith("missing") for p in summary.problems)


def test_a_section_triage_run_is_recognised(tmp_path):
    directory = tmp_path / "gC-J7zwYMAM_20260815-120001"
    directory.mkdir(parents=True)
    (directory / "section_triage_packet.md").write_text(
        "x" * 400, encoding="utf-8")
    (directory / "run.json").write_text(json.dumps({
        "kind": "section_triage", "video_id": "gC-J7zwYMAM",
        "prompt_version": "e8a7d359ad50",
    }), encoding="utf-8")

    summary = validate_run(directory)

    assert summary.kind == "section_triage"
    assert not any("not a run" in p for p in summary.problems)


def test_a_healthy_run_reports_no_problems(tmp_path):
    summary = validate_run(make_run(tmp_path))

    assert summary.ok
    assert summary.kind == "comment"
    assert summary.video_title == "A video"
    assert summary.prompt_version == "e8a7d359ad50"


def test_recorded_rebuild_kind_wins_over_packet_filename(tmp_path):
    summary = validate_run(make_run(tmp_path, run={"kind": "rebuild"}))

    assert summary.kind == "rebuild"
    assert summary.ok


def test_version_two_run_requires_a_completion_record(tmp_path):
    summary = validate_run(make_run(
        tmp_path, run={"artifact_contract_version": 2},
    ))

    assert any("not fully published" in problem
               for problem in summary.problems)


def test_version_two_run_validates_completion_hashes(tmp_path):
    directory = make_run(tmp_path, run={"artifact_contract_version": 2})
    files = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.iterdir()
        if path.is_file()
    }
    (directory / ".artifacts-complete.json").write_text(
        json.dumps({"version": 1, "files": files}),
        encoding="utf-8",
    )

    assert validate_run(directory).ok

    (directory / "packet.md").write_text("changed", encoding="utf-8")
    summary = validate_run(directory)

    assert any("does not match" in problem for problem in summary.problems)


def test_version_three_transcript_provenance_is_internally_validated():
    assert _check_transcript_provenance(PROVENANCE) == []

    broken = dict(
        PROVENANCE,
        source="saved-transcript",
        immediate_source="youtube-transcript-api",
        is_generated="unknown",
        originating_run="",
    )
    problems = _check_transcript_provenance(broken)

    assert any("source and immediate_source disagree" in p for p in problems)
    assert any("is_generated" in p for p in problems)
    assert any("originating_run" in p for p in problems)


def test_a_missing_artifact_is_named(tmp_path):
    summary = validate_run(make_run(tmp_path, omit=("report.md",)))

    assert not summary.ok
    assert "missing report.md" in summary.problems


def test_an_empty_artifact_is_a_problem(tmp_path):
    """An interrupted write leaves a file that exists and says nothing."""

    summary = validate_run(make_run(tmp_path, empty=("packet.md",)))

    assert "packet.md is empty" in summary.problems


def test_a_supported_no_transcript_run_accepts_its_empty_transcript(tmp_path):
    summary = validate_run(make_run(
        tmp_path,
        run={"transcript": {"availability": "not_published", "entries": 0}},
        empty=("transcript_timestamped.txt",),
    ))

    assert summary.ok
    assert "transcript_timestamped.txt is empty" not in summary.problems


def test_an_available_transcript_may_not_have_an_empty_artifact(tmp_path):
    summary = validate_run(make_run(
        tmp_path,
        run={"transcript": {"availability": "available", "entries": 3}},
        empty=("transcript_timestamped.txt",),
    ))

    assert "transcript_timestamped.txt is empty" in summary.problems


@pytest.mark.parametrize("field", ("packet_characters", "budget"))
@pytest.mark.parametrize("value", ("unknown", "++1", "1" * 5000, None, [], {}))
def test_malformed_numeric_fields_are_named_instead_of_raised(
    tmp_path, field, value,
):
    summary = validate_run(make_run(tmp_path, run={field: value}))

    assert any(field in problem for problem in summary.problems)


def test_malformed_transcript_availability_is_reported_as_empty_not_raised(
    tmp_path,
):
    summary = validate_run(make_run(
        tmp_path,
        run={"transcript": {"availability": []}},
        empty=("transcript_timestamped.txt",),
    ))

    assert "transcript_timestamped.txt is empty" in summary.problems


def test_one_malformed_record_does_not_suppress_healthy_runs(tmp_path):
    make_run(tmp_path, "healthy_20260727-120000")
    make_run(
        tmp_path,
        "malformed_20260727-110000",
        run={"packet_characters": {"not": "a number"}},
    )

    summaries = list_runs(tmp_path)
    text = render_list(summaries)

    assert len(summaries) == 2
    assert any(summary.ok for summary in summaries)
    assert any("packet_characters" in problem
               for summary in summaries for problem in summary.problems)
    assert "ok healthy" in text
    assert "!! malformed" in text


def test_a_packet_that_does_not_match_its_record_is_caught(tmp_path):
    """The record and the artifact disagreeing means one of them is lying."""

    summary = validate_run(make_run(
        tmp_path, packet="x" * 500, run={"packet_characters": 999_999}
    ))

    assert any("says the packet is 999,999" in p for p in summary.problems)


def test_a_packet_over_its_own_budget_is_caught(tmp_path):
    summary = validate_run(make_run(
        tmp_path, packet="x" * 5000, run={"budget": 1000}
    ))

    assert any("over the 1,000 budget" in p for p in summary.problems)


def test_a_run_claiming_absence_from_an_incomplete_scan_is_caught(tmp_path):
    """The two cannot both be true, and the combination is the exact defect
    a live run produced in Phase 3."""

    summary = validate_run(make_run(tmp_path, run={
        "retrieval": {"status": "top_level_truncated",
                      "may_conclude_absence": True},
    }))

    assert any("cannot both be true" in p for p in summary.problems)


def test_a_contract_that_disagreed_with_itself_is_caught(tmp_path):
    """Two registers must produce four headings. Anything else means the
    packet asked for one thing and checked for another."""

    summary = validate_run(make_run(tmp_path, run={
        "variations": ["short_hook", "dry_joke"],
        "variation_headings": ["### 1. Short hook", "### Harsh critique",
                               "### Hardened final"],
    }))

    assert any("disagreed with itself" in p for p in summary.problems)


def test_a_run_with_no_prompt_version_cannot_be_attributed(tmp_path):
    summary = validate_run(make_run(tmp_path, run={"prompt_version": ""}))

    assert any("cannot be attributed" in p for p in summary.problems)


def test_unparseable_run_json_is_reported_rather_than_raised(tmp_path):
    directory = make_run(tmp_path)
    (directory / "run.json").write_text("{ not json", encoding="utf-8")

    summary = validate_run(directory)

    assert any("not valid JSON" in p for p in summary.problems)


def test_a_directory_that_is_not_a_run_says_so(tmp_path):
    stray = tmp_path / "holiday_photos"
    stray.mkdir()
    (stray / "beach.txt").write_text("x", encoding="utf-8")

    summary = validate_run(stray)

    assert any("not a run this tool produced" in p for p in summary.problems)


def test_a_missing_directory_is_reported_not_raised(tmp_path):
    summary = validate_run(tmp_path / "nothing_here")

    assert not summary.ok
    assert any("not a directory" in p for p in summary.problems)


def test_a_guided_run_is_recognised_by_its_review_file(tmp_path):
    directory = tmp_path / "run"
    directory.mkdir()
    (directory / "replies_to_review.md").write_text("# replies\n",
                                                    encoding="utf-8")
    (directory / "run.json").write_text(
        json.dumps({"kind": "guided", "video_id": "gC-J7zwYMAM",
                    "prompt_version": "e8a7d359ad50"}),
        encoding="utf-8",
    )

    summary = validate_run(directory)

    assert summary.kind == "guided"
    assert summary.ok


def test_a_run_of_any_kind_without_its_record_is_a_finding(tmp_path):
    """run.json is required of every kind, not just comment runs.

    Without it a run is a directory of markdown with no way to say which
    prompt version produced it — which is the first question asked when
    something looks wrong.
    """

    directory = tmp_path / "run"
    directory.mkdir()
    (directory / "reply_packet.md").write_text("# packet\n", encoding="utf-8")

    summary = validate_run(directory)

    assert summary.kind == "reply"
    assert "missing run.json" in summary.problems


def test_runs_are_listed_newest_first(tmp_path):
    make_run(tmp_path, "gC-J7zwYMAM_20260727-100000")
    make_run(tmp_path, "gC-J7zwYMAM_20260727-120000")

    summaries = list_runs(tmp_path)

    assert [s.directory.split("_")[-1] for s in summaries] == \
           ["20260727-120000", "20260727-100000"]


def test_the_listing_shows_which_runs_are_broken(tmp_path):
    make_run(tmp_path, "good_20260727-120000")
    make_run(tmp_path, "bad_20260727-110000", omit=("packet.md", "run.json"))

    text = render_list(list_runs(tmp_path))

    assert "ok good" in text
    assert "!! bad" in text


def test_validation_output_names_every_problem(tmp_path):
    summary = validate_run(make_run(tmp_path, omit=("report.md",),
                                    empty=("evidence.json",)))

    text = render_validation(summary)

    assert "missing report.md" in text
    assert "evidence.json is empty" in text
    assert "2 problems" in text


def test_an_empty_root_lists_nothing_without_failing(tmp_path):
    assert list_runs(tmp_path) == []
    assert render_list([]) == "No runs found."
