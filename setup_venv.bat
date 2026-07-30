@echo off
REM Create and repair the private Python environment used by every launcher.
REM Python 3.10 is selected explicitly so a different system-wide `python`
REM command can never make the GUI silently lose its transcript providers.

setlocal
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if exist "%VENV_PY%" goto :check_version

echo Creating the project Python 3.10 environment ...
py -3.10 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Python 3.10 is required, but the Windows Python launcher could not find it.
    echo Install Python 3.10, including the py launcher, then run gui.bat again.
    exit /b 10
)

py -3.10 -m venv ".venv"
if errorlevel 1 (
    echo.
    echo The project virtual environment could not be created.
    exit /b 11
)

:check_version
"%VENV_PY%" -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 13) else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo The existing .venv uses an unsupported Python version.
    echo This project requires Python 3.10, 3.11, or 3.12.
    echo Rename or remove .venv, then run gui.bat to create a Python 3.10 environment.
    exit /b 12
)

REM A quick import check makes normal launches instant. If the environment is
REM new or incomplete, install the application plus both caption providers.
"%VENV_PY%" -c "import importlib.metadata as m, faster_whisper, requests, youtube_transcript_api, yt_dlp; m.version('llm-youtube-comment-generation')" >nul 2>&1
if not errorlevel 1 exit /b 0

echo Installing the application and transcript providers ...
"%VENV_PY%" -m pip install --disable-pip-version-check -e ".[transcripts,local-transcription]"
if errorlevel 1 (
    echo.
    echo The project dependencies could not be installed.
    exit /b 13
)

"%VENV_PY%" -c "import importlib.metadata as m, faster_whisper, requests, youtube_transcript_api, yt_dlp; m.version('llm-youtube-comment-generation')" >nul 2>&1
if errorlevel 1 (
    echo.
    echo The environment was created, but its transcript providers are incomplete.
    exit /b 14
)

exit /b 0
