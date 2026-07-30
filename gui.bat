@echo off
REM Open a window on a comment packet for one video.
REM
REM Double-click this file, or run it from a terminal. You do not have to type
REM anything: copy the video URL in your browser first and the video is taken
REM from the clipboard. A URL or ID passed as an argument still wins.
REM
REM The window opens first. Choose a video and press Build; then copy the
REM packet, paste it into your model, and bring the answer back.
REM Nothing is ever posted; accepted drafts are saved to comment_drafts.md
REM beside the packet and its run record.
REM
REM   gui.bat --replies     the other window: work through people who replied
REM                         to YOUR comment and have not heard back. Needs a
REM                         video you commented on, which is a rarer state.
REM   gui.bat --preview     the reply window on made-up people. No scan, no
REM                         quota, nothing written.

setlocal EnableDelayedExpansion
cd /d "%~dp0"

call "%~dp0setup_venv.bat"
if errorlevel 1 goto :failed

REM Always run the code beside this launcher. An editable install elsewhere on
REM the computer may also provide ytcomment, but it must never make this folder
REM silently open an older GUI.
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "YTCOMMENT_PYTHON=%~dp0.venv\Scripts\python.exe"
set "YTCOMMENT_PYTHONW=%~dp0.venv\Scripts\pythonw.exe"

REM Who you are, for reply mode only. The setting wins if you have exported
REM YTCOMMENT_MY_HANDLE; otherwise this line is used.
REM Who you are, for reply mode. Never written in this file: it is personal
REM data and this file is meant to be publishable. Set it once with
REM     setx YTCOMMENT_MY_HANDLE yourhandle
REM and no launcher ever has to know it.
set "HANDLE=%YTCOMMENT_MY_HANDLE%"

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

echo !ALLARGS! | findstr /i /c:"--preview" >nul
if not errorlevel 1 goto :preview
echo !ALLARGS! | findstr /i /c:"--replies" >nul
if not errorlevel 1 goto :replies

:run
start "" "!YTCOMMENT_PYTHONW!" -m llm_youtube_comment_generation.interfaces.gui.launcher comment build !VIDEOARG! --window --no-copy !EXTRA!
goto :done

:replies
REM The same window, opened on the reply side. It opens with nothing: the
REM scan happens when you press Find who needs a reply, not before.
set "EXTRA=!EXTRA:--replies=!"
if not defined HANDLE (
    echo.
    echo Reply mode needs to know which channel you comment from.
    echo Set it once so you never see this again:
    echo     setx YTCOMMENT_MY_HANDLE yourhandle
    echo.
    set /p "HANDLE=Your handle for this run: "
    if not defined HANDLE goto :nothing
)
echo.
echo Opening the window on the reply side, as @!HANDLE! ...
echo.
start "" "!YTCOMMENT_PYTHONW!" -m llm_youtube_comment_generation.interfaces.gui.launcher gui !VIDEOARG! --my-handle "!HANDLE!" !EXTRA!
goto :done

:preview
echo.
echo Opening a preview window. Nothing is fetched and nothing is saved.
echo.
start "" "!YTCOMMENT_PYTHONW!" -m llm_youtube_comment_generation.interfaces.gui.launcher gui --preview
goto :done

:nothing
echo No video given.
goto :done

:failed
echo.
echo That did not work. Run doctor.bat to check the installation.

:done
endlocal
