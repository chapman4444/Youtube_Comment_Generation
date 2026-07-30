"""The transcript sources are wired in the order the CHANGELOG claims.

There are four now — the scrape endpoint, yt-dlp's player API, this machine's
saved copy, and transcribing the audio here — and the order is the whole
design. An order that quietly differs from the one written down is worse than
no order at all, because every decision after it is reasoned from the wrong
picture.

`transcribe_locally` is the one that must be off unless asked for: every other
source is one request, and that one is an audio download plus minutes of CPU.

Nothing here reaches the network; only construction is checked.
"""

from __future__ import annotations

import sys

import pytest

import llm_youtube_comment_generation.interfaces.cli.main  # noqa: F401

CLI = sys.modules["llm_youtube_comment_generation.interfaces.cli.main"]

from llm_youtube_comment_generation.application.configuration import resolve
from llm_youtube_comment_generation.infrastructure.saved_transcripts import (
    SavedTranscriptFallback,
)
from llm_youtube_comment_generation.infrastructure.transcript_api import (
    TranscriptAdapter,
)
from llm_youtube_comment_generation.infrastructure.transcript_chain import (
    ChainedTranscripts,
)
from llm_youtube_comment_generation.infrastructure.whisper_transcript import (
    WhisperTranscriptAdapter,
)
from llm_youtube_comment_generation.infrastructure.ytdlp_transcript import (
    YtDlpTranscriptAdapter,
)


def ports(**flags):
    configuration = resolve(flags={"output_directory": "output", **flags})
    return CLI.default_ports(configuration, "a-key", events=None)


def sources(port):
    """Caption sources followed by the optional local fallback."""

    assert isinstance(port, SavedTranscriptFallback)
    inner = port._inner
    assert isinstance(inner, ChainedTranscripts)
    inventory = list(inner._sources)
    if port._local_fallback is not None:
        inventory.append(port._local_fallback)
    return inventory


# -- the order -------------------------------------------------------------


def test_the_scrape_endpoint_is_tried_first():
    """One request against yt-dlp's several, and it gives up after three
    refusals, so on a blocked machine its cost collapses to nothing."""

    assert isinstance(sources(ports()["transcripts"])[0], TranscriptAdapter)


def test_yt_dlp_backs_it_up():
    """They are blocked separately: an address refused by the first was being
    served by the second in the same minute."""

    assert isinstance(sources(ports()["transcripts"])[1],
                      YtDlpTranscriptAdapter)


def test_the_saved_copy_sits_outside_both():
    """It is the last resort across processes, so it wraps rather than
    joins."""

    assert isinstance(ports()["transcripts"], SavedTranscriptFallback)


# -- the expensive one is opt-in -------------------------------------------


def test_transcribing_here_is_off_unless_it_is_asked_for():
    """Every other source is one request. This is an audio download and
    minutes of CPU, and spending that unasked in the middle of a build would
    be a nasty surprise."""

    assert not any(isinstance(s, WhisperTranscriptAdapter)
                   for s in sources(ports()["transcripts"]))


def test_asking_for_it_adds_it_last():
    chain = sources(ports(transcribe_locally=True)["transcripts"])

    assert isinstance(chain[-1], WhisperTranscriptAdapter)
    assert len(chain) == 3


def test_the_setting_reads_a_word_as_well_as_a_flag():
    """"false" from a file or an environment variable is a non-empty string
    and therefore true, which is the classic way an off switch turns itself
    on."""

    for value in ("false", "0", "no", "off", ""):
        chain = sources(ports(transcribe_locally=value)["transcripts"])
        assert not any(isinstance(s, WhisperTranscriptAdapter) for s in chain), \
            f"{value!r} switched it on"

    for value in ("true", "1", "yes", "on"):
        chain = sources(ports(transcribe_locally=value)["transcripts"])
        assert any(isinstance(s, WhisperTranscriptAdapter) for s in chain), \
            f"{value!r} did not switch it on"


def test_the_chosen_model_reaches_the_transcriber():
    chain = sources(ports(transcribe_locally=True,
                          whisper_model="medium.en")["transcripts"])

    assert chain[-1]._model_name == "medium.en"


def test_window_options_can_enable_whisper_without_mutating_configuration():
    configuration = resolve(flags={"output_directory": "output"})
    wired = CLI.default_ports(
        configuration,
        "a-key",
        events=None,
        transcribe_locally=True,
        whisper_model="tiny.en",
    )
    chain = sources(wired["transcripts"])

    assert isinstance(chain[-1], WhisperTranscriptAdapter)
    assert chain[-1]._model_name == "tiny.en"


def test_window_cancellation_reaches_the_local_transcriber():
    requested = lambda: True
    configuration = resolve(flags={"output_directory": "output"})
    wired = CLI.default_ports(
        configuration,
        "a-key",
        events=None,
        cancelled=requested,
        transcribe_locally=True,
    )
    whisper = sources(wired["transcripts"])[-1]

    assert isinstance(whisper, WhisperTranscriptAdapter)
    assert whisper._cancelled is requested


def test_ask_policy_wires_confirmation_before_local_whisper():
    asked = lambda result: False
    configuration = resolve(flags={"output_directory": "output"})
    wired = CLI.default_ports(
        configuration,
        "a-key",
        events=None,
        whisper_policy="ask",
        confirm_transcription=asked,
    )

    assert isinstance(
        wired["transcripts"]._local_fallback,
        WhisperTranscriptAdapter,
    )
    assert wired["transcripts"]._approve_local_fallback is asked


def test_ignore_policy_does_not_construct_local_whisper():
    configuration = resolve(flags={"output_directory": "output"})
    wired = CLI.default_ports(
        configuration,
        "a-key",
        events=None,
        whisper_policy="ignore",
    )

    assert wired["transcripts"]._local_fallback is None


@pytest.mark.parametrize(
    ("route", "adapter"),
    [
        ("api", TranscriptAdapter),
        ("ytdlp", YtDlpTranscriptAdapter),
        ("whisper", WhisperTranscriptAdapter),
    ],
)
def test_manual_routes_construct_exactly_the_requested_live_source(
    route, adapter,
):
    configuration = resolve(flags={"output_directory": "output"})

    wired = CLI.default_ports(
        configuration,
        "a-key",
        events=None,
        transcript_route=route,
    )

    assert isinstance(wired["transcripts"], adapter)


def test_manual_saved_route_does_not_try_a_live_source():
    configuration = resolve(flags={"output_directory": "output"})

    wired = CLI.default_ports(
        configuration,
        "a-key",
        events=None,
        transcript_route="saved",
    )

    assert isinstance(wired["transcripts"], SavedTranscriptFallback)
    assert wired["transcripts"]._inner is None


# -- the proxy reaches what actually gets banned ---------------------------


def test_the_proxy_reaches_every_source_that_talks_to_youtube():
    """It was in the configuration for the whole project and reached only the
    authenticated API, which is never the component that gets blocked."""

    chain = sources(ports(proxy_url="http://127.0.0.1:8888",
                          transcribe_locally=True)["transcripts"])

    for source in chain:
        assert getattr(source, "_proxy_url", "") == "http://127.0.0.1:8888", (
            f"{type(source).__name__} never sees the proxy"
        )


def test_the_requested_languages_reach_every_source():
    chain = sources(ports(transcript_languages="de,en",
                          transcribe_locally=True)["transcripts"])

    for source in chain:
        assert source._languages == ("de", "en")
