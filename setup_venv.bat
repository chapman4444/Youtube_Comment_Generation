@echo off
REM Create and repair the private Python environment used by every launcher.
REM Python 3.10 is selected explicitly so a different system-wide `python`
REM command can never make the GUI silently lose its transcript providers.

setlocal
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "CONSTRAINTS=%~dp0constraints\review.txt"
set "CORE_FINGERPRINT=%~dp0.venv\.ytcomment-core-fingerprint"
set "FINGERPRINT_TOOL=%~dp0tools\dependency_fingerprint.py"

if not exist "%CONSTRAINTS%" (
    echo.
    echo The reviewed dependency constraints are missing: %CONSTRAINTS%
    exit /b 9
)
set "PIP_CONSTRAINT=%CONSTRAINTS%"

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

REM Normal launchers require only the core application. Transcript providers
REM are optional capabilities: doctor must be able to start and report their
REM absence instead of bootstrap failing before doctor can run.
"%VENV_PY%" -c "import importlib.metadata as m, requests; m.version('llm-youtube-comment-generation')" >nul 2>&1
if errorlevel 1 goto :install_core
"%VENV_PY%" "%FINGERPRINT_TOOL%" check --root "%CD%" --state "%CORE_FINGERPRINT%" >nul 2>&1
if not errorlevel 1 goto :core_ready

:install_core
echo Installing the core application ...
"%VENV_PY%" -m pip install --disable-pip-version-check -c "%CONSTRAINTS%" -e "."
if errorlevel 1 (
    echo.
    echo The core project dependencies could not be installed.
    exit /b 13
)

"%VENV_PY%" -c "import importlib.metadata as m, requests; m.version('llm-youtube-comment-generation')" >nul 2>&1
if errorlevel 1 (
    echo.
    echo The environment was created, but the core application is incomplete.
    exit /b 14
)

"%VENV_PY%" "%FINGERPRINT_TOOL%" write --root "%CD%" --state "%CORE_FINGERPRINT%" >nul 2>&1
if errorlevel 1 (
    echo.
    echo The core application was installed, but dependency freshness could not be recorded.
    exit /b 18
)

:core_ready
if "%~1"=="" exit /b 0
if /i "%~1"=="transcripts" (
    set "OPTIONAL_EXTRAS=transcripts"
    goto :install_optional
)
if /i "%~1"=="local-transcription" (
    set "OPTIONAL_EXTRAS=local-transcription"
    goto :install_optional
)
if /i "%~1"=="all" (
    set "OPTIONAL_EXTRAS=transcripts,local-transcription"
    goto :install_optional
)
if /i "%~1"=="review" (
    set "OPTIONAL_EXTRAS=review"
    goto :install_optional
)

echo.
echo Unknown optional setup path: %~1
echo Use setup_venv.bat transcripts, local-transcription, all, or review.
exit /b 15

:install_optional
echo Installing optional support: %OPTIONAL_EXTRAS% ...
"%VENV_PY%" -m pip install --disable-pip-version-check -c "%CONSTRAINTS%" -e ".[%OPTIONAL_EXTRAS%]"
if errorlevel 1 (
    echo.
    echo Optional support could not be installed. The core application remains usable.
    exit /b 16
)

if /i "%~1"=="transcripts" (
    "%VENV_PY%" -c "import youtube_transcript_api, yt_dlp" >nul 2>&1
)
if /i "%~1"=="local-transcription" (
    "%VENV_PY%" -c "import faster_whisper" >nul 2>&1
)
if /i "%~1"=="all" (
    "%VENV_PY%" -c "import faster_whisper, youtube_transcript_api, yt_dlp" >nul 2>&1
)
if /i "%~1"=="review" (
    "%VENV_PY%" -c "import build, faster_whisper, pytest, requests, ruff, youtube_transcript_api, yt_dlp" >nul 2>&1
)
if errorlevel 1 (
    echo.
    echo Optional support was installed, but its provider imports are incomplete.
    echo The core application remains usable; run doctor.bat for details.
    exit /b 17
)

exit /b 0
