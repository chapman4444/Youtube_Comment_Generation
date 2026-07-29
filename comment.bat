@echo off
REM Build a comment packet. Double-click, or drop a URL on it.
REM
REM You do not have to type the video. Copy its URL in your browser and run
REM this; the video is taken from the clipboard. A URL or ID passed as the
REM first argument still wins over whatever is on the clipboard.
REM
REM Anything else you pass is handed straight to ytcomment, so
REM   comment.bat --dial grounding=summary
REM   comment.bat https://youtu.be/xxxxxxxxxxx --dial humor=none --no-copy
REM both work. Run "ytcomment comment build --help" for the full list.
REM
REM The packet is written to output\<video>_<timestamp>\packet.md and lands
REM on your clipboard ready to paste. Nothing is ever posted.

setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM Always run the code beside this launcher, never an older editable install
REM from another folder.
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "YTCOMMENT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "!YTCOMMENT_PYTHON!" set "YTCOMMENT_PYTHON=python"

REM Arguments are split off %* rather than read as %1, %2. cmd treats "=" as
REM an argument delimiter, so %1 turns "--dial grounding=summary" into three
REM tokens and "watch?v=xxxx" into two. Splitting on spaces alone keeps both
REM intact. The first token is the video only when it is not an option.
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

REM Only ask when the answer was not already given on the command line.
set "REGISTERS="
echo !EXTRA! | findstr /i /c:"--registers" >nul
if errorlevel 1 (
    echo.
    set /p "REGISTERS=Registers (blank for the usual five): "
)
echo.

:run
if "!REGISTERS!"=="" (
    "!YTCOMMENT_PYTHON!" -m llm_youtube_comment_generation.interfaces.cli.main comment build !VIDEOARG! !EXTRA!
) else (
    "!YTCOMMENT_PYTHON!" -m llm_youtube_comment_generation.interfaces.cli.main comment build !VIDEOARG! --registers "!REGISTERS!" !EXTRA!
)
set "RC=!ERRORLEVEL!"
if "!RC!"=="0" goto :ok

REM Branch on which failure it was. Retyping the URL used to be the answer to
REM every non-zero exit, so a video with no transcript -- exit 5, nothing to
REM do with the video -- asked for the URL, got the same one back, and spent
REM a second scan proving the same thing.
if "!RC!"=="5" goto :notranscript
if "!RC!"=="3" goto :askvideo
goto :failed

:notranscript
REM Exit 5 here means there are no captions. The packet can still be built
REM from the metadata and the comment section, and it counts the comments and
REM says in its own text that it has no transcript.
echo.
set /p "ANYWAY=Build it from the comments alone? [y/N] "
if /i not "!ANYWAY!"=="y" goto :done
set "EXTRA=!EXTRA! --allow-no-transcript"
echo.
goto :run

:askvideo
REM Exit 3 is a configuration failure, which is where "no video on the
REM clipboard" and "the clipboard holds a packet" both land. Asking is only
REM useful when nothing was given on the command line: a video that was
REM supplied and rejected will be rejected again unchanged.
if defined VIDEOARG goto :failed
if defined ASKED goto :failed
set "ASKED=1"
echo.
set /p "TYPED=YouTube URL or video ID: "
if "!TYPED!"=="" goto :nothing
set "VIDEOARG="!TYPED!""
echo.
goto :run

:ok
echo.
REM A dry run builds nothing, so it must not claim a packet is waiting.
echo !EXTRA! | findstr /i /c:"--dry-run" >nul
if errorlevel 1 (
    echo Done. The packet is on your clipboard; paste it into your model.
) else (
    echo Dry run finished. Nothing was built and the clipboard is untouched.
)
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
