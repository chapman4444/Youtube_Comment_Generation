"""`doctor` has to describe the whole transcript stack, not a quarter of it.

It said "transcript library: installed" while there were four ways to get the
words -- the scrape endpoint, yt-dlp's player API, this machine's saved
copies, and transcribing the audio here. Answering a quarter of the question
is worse than answering none, because it reads like the whole answer: an
operator whose scrape endpoint is blocked would see "installed" and conclude
the problem was elsewhere.

`doctor` is run when something is wrong, so it must never be the thing that
also breaks. Every check here is also a check that it still exits 0.
"""

from __future__ import annotations

import io
import sys

import pytest

import llm_youtube_comment_generation.interfaces.cli.main  # noqa: F401

CLI = sys.modules["llm_youtube_comment_generation.interfaces.cli.main"]

from llm_youtube_comment_generation.application.configuration import resolve


@pytest.fixture(autouse=True)
def installed_whisper_library(monkeypatch):
    """These cases test the on/off setting, not optional-package discovery."""

    from llm_youtube_comment_generation.infrastructure import whisper_transcript

    monkeypatch.setattr(whisper_transcript, "library_available", lambda: True)


def report(tmp_path, **flags):
    configuration = resolve(
        flags={"output_directory": str(tmp_path), **flags})
    stream = io.StringIO()
    code = CLI.run_doctor(configuration, "a-key", stream)
    return code, stream.getvalue()


# -- every source is named -------------------------------------------------


@pytest.mark.parametrize("source", ["scrape", "yt-dlp", "whisper", "saved"])
def test_each_transcript_source_gets_its_own_line(tmp_path, source):
    _code, printed = report(tmp_path)

    assert f"transcript: {source}" in printed


def test_it_still_exits_zero(tmp_path):
    """It reports; it does not judge. A missing optional library is a fact,
    and the application works without it."""

    code, _printed = report(tmp_path)

    assert code == 0


# -- whisper: installed and switched on are different facts ----------------


def test_whisper_off_says_how_to_turn_it_on(tmp_path):
    """Reporting only "installed" leaves an operator concluding his setting
    is broken; reporting only "off" leaves him installing what he has."""

    _code, printed = report(tmp_path)

    assert "off" in printed
    assert "--transcribe" in printed
    assert "YTCOMMENT_TRANSCRIBE_LOCALLY" in printed


def test_whisper_on_says_what_it_will_cost(tmp_path):
    """Minutes of CPU per video is not a surprise anybody should get from a
    packet build."""

    _code, printed = report(tmp_path, transcribe_locally=True)

    assert "on (" in printed
    assert "minutes of CPU" in printed
    assert "limit 60 minutes / 200 MiB" in printed


def test_the_chosen_model_is_named_either_way(tmp_path):
    for flags in ({}, {"transcribe_locally": True}):
        _code, printed = report(tmp_path, whisper_model="medium.en", **flags)
        assert "medium.en" in printed


def test_missing_whisper_library_is_reported_as_optional(tmp_path, monkeypatch):
    from llm_youtube_comment_generation.infrastructure import whisper_transcript

    monkeypatch.setattr(whisper_transcript, "library_available", lambda: False)

    code, printed = report(tmp_path)

    assert code == 0
    assert "not installed" in printed
    assert 'python -m pip install -e ".[local-transcription]"' in printed


def test_core_only_install_reports_every_missing_provider(tmp_path, monkeypatch):
    from llm_youtube_comment_generation.infrastructure import whisper_transcript

    monkeypatch.setattr(CLI, "library_available", lambda: False)
    monkeypatch.setattr(CLI, "ytdlp_available", lambda: False)
    monkeypatch.setattr(whisper_transcript, "library_available", lambda: False)

    code, printed = report(tmp_path)

    assert code == 0
    assert "transcript: scrape" in printed
    assert "transcript: yt-dlp" in printed
    assert "transcript: whisper" in printed
    assert printed.count("not installed") >= 3


# -- saved transcripts: what this machine can do with no network -----------


def test_nothing_saved_yet_says_so_plainly(tmp_path):
    _code, printed = report(tmp_path)

    assert "nothing saved yet" in printed


def test_it_counts_the_videos_that_can_be_rebuilt_offline(tmp_path):
    """The number that matters when the endpoint is refusing: how much can
    be done without asking YouTube for anything."""

    for video in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        run = tmp_path / f"{video}_20260728-120000"
        run.mkdir()
        (run / "transcript_timestamped.txt").write_text(
            "[00:00:00] words", encoding="utf-8")

    _code, printed = report(tmp_path)

    assert "2 video(s) can be rebuilt" in printed


def test_an_empty_transcript_file_is_not_a_saved_transcript(tmp_path):
    run = tmp_path / "aaaaaaaaaaa_20260728-120000"
    run.mkdir()
    (run / "transcript_timestamped.txt").write_text("", encoding="utf-8")

    _code, printed = report(tmp_path)

    assert "nothing saved yet" in printed


def test_a_missing_output_directory_is_not_an_error(tmp_path):
    """The writability check runs first and creates it, so by the time the
    saved-transcript count is taken there is a directory with nothing in it.
    The "no output directory" branch is the fallback for when creating it
    failed, which is reported by the writability line above it anyway."""

    code, printed = report(tmp_path / "not-created-yet")

    assert code == 0
    assert "nothing saved yet" in printed
    assert "!!" not in printed, "a missing directory is not a failure"


# -- the advice is actionable ----------------------------------------------


def test_a_missing_library_says_the_command_that_installs_it(tmp_path,
                                                             monkeypatch):
    """"not installed" without the pip line sends him to a search engine."""

    monkeypatch.setattr(CLI, "ytdlp_available", lambda: False)

    _code, printed = report(tmp_path)

    assert 'python -m pip install -e ".[transcripts]"' in printed


def test_each_failed_probe_is_isolated_and_later_checks_still_run(
    tmp_path,
    monkeypatch,
):
    def fail(message):
        def probe(*_args, **_kwargs):
            raise RuntimeError(message)
        return probe

    monkeypatch.setattr(
        CLI,
        "library_available",
        fail("scrape unavailable"),
    )
    monkeypatch.setattr(
        CLI,
        "ytdlp_available",
        fail("player unavailable"),
    )
    monkeypatch.setattr(
        CLI,
        "_saved_transcript_state",
        fail("saved scan unavailable"),
    )
    monkeypatch.setattr(
        CLI.prompt_resources,
        "prompt_version",
        fail("manifest malformed"),
    )
    monkeypatch.setattr(
        CLI,
        "_write_check",
        fail("cannot probe output"),
    )
    monkeypatch.setattr(
        CLI,
        "history_store",
        fail("history lifecycle unavailable"),
    )

    code, printed = report(tmp_path)

    assert code == 0
    assert printed.count("CHECK FAILED (RuntimeError)") == 6
    for name in (
        "transcript: scrape",
        "transcript: yt-dlp",
        "transcript: saved",
        "prompt resources",
        "output directory",
        "history store",
    ):
        assert name in printed


def test_failed_probe_details_are_bounded_and_redacted(tmp_path, monkeypatch):
    private = str(tmp_path)
    proxy = "http://" + "operator:secret@" + "example.test:8080"
    configuration = resolve(flags={
        "output_directory": private,
        "proxy_url": proxy,
    })
    monkeypatch.setattr(
        CLI,
        "_write_check",
        lambda _root: (_ for _ in ()).throw(
            RuntimeError(f"{private} {proxy} " + "x" * 400)
        ),
    )
    stream = io.StringIO()

    code = CLI.run_doctor(configuration, "eight-char-secret", stream)
    printed = stream.getvalue()

    assert code == 0
    assert private not in printed
    assert "operator:secret" not in printed
    assert len(next(
        line for line in printed.splitlines()
        if "output directory" in line
    )) < 340
