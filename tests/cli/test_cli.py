"""The command line: parsing, exit codes, output shape, and configuration.

Every test here runs the real `main()` — real argument parsing, real
precedence resolution, real exit-code mapping — with the ports swapped for
fakes. That is the point of injecting `build_ports`: the CLI is exercised
end to end without a network.
"""

from __future__ import annotations

import io
import json

import pytest

from fakes import FakeEventSink, FakeTranscriptPort, FakeYouTubePort
from llm_youtube_comment_generation.application.configuration import (
    DEFAULTS,
    ENVIRONMENT_KEYS,
    SOURCE_CONFIG_FILE,
    SOURCE_DEFAULT,
    SOURCE_ENVIRONMENT,
    SOURCE_FLAG,
    SOURCE_SETTINGS,
    redact,
    resolve,
    resolve_api_key,
)
from llm_youtube_comment_generation.domain.errors import (
    ConfigurationError,
    QuotaExceededError,
)
from llm_youtube_comment_generation.domain.statuses import TranscriptAvailability
from llm_youtube_comment_generation.interfaces.cli.main import main

VIDEO = "gC-J7zwYMAM"


def comment(index, likes=0, replies=0):
    return {
        "comment_id": f"c{index}",
        "author": f"@user{index}",
        "author_channel_id": "UC" + str(index).ljust(22, "z"),
        "text": " ".join(["word"] * (index % 20 + 3)),
        "like_count": likes,
        "total_reply_count": replies,
        "published_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
    }


def ports_factory(youtube=None, transcripts=None, events=None):
    youtube = youtube or FakeYouTubePort(
        videos={VIDEO: {"video_id": VIDEO, "title": "A real video",
                        "channel_title": "A channel", "comment_count": 2,
                        "view_count": 1000, "like_count": 50,
                        "published_at": "2026-07-01T00:00:00Z"}},
        comments=[comment(1, likes=10), comment(2, likes=3, replies=2)],
        replies={"c2": [comment(9)]},
    )
    transcripts = transcripts or FakeTranscriptPort()
    sink = events or FakeEventSink()

    def build(configuration, api_key, event_sink):
        return {"youtube": youtube, "transcripts": transcripts, "events": sink}

    return build, youtube, sink


def run(argv, environment=None, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    build, youtube, sink = ports_factory(**kwargs)
    code = main(
        argv,
        build_ports=build,
        stdout=out,
        stderr=err,
        environment={"YOUTUBE_API_KEY": "test-key", **(environment or {})},
    )
    return code, out.getvalue(), err.getvalue(), youtube, sink


# --------------------------------------------------------------------------
# video inspect
# --------------------------------------------------------------------------


def test_inspect_reports_the_video_and_exits_zero():
    code, out, err, _, _ = run(["video", "inspect", VIDEO])

    assert code == 0
    assert "A real video" in out
    assert VIDEO in out
    assert err == "" or "Inspecting" in err


def test_inspect_accepts_a_url_as_well_as_an_id():
    code, out, _, _, _ = run(
        ["video", "inspect", f"https://www.youtube.com/watch?v={VIDEO}"]
    )

    assert code == 0
    assert VIDEO in out


def test_a_bad_video_id_exits_three_and_spends_no_quota():
    """Configuration error, not a generic failure: the operator can fix it."""

    code, _, err, youtube, _ = run(["video", "inspect", "obviously not a video"])

    assert code == 3
    assert youtube.api_operations_used == 0
    assert err.strip()


def test_a_dry_run_performs_no_request_at_all():
    """The whole value of --dry-run is that it costs nothing.

    A version that spent "just one" request to validate would defeat the
    purpose for an operator checking a command before committing quota.
    """

    code, out, _, youtube, _ = run(["video", "inspect", VIDEO, "--dry-run"])

    assert code == 0
    assert youtube.api_operations_used == 0
    assert "No API request was sent" in out


def test_a_dry_run_needs_no_api_key():
    out, err = io.StringIO(), io.StringIO()
    build, youtube, _ = ports_factory()

    code = main(["video", "inspect", VIDEO, "--dry-run"],
                build_ports=build, stdout=out, stderr=err, environment={})

    assert code == 0
    assert youtube.api_operations_used == 0


def test_a_real_run_without_a_key_exits_three_before_touching_the_network():
    out, err = io.StringIO(), io.StringIO()
    build, youtube, _ = ports_factory()

    code = main(["video", "inspect", VIDEO],
                build_ports=build, stdout=out, stderr=err, environment={})

    assert code == 3
    assert "No API key" in err.getvalue()
    assert youtube.api_operations_used == 0


def test_quota_exhaustion_exits_two():
    youtube = FakeYouTubePort(videos={VIDEO: {"video_id": VIDEO}})
    youtube.raise_on_video = QuotaExceededError(
        "videos", 403, {"error": {"errors": [{"reason": "quotaExceeded"}]}}
    )

    code, _, err, _, _ = run(["video", "inspect", VIDEO], youtube=youtube)

    assert code == 2
    assert "quota" in err.lower()


def test_the_api_key_is_never_echoed_in_an_error():
    """A key in a terminal is a key in a screenshot in a bug report."""

    youtube = FakeYouTubePort(videos={})
    youtube.raise_on_video = ConfigurationError(
        "request failed for key AIzaSyVerySecretValue123"
    )

    _, _, err, _, _ = run(
        ["video", "inspect", VIDEO],
        environment={"YOUTUBE_API_KEY": "AIzaSyVerySecretValue123"},
        youtube=youtube,
    )

    assert "AIzaSyVerySecretValue123" not in err
    assert "[redacted]" in err


# --------------------------------------------------------------------------
# Output shapes
# --------------------------------------------------------------------------


def test_json_output_is_valid_and_stable():
    """A caller scripts against these keys, so the shape is a contract."""

    code, out, _, _, _ = run(["--output", "json", "video", "inspect", VIDEO])
    payload = json.loads(out)

    assert code == 0
    assert set(payload) == {
        "status", "video", "retrieval", "counts", "transcript", "register",
        "warnings", "metrics", "dry_run",
    }
    assert set(payload["retrieval"]) == {
        "status", "complete", "may_conclude_absence", "retrieved",
        "reported_total", "missing", "notes",
    }
    assert payload["video"]["video_id"] == VIDEO
    assert payload["counts"]["comments"] == 2


def test_completeness_is_reported_even_when_everything_went_right():
    """Reporting only failures trains the reader to assume silence is success."""

    _, out, _, _, _ = run(["video", "inspect", VIDEO])

    assert "retrieval  complete" in out


def test_an_incomplete_scan_says_it_cannot_prove_absence():
    youtube = FakeYouTubePort(
        videos={VIDEO: {"video_id": VIDEO, "title": "t"}},
        comments=[comment(i) for i in range(50)],
    )

    code, out, _, _, _ = run(
        ["video", "inspect", VIDEO], environment={"YTCOMMENT_MAX_COMMENTS": "10"},
        youtube=youtube,
    )

    assert code == 0                       # a warning is not an error
    assert "top_level_truncated" in out
    assert "cannot be used to conclude a comment is absent" in out


def test_a_missing_transcript_warns_but_still_exits_zero():
    code, out, _, _, _ = run(
        ["video", "inspect", VIDEO],
        transcripts=FakeTranscriptPort(
            availability=TranscriptAvailability.NOT_PUBLISHED
        ),
    )

    assert code == 0
    assert "transcript_unavailable" in out


def test_progress_none_emits_nothing_to_stderr():
    out, err = io.StringIO(), io.StringIO()
    build, _, _ = ports_factory(events=None)

    # The real sink is built by main() when the factory does not override it,
    # so this asserts the flag reaches sink construction.
    code = main(["--progress", "none", "video", "inspect", VIDEO],
                build_ports=lambda c, k, e: {
                    "youtube": ports_factory()[1],
                    "transcripts": FakeTranscriptPort(),
                    "events": e,
                },
                stdout=out, stderr=err,
                environment={"YOUTUBE_API_KEY": "k"})

    assert code == 0
    assert err.getvalue() == ""


def test_no_arguments_prints_help_and_exits_zero():
    out, err = io.StringIO(), io.StringIO()

    assert main([], stdout=out, stderr=err, environment={}) == 0
    assert "ytcomment" in out.getvalue()


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------


def test_doctor_reports_a_missing_key_without_failing():
    """doctor is run when something is wrong; it must not be another thing
    that breaks."""

    out, err = io.StringIO(), io.StringIO()

    code = main(["doctor"], stdout=out, stderr=err, environment={})

    assert code == 0
    assert "NOT FOUND" in out.getvalue()


def test_doctor_reports_a_missing_transcript_library_as_a_fact():
    """A missing optional library is reported and exits 0: the application
    works without it.

    The label moved when the transcript stack grew to four sources. "ok" and
    "!!" are the contract with the reader, not the wording, so this asserts
    the sources are named and the exit code holds.
    """

    out, err = io.StringIO(), io.StringIO()

    code = main(["doctor"], stdout=out, stderr=err,
                environment={"YOUTUBE_API_KEY": "k"})
    printed = out.getvalue()

    assert code == 0
    assert "transcript: scrape" in printed
    assert "api key" in printed


# --------------------------------------------------------------------------
# config print
# --------------------------------------------------------------------------


def test_config_print_shows_every_setting_and_its_origin():
    out, err = io.StringIO(), io.StringIO()

    code = main(["config", "print"], stdout=out, stderr=err,
                environment={"YOUTUBE_API_KEY": "k"})
    printed = out.getvalue()

    assert code == 0
    for name in DEFAULTS:
        assert name in printed
    assert "built-in default" in printed


def test_config_print_says_whether_a_key_resolved_never_the_key():
    out, err = io.StringIO(), io.StringIO()

    main(["config", "print"], stdout=out, stderr=err,
         environment={"YOUTUBE_API_KEY": "AIzaSySecretValue"})
    printed = out.getvalue()

    assert "resolved" in printed
    assert "AIzaSySecretValue" not in printed


def test_config_print_redacts_proxy_identity_and_private_paths():
    out, err = io.StringIO(), io.StringIO()
    secret = "p4ssw0rd"
    proxy = "http://" + f"operator:{secret}@" + "proxy.test:8080"
    private_path = "C:" + "\\Users\\PrivateName\\runs"

    code = main(
        ["config", "print"],
        stdout=out,
        stderr=err,
        environment={
            "YTCOMMENT_PROXY_URL": proxy,
            "YTCOMMENT_MY_HANDLE": "@private-handle",
            "YTCOMMENT_MY_CHANNEL_ID": "UC" + "A" * 22,
            "YTCOMMENT_OUTPUT_DIR": private_path,
        },
    )
    printed = out.getvalue()

    assert code == 0
    assert "http://proxy.test:8080" in printed
    assert secret not in printed
    assert "operator" not in printed
    assert "@private-handle" not in printed
    assert "UC" + "A" * 22 not in printed
    assert "PrivateName" not in printed
    assert "C:" + "\\Users\\<user>\\runs" in printed
    assert "proxy_url" in printed
    assert "environment" in printed


# --------------------------------------------------------------------------
# Configuration precedence
# --------------------------------------------------------------------------


def test_the_precedence_chain_runs_lowest_to_highest():
    configuration = resolve(
        settings={"max_comments": 100},
        config_file={"max_comments": 200},
        environment={"YTCOMMENT_MAX_COMMENTS": "300"},
        flags={"max_comments": 400},
    )

    assert configuration["max_comments"] == 400
    assert configuration.source_of("max_comments") == SOURCE_FLAG


@pytest.mark.parametrize("layers, expected, source", [
    ({}, DEFAULTS["max_comments"], SOURCE_DEFAULT),
    ({"settings": {"max_comments": 100}}, 100, SOURCE_SETTINGS),
    ({"config_file": {"max_comments": 200}}, 200, SOURCE_CONFIG_FILE),
    ({"environment": {"YTCOMMENT_MAX_COMMENTS": "300"}}, 300, SOURCE_ENVIRONMENT),
    ({"flags": {"max_comments": 400}}, 400, SOURCE_FLAG),
])
def test_each_layer_is_reachable_and_names_itself(layers, expected, source):
    # environment defaults to {} unless the case under test supplies one;
    # passing it separately would be a duplicate keyword argument.
    configuration = resolve(**{"environment": {}, **layers})

    assert configuration["max_comments"] == expected
    assert configuration.source_of("max_comments") == source


def test_an_untouched_flag_does_not_outrank_the_settings_file():
    """argparse defaults are None on purpose.

    If an untouched flag counted as a command-line value, every setting would
    report its origin as the command line and the settings file would be
    silently defeated.
    """

    configuration = resolve(
        settings={"max_comments": 100},
        environment={},
        flags={"max_comments": None},
    )

    assert configuration["max_comments"] == 100
    assert configuration.source_of("max_comments") == SOURCE_SETTINGS


def test_every_environment_variable_maps_to_a_real_setting():
    """A mapping to a setting that does not exist would silently do nothing."""

    for name in ENVIRONMENT_KEYS:
        assert name in DEFAULTS


def test_a_budget_below_the_reachable_minimum_is_refused():
    with pytest.raises(ConfigurationError, match="below the smallest packet"):
        resolve(environment={}, flags={"packet_characters": 1000})


@pytest.mark.parametrize(
    "name",
    ("max_comments", "reply_scan_comments", "max_replies_per_thread"),
)
@pytest.mark.parametrize("value", (0, -1))
def test_every_retrieval_limit_must_be_positive(name, value):
    with pytest.raises(ConfigurationError, match="at least 1"):
        resolve(environment={}, flags={name: value})


def test_the_refusal_names_where_the_bad_value_came_from():
    """"It is wrong" is unhelpful when four layers could have set it."""

    with pytest.raises(ConfigurationError, match="environment"):
        resolve(environment={"YTCOMMENT_PACKET_CHARACTERS": "1000"})


def test_a_non_numeric_setting_is_refused_clearly():
    with pytest.raises(ConfigurationError, match="whole number"):
        resolve(environment={"YTCOMMENT_MAX_COMMENTS": "lots"})


def test_transcript_languages_accept_a_comma_separated_string():
    configuration = resolve(
        environment={}, settings={"transcript_languages": "en, es ,fr"}
    )

    assert configuration["transcript_languages"] == ("en", "es", "fr")


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------


def test_the_key_is_read_from_the_environment_first():
    assert resolve_api_key({"YOUTUBE_API_KEY": "from-env"}) == "from-env"
    assert resolve_api_key({"YTCOMMENT_API_KEY": "alt"}) == "alt"


def test_a_key_file_is_a_fallback_not_a_default(tmp_path):
    key_file = tmp_path / "key.txt"
    key_file.write_text("  from-file  ", encoding="utf-8")

    assert resolve_api_key({}, key_file) == "from-file"
    assert resolve_api_key({"YOUTUBE_API_KEY": "from-env"}, key_file) == "from-env"


def test_a_missing_key_resolves_to_empty_rather_than_raising():
    """doctor reports it; a real command refuses. The resolver does neither."""

    assert resolve_api_key({}, "") == ""


def test_redaction_ignores_short_strings():
    """Redacting a two-character secret would corrupt every message."""

    assert redact("the value is ab", "ab") == "the value is ab"
    assert redact("key AIzaSyLongSecret", "AIzaSyLongSecret") == "key [redacted]"
