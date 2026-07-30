@echo off
REM Work through the replies you owe on one video.
REM
REM You do not have to type the video. Copy its URL in your browser and run
REM this; the video is taken from the clipboard. A URL or ID passed as an
REM argument still wins over whatever is on the clipboard.
REM
REM Shows who is waiting, then opens the window. Accepted replies are saved
REM to replies_to_review.md as you go, so stopping never loses them.
REM Nothing is ever posted.

setlocal EnableDelayedExpansion
cd /d "%~dp0"

call "%~dp0setup_venv.bat"
if errorlevel 1 goto :failed

REM Always run the code beside this launcher, never an older editable install
REM from another folder.
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "YTCOMMENT_PYTHON=%~dp0.venv\Scripts\python.exe"

REM Who you are. Never written in this file: it is personal data and this
REM file is meant to be publishable. Set it once with
REM     setx YTCOMMENT_MY_HANDLE yourhandle
REM and no launcher ever has to know it.
set "HANDLE=%YTCOMMENT_MY_HANDLE%"
if not defined HANDLE (
    echo.
    echo Reply mode needs to know which channel you comment from.
    echo Set it once so you never see this again:
    echo     setx YTCOMMENT_MY_HANDLE yourhandle
    echo.
    set /p "HANDLE=Your handle for this run: "
    if not defined HANDLE goto :nothing
)

REM Split off %* rather than reading %1: cmd treats "=" as an argument
REM delimiter, so "--dial humor=none" and "watch?v=xxxx" both arrive broken
REM when read positionally. The first token is the video unless it is an
REM option; everything after it is handed to ytcomment untouched.
set "ALLARGS=%*"
set "VIDEOARG="
set "EXTRA="
if not defined ALLARGS goto :parsed

for /f "tokens=1,* delims= " %%A in ("!ALLARGS!") do (
    set "FIRSTTOK=%%A"
    set "RESTTOK=%%B"
)
if "!FIRSTTOK:~0,1!"=="-" (
    set "EXTRA=!ALLARGS!"
) else (
    set "VIDEOARG=!FIRSTTOK!"
    set "EXTRA=!RESTTOK!"
)
:parsed

:run
echo.
echo Scanning for your comments as @%HANDLE% ...
echo.
"!YTCOMMENT_PYTHON!" -m llm_youtube_comment_generation.interfaces.cli.main reply scan-mine !VIDEOARG! --my-handle "%HANDLE%" !EXTRA!
if not errorlevel 1 goto :scanned

if defined ASKED goto :failed
set "ASKED=1"
echo.
set /p "TYPED=YouTube URL or video ID: "
if "!TYPED!"=="" goto :nothing
set "VIDEOARG="!TYPED!""
goto :run

:scanned
echo.
set /p "GO=Open the window to work through these? [y/N] "
if /i not "!GO!"=="y" goto :done

REM When no video was given, this reads the clipboard a second time. The scan
REM above does not touch the clipboard, so it still holds the same URL, and
REM the window announces which video it opened.
"!YTCOMMENT_PYTHON!" -m llm_youtube_comment_generation.interfaces.cli.main gui !VIDEOARG! --my-handle "%HANDLE%" !EXTRA!
goto :done

:nothing
echo No video given.
goto :done

:failed
echo.
echo That did not work. Run doctor.bat to check the installation.

:done
echo.
pause
endlocal
