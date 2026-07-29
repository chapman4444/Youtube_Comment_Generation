@echo off
REM Check the installation, and list past runs with broken ones flagged.
REM Run this first when something looks wrong. It never fails.

setlocal
cd /d "%~dp0"

REM Always inspect the code beside this launcher.
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "YTCOMMENT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%YTCOMMENT_PYTHON%" set "YTCOMMENT_PYTHON=python"

"%YTCOMMENT_PYTHON%" -m llm_youtube_comment_generation.interfaces.cli.main doctor
echo.
echo ----------------------------------------------------------------
echo.
"%YTCOMMENT_PYTHON%" -m llm_youtube_comment_generation.interfaces.cli.main run list
echo.
pause
endlocal
