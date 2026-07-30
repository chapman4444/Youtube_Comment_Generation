"""The batch files are the operator's actual interface.

He double-clicks these; he does not type `ytcomment`. One of them was found
empty — zero bytes — after a session of editing and running it, and nothing
noticed until he ran it four times and got no output at all. A file that is
supposed to contain a program is the easiest thing in the world to check.
"""

from __future__ import annotations

import re
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

LAUNCHERS = {
    "comment.bat": (
        "interfaces.cli.main comment build",
        # Arguments are split off %* because cmd treats "=" as a delimiter.
        'set "ALLARGS=%*"',
        'for /f "tokens=1,* delims= "',
        "pause",
    ),
    "reply.bat": (
        "interfaces.cli.main reply scan-mine",
        'set "ALLARGS=%*"',
        "set \"HANDLE=",
        "pause",
    ),
    "gui.bat": (
        "interfaces.gui.launcher gui",
        'set "ALLARGS=%*"',
        "set \"HANDLE=",
        # The window needs a queue that rarely exists. Without a way in that
        # does not, it cannot be looked at before it is needed.
        "interfaces.gui.launcher gui --preview",
    ),
    "doctor.bat": ("interfaces.cli.main doctor", "pause"),
    "scoreboard.bat": ("interfaces.cli.main scoreboard", "pause"),
}


@pytest.mark.parametrize("name", sorted(LAUNCHERS))
def test_the_launcher_is_not_empty(name):
    path = ROOT / name

    assert path.is_file(), f"{name} is missing"
    assert path.stat().st_size > 0, f"{name} is zero bytes"


@pytest.mark.parametrize("name", sorted(LAUNCHERS))
def test_the_launcher_still_does_its_job(name):
    """Each line here is something the file stops working without."""

    text = (ROOT / name).read_text(encoding="utf-8")

    for required in LAUNCHERS[name]:
        assert required in text, f"{name} no longer contains {required!r}"


@pytest.mark.parametrize("name", sorted(LAUNCHERS))
def test_every_launcher_uses_the_source_beside_it(name):
    """A global editable install may point at an older copy of the project."""

    text = (ROOT / name).read_text(encoding="utf-8")

    assert 'set "PYTHONPATH=%~dp0src;%PYTHONPATH%"' in text
    assert r".venv\Scripts\python.exe" in text
    if name == "gui.bat":
        assert "-m llm_youtube_comment_generation.interfaces.gui.launcher" in text
    else:
        assert "-m llm_youtube_comment_generation.interfaces.cli.main" in text


@pytest.mark.parametrize("name", sorted(LAUNCHERS))
def test_every_launcher_bootstraps_and_requires_the_project_venv(name):
    text = (ROOT / name).read_text(encoding="utf-8")

    assert 'call "%~dp0setup_venv.bat"' in text
    assert "set \"YTCOMMENT_PYTHON=python\"" not in text


def test_venv_bootstrap_keeps_optional_providers_out_of_the_core_path():
    text = (ROOT / "setup_venv.bat").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    core_path = text.split("\n:core_ready", 1)[0]

    assert 'py -3.10 -m venv ".venv"' in text
    assert '-e "."' in core_path
    assert "youtube_transcript_api" not in core_path
    assert "yt_dlp" not in core_path
    assert "faster_whisper" not in core_path
    assert 'if "%~1"=="" exit /b 0' in text
    assert '"OPTIONAL_EXTRAS=transcripts"' in text
    assert '"OPTIONAL_EXTRAS=local-transcription"' in text
    assert '"OPTIONAL_EXTRAS=transcripts,local-transcription"' in text
    assert '".[%OPTIONAL_EXTRAS%]"' in text
    assert "youtube_transcript_api" in text
    assert "yt_dlp" in text
    assert "faster_whisper" in text
    assert 'transcripts = ["youtube-transcript-api>=1.0", "yt-dlp"]' in project
    assert 'local-transcription = ["faster-whisper"]' in project


@pytest.mark.parametrize("name", sorted(LAUNCHERS))
def test_the_launcher_ends_where_it_can_be_read(name):
    """Without a pause, a double-clicked window closes before the operator
    can read what happened — including the error telling him why."""

    lines = [line.strip() for line
             in (ROOT / name).read_text(encoding="utf-8").splitlines()
             if line.strip()]

    assert "endlocal" in lines[-1] or "pause" in lines[-1]


def test_gui_launcher_closes_without_startup_or_shutdown_chatter():
    text = (ROOT / "gui.bat").read_text(encoding="utf-8")

    assert "pause" not in text.lower()
    assert "Building the comment packet, then opening the window" not in text
    assert r".venv\Scripts\pythonw.exe" in text
    assert (
        'start "" "!YTCOMMENT_PYTHONW!" '
        "-m llm_youtube_comment_generation.interfaces.gui.launcher "
        "comment build"
    ) in text
    assert 'set "RC=!ERRORLEVEL!"' not in text
    assert 'if "!RC!"=="5"' not in text


def test_a_dry_run_does_not_claim_a_packet_was_built():
    """It printed "the packet is on your clipboard" after --dry-run, which
    sends no request and writes nothing."""

    text = (ROOT / "comment.bat").read_text(encoding="utf-8")

    assert "--dry-run" in text
    assert "Nothing was built" in text


def test_no_launcher_carries_a_personal_handle():
    """A handle written into a launcher is personal data in a file meant to
    be published. One was: an earlier session lifted a handle out of fetched
    comment data -- a stranger's -- and wrote it in as the operator's, which
    both leaked a name and made every reply scan search for the wrong person.

    The handle belongs in YTCOMMENT_MY_HANDLE and nowhere in this repository.
    """

    for name in sorted(LAUNCHERS):
        text = (ROOT / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("REM"):
                continue
            assert not re.search(r'set\s+"?HANDLE=[A-Za-z0-9@._-]+', stripped), (
                f"{name} hardcodes a handle: {stripped!r}. "
                "Read YTCOMMENT_MY_HANDLE instead."
            )


def test_the_launchers_say_how_to_set_the_handle():
    """Removing the hardcoded value is only half of it. A launcher that needs
    a handle and does not say how to supply one is worse than one that
    guesses."""

    for name in ("reply.bat", "gui.bat"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "YTCOMMENT_MY_HANDLE" in text
        assert "setx YTCOMMENT_MY_HANDLE" in text


def test_a_missing_transcript_does_not_ask_for_the_url_again():
    """A video with no captions exits 5, which has nothing to do with the
    video. comment.bat asked for the URL, got the same one back, and spent a
    second scan proving the same thing."""

    text = (ROOT / "comment.bat").read_text(encoding="utf-8")

    assert 'set "RC=!ERRORLEVEL!"' in text, "the exit code is not captured"
    assert '"!RC!"=="5"' in text, "a missing transcript is not distinguished"
    assert "--allow-no-transcript" in text, "it does not offer the way forward"
    assert '"!RC!"=="3"' in text, "only a config failure should re-prompt"


def test_a_video_given_on_the_command_line_is_never_asked_for_again():
    text = (ROOT / "comment.bat").read_text(encoding="utf-8")

    assert "if defined VIDEOARG goto :failed" in text


def test_every_launcher_passes_extra_arguments_through():
    """comment.bat --dial grounding=summary passed "--dial" as the video and
    dropped its value, because it read only %1."""

    for name in ("comment.bat", "reply.bat", "gui.bat"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "!EXTRA!" in text, f"{name} drops everything after the video"


def test_review_zip_records_snapshot_verification_evidence():
    text = (ROOT / "make_review_zip.bat").read_text(encoding="utf-8")

    assert "tools\\create_review_evidence.py" in text
    assert 'call "%PROJECT_ROOT%setup_venv.bat" review' in text
    assert "import build, faster_whisper, pytest, requests, ruff" in text
    assert '"%PROJECT_PY%" tools\\create_review_evidence.py' in text
    assert '"REVIEW_PROMPT.md"' in text
    assert "REVIEW_VERIFICATION.md" in text
    assert "WinRAR.exe" in text
    assert "Youtube_Comment_Generation_review.new.zip" in text
    assert '"%WINRAR_EXE%" t -y "%TEMP_ARCHIVE%"' in text
    assert 'move /y "%TEMP_ARCHIVE%" "%ARCHIVE%"' in text
    evidence = text.index('tools\\create_review_evidence.py')
    replacement = text.index('move /y "%TEMP_ARCHIVE%" "%ARCHIVE%"')
    assert evidence < replacement


def test_review_setup_declares_and_checks_every_gate_dependency():
    setup = (ROOT / "setup_venv.bat").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "review = [" in project
    for requirement in (
        "pytest",
        "ruff",
        "build",
        "youtube-transcript-api",
        "yt-dlp",
        "faster-whisper",
    ):
        assert requirement in project
    assert 'if /i "%~1"=="review"' in setup
    assert '"OPTIONAL_EXTRAS=review"' in setup
    assert (
        "import build, faster_whisper, pytest, requests, ruff, "
        "youtube_transcript_api, yt_dlp"
    ) in setup


@pytest.mark.opens_for_real
def test_module_help_has_no_duplicate_import_runpy_warning():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "llm_youtube_comment_generation.interfaces.cli.main",
            "--help",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Build YouTube comment and reply packets" in completed.stdout
    assert "RuntimeWarning" not in completed.stderr
    assert "unpredictable behaviour" not in completed.stderr
