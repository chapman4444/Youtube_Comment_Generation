@echo off
setlocal

rem Console Rar.exe creates RAR archives only. WinRAR.exe supports ZIP output.
set "WINRAR_EXE=C:\Program Files\WinRAR\WinRAR.exe"
set "PROJECT_ROOT=%~dp0"
set "PROJECT_PY=%PROJECT_ROOT%.venv\Scripts\python.exe"
set "REVIEW_DIR=%PROJECT_ROOT%review_packages"
set "STAGE=%REVIEW_DIR%\_review_stage_%RANDOM%_%RANDOM%"
set "ARCHIVE=%REVIEW_DIR%\Youtube_Comment_Generation_review.zip"
set "TEMP_ARCHIVE=%REVIEW_DIR%\Youtube_Comment_Generation_review.new.zip"

if not exist "%WINRAR_EXE%" (
    echo WinRAR was not found:
    echo   %WINRAR_EXE%
    exit /b 2
)

call "%PROJECT_ROOT%setup_venv.bat" review
if errorlevel 1 (
    echo The project Python environment could not be prepared.
    exit /b 9
)

"%PROJECT_PY%" -c "import build, faster_whisper, pytest, requests, ruff, youtube_transcript_api, yt_dlp" >nul 2>&1
if errorlevel 1 (
    echo The review environment is missing one or more required verification modules.
    echo Run setup_venv.bat review to repair it.
    exit /b 10
)

if not exist "%REVIEW_DIR%" mkdir "%REVIEW_DIR%"
if errorlevel 1 (
    echo Could not create:
    echo   %REVIEW_DIR%
    exit /b 3
)

rem Work on a disposable copy so WinRAR never archives the live project directly.
if exist "%STAGE%" (
    echo Could not select a unique staging folder:
    echo   %STAGE%
    exit /b 4
)
mkdir "%STAGE%"
if errorlevel 1 (
    echo Could not create the staging folder:
    echo   %STAGE%
    exit /b 4
)

if exist "%TEMP_ARCHIVE%" del /q "%TEMP_ARCHIVE%"
if exist "%TEMP_ARCHIVE%" (
    echo Could not remove an incomplete temporary review archive:
    echo   %TEMP_ARCHIVE%
    exit /b 5
)

for %%F in (
    ".gitattributes"
    ".gitignore"
    "README.md"
    "REVIEW_PROMPT.md"
    "pyproject.toml"
    "comment.bat"
    "doctor.bat"
    "gui.bat"
    "make_review_zip.bat"
    "reply.bat"
    "scoreboard.bat"
    "setup_venv.bat"
) do (
    if exist "%PROJECT_ROOT%%%~F" copy /y "%PROJECT_ROOT%%%~F" "%STAGE%\" >nul
)

robocopy "%PROJECT_ROOT%docs\architecture" "%STAGE%\docs\architecture" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :copy_failed

robocopy "%PROJECT_ROOT%src" "%STAGE%\src" /E /XD __pycache__ *.egg-info /XF *.pyc *.pyo /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :copy_failed

robocopy "%PROJECT_ROOT%tests" "%STAGE%\tests" /E /XD __pycache__ .pytest_cache /XF *.pyc *.pyo test_frozen_inventory.py /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :copy_failed

robocopy "%PROJECT_ROOT%tools" "%STAGE%\tools" /E /XD __pycache__ /XF *.pyc *.pyo freeze_inventory.py write_not_ported.py /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :copy_failed

if exist "%PROJECT_ROOT%.github" (
    robocopy "%PROJECT_ROOT%.github" "%STAGE%\.github" /E /NFL /NDL /NJH /NJS /NP >nul
    if errorlevel 8 goto :copy_failed
)

pushd "%STAGE%"
"%PROJECT_PY%" tools\create_review_evidence.py
if errorlevel 1 (
    popd
    echo Review verification failed. The review ZIP was not created.
    echo See the staged REVIEW_VERIFICATION.md for the recorded results.
    exit /b 8
)
start "" /wait "%WINRAR_EXE%" a -afzip -m5 -r -ep1 -y "%TEMP_ARCHIVE%" "*"

set "RAR_RESULT=%ERRORLEVEL%"
popd

if not "%RAR_RESULT%"=="0" (
    echo WinRAR failed with exit code %RAR_RESULT%.
    if exist "%TEMP_ARCHIVE%" del /q "%TEMP_ARCHIVE%"
    exit /b %RAR_RESULT%
)

start "" /wait "%WINRAR_EXE%" t -y "%TEMP_ARCHIVE%"
set "RAR_RESULT=%ERRORLEVEL%"
if not "%RAR_RESULT%"=="0" (
    echo WinRAR could not verify the new ZIP. The previous ZIP was preserved.
    if exist "%TEMP_ARCHIVE%" del /q "%TEMP_ARCHIVE%"
    exit /b %RAR_RESULT%
)

move /y "%TEMP_ARCHIVE%" "%ARCHIVE%" >nul
if errorlevel 1 (
    echo The new ZIP passed verification, but the previous ZIP could not be replaced:
    echo   %ARCHIVE%
    if exist "%TEMP_ARCHIVE%" del /q "%TEMP_ARCHIVE%"
    exit /b 5
)

rmdir /s /q "%STAGE%"
powershell.exe -NoProfile -Command "(Get-Item -LiteralPath '%ARCHIVE%').LastWriteTime = Get-Date"
if errorlevel 1 (
    echo The ZIP was created, but its displayed modified time could not be updated.
    exit /b 7
)

echo.
echo Review ZIP created and tested:
echo   %ARCHIVE%
exit /b 0

:copy_failed
echo Could not prepare the review files.
exit /b 6
