@echo off
REM What happened to the replies you drafted.
REM
REM Uses a high comment limit deliberately. At a low one the scoreboard
REM refuses to conclude anything, because a scan that stopped early cannot
REM tell "this reply is not there" from "I did not look far enough".

setlocal
cd /d "%~dp0"

call "%~dp0setup_venv.bat"
if errorlevel 1 goto :done

REM Always run the code beside this launcher.
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "YTCOMMENT_PYTHON=%~dp0.venv\Scripts\python.exe"

set "VIDEO=%~1"
if "%VIDEO%"=="" set /p "VIDEO=YouTube URL or video ID: "
if "%VIDEO%"=="" goto :nothing

echo.
"%YTCOMMENT_PYTHON%" -m llm_youtube_comment_generation.interfaces.cli.main scoreboard build "%VIDEO%" --max-comments 3000
goto :done

:nothing
echo No video given.

:done
echo.
pause
endlocal
