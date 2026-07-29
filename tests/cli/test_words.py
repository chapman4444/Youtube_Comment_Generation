"""The words command at the command line.

There was no test here at all when it shipped, which is the same gap that let
`reply triage` report three candidates for a packet listing one. The domain
was covered and the command was not, so nothing checked that the numbers the
operator reads describe the table printed above them.
"""

from __future__ import annotations

import io

import pytest

from llm_youtube_comment_generation.interfaces.cli.main import main

TRANSCRIPT = "\n".join([
    "[00:00:00] >> The shotgun question came up again, and again.",
    "[00:00:04] >> [music] The shotgun is the part that matters here.",
    "[00:00:09] >> Police opened a criminal case about the shotgun.",
    "[00:00:14] >> Police said the criminal case was closed. [laughter]",
])


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, stdout=out, stderr=err,
                environment={"YOUTUBE_API_KEY": "test-key"})
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def transcript(tmp_path):
    path = tmp_path / "transcript_timestamped.txt"
    path.write_text(TRANSCRIPT, encoding="utf-8")
    return path


def counts_in(out):
    """The word/count pairs printed in the table."""

    rows = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].replace(",", "").isdigit():
            rows[parts[0]] = int(parts[1].replace(",", ""))
    return rows


def test_a_transcript_file_is_counted(transcript):
    code, out, _ = run(["words", str(transcript)])

    assert code == 0
    assert counts_in(out)["shotgun"] == 3
    assert counts_in(out)["police"] == 2


def test_a_run_directory_is_accepted_rather_than_the_file_inside_it(tmp_path):
    """Every run writes the transcript beside its packet."""

    (tmp_path / "transcript_timestamped.txt").write_text(
        TRANSCRIPT, encoding="utf-8")

    code, out, _ = run(["words", str(tmp_path)])

    assert code == 0
    assert "shotgun" in out


def test_the_timestamped_transcript_wins_over_the_plain_one(tmp_path):
    """A legacy run directory holds both. Globbing picked plain by accident."""

    (tmp_path / "transcript_timestamped.txt").write_text(
        TRANSCRIPT, encoding="utf-8")
    (tmp_path / "transcript_plain.txt").write_text(
        "[00:00:00] zebra zebra zebra", encoding="utf-8")

    _, out, _ = run(["words", str(tmp_path)])

    assert "transcript_timestamped.txt" in out
    assert "zebra" not in out


def test_caption_annotations_never_reach_the_table(transcript):
    _, out, _ = run(["words", str(transcript)])

    assert "music" not in counts_in(out)
    assert "laughter" not in counts_in(out)


# -- the numbers must describe the table -----------------------------------


def test_the_totals_reconcile_with_the_rows(transcript):
    _, out, _ = run(["words", str(transcript), "--top", "0"])

    rows = counts_in(out)
    total = int(out.split(" tokens")[0].split("\n")[-1].replace(",", ""))
    removed = int(out.split(" removed as filler")[0].split(", ")[-1]
                  .replace(",", ""))

    assert sum(rows.values()) + removed == total


def test_the_totals_still_reconcile_when_min_count_drops_rows(transcript):
    """The CLI used to filter the rows after the removed figure was computed,
    so a --min-count run printed a removed count for a table it no longer
    described."""

    _, out, _ = run(["words", str(transcript), "--top", "0",
                     "--min-count", "2"])

    rows = counts_in(out)
    total = int(out.split(" tokens")[0].split("\n")[-1].replace(",", ""))
    removed = int(out.split(" removed as filler")[0].split(", ")[-1]
                  .replace(",", ""))

    assert all(count >= 2 for count in rows.values())
    assert sum(rows.values()) + removed == total


def test_a_truncated_table_reports_the_whole_count(transcript):
    _, out, _ = run(["words", str(transcript), "--top", "1"])

    assert "Showing 1 of" in out
    assert "1 distinct keywords" not in out


# -- refusals --------------------------------------------------------------


def test_a_negative_top_shows_everything_like_zero_does(transcript):
    """It already behaved this way and the help text said only "0 for all"."""

    _, zero, _ = run(["words", str(transcript), "--top", "0"])
    _, negative, _ = run(["words", str(transcript), "--top", "-5"])

    assert counts_in(zero) == counts_in(negative)
    assert "Showing" not in negative


def test_a_directory_with_no_transcript_says_what_it_wanted(tmp_path):
    code, _, err = run(["words", str(tmp_path)])

    assert code != 0
    assert "transcript_timestamped.txt" in err


def test_a_missing_path_is_an_error_not_an_empty_table(tmp_path):
    code, out, err = run(["words", str(tmp_path / "nope.txt")])

    assert code != 0
    assert "No transcript" in err
    assert "tokens" not in out


def test_the_word_lists_can_be_listed(tmp_path):
    code, out, _ = run(["words", str(tmp_path), "--list-wordlists"])

    assert code == 0
    assert "omit_words.txt" in out
    assert "spoken_extra.txt" in out


def test_an_unknown_word_list_names_the_ones_that_exist(transcript):
    code, _, err = run(["words", str(transcript), "--stopwords", "nope.txt"])

    assert code != 0
    assert "omit_words.txt" in err
