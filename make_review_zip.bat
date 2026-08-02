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
set "ARCHIVE_DIGEST=%ARCHIVE%.sha256"
set "DIGEST_TEMP=%ARCHIVE_DIGEST%.new"
rem git wants forward slashes and no trailing separator for safe.directory.
rem It is set for this repository only: the check exists to stop a stranger's
rem hooks running, and this script already lives in the checkout it exports.
set "PROJECT_ROOT_POSIX=%PROJECT_ROOT:~0,-1%"
set "PROJECT_ROOT_POSIX=%PROJECT_ROOT_POSIX:\=/%"
rem Where a failed verification report is kept once the stage is gone.
set "FAILED_REPORT=%REVIEW_DIR%\REVIEW_VERIFICATION_FAILED.md"

rem Nothing is staged yet, so an early failure has nothing to remove. The
rem cleanup routine keys off this: it must never delete a folder this run did
rem not create.
set "STAGE_CREATED="

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
rem Tested by existence, not by errorlevel: when the folder already exists the
rem mkdir above never runs and errorlevel still holds whatever the previous
rem command left behind.
if not exist "%REVIEW_DIR%" (
    echo Could not create:
    echo   %REVIEW_DIR%
    exit /b 3
)

rem Remove staging folders abandoned by an earlier failed run. Every exit path
rem below now cleans up after itself, but a folder left by an older build of
rem this script would otherwise sit here forever at a few megabytes each. The
rem pattern matches only this script's own naming, and it runs before the new
rem stage is created so it can never match the current one.
for /d %%D in ("%REVIEW_DIR%\_review_stage_*") do rd /s /q "%%~fD" 2>nul

rem Drop any report left by an earlier failure, so a report sitting here always
rem describes the run that just finished rather than an older one.
if exist "%FAILED_REPORT%" del /q "%FAILED_REPORT%"

rem Work on a disposable copy so WinRAR never archives the live project directly.
if exist "%STAGE%" (
    echo Could not select a unique staging folder:
    echo   %STAGE%
    exit /b 4
)
mkdir "%STAGE%"
if not exist "%STAGE%" (
    echo Could not create the staging folder:
    echo   %STAGE%
    exit /b 4
)
set "STAGE_CREATED=1"

if exist "%TEMP_ARCHIVE%" del /q "%TEMP_ARCHIVE%"
if exist "%TEMP_ARCHIVE%" (
    echo Could not remove an incomplete temporary review archive:
    echo   %TEMP_ARCHIVE%
    set "EXITCODE=5"
    goto :cleanup
)

rem The staged tree is the committed tree, produced by git rather than copied
rem out of the working directory.
rem
rem It used to be an allowlist: six robocopy calls and twelve named files.
rem The release-input rule that has to agree with it is a denylist. Two
rem opposite policies over one domain drift by construction, and each drift
rem cost a full release-matrix run to discover -- docs/screenshots first, then
rem docs/SCREENSHOTS.md added beside it. A file was a release input the moment
rem it was created and was staged only if somebody remembered to edit this
rem list.
rem
rem git archive removes the second policy. What ships is what is committed,
rem so nothing can be a release input without also being staged, and no
rem local edit or stray file can reach the archive at all. It applies
rem .gitattributes too, so .bat files arrive CRLF and Python arrives LF
rem exactly as a clean checkout would, which is what made the archive's bytes
rem depend on this machine before.
git -c safe.directory=%PROJECT_ROOT_POSIX% archive --format=tar HEAD | tar -x -C "%STAGE%"
if errorlevel 1 (
    echo Could not export the committed tree with git archive.
    echo Uncommitted work is never staged: commit it first.
    goto :copy_failed
)

if exist "%REVIEW_DIR%\RELEASE_VERIFICATION.md" (
    copy /y "%REVIEW_DIR%\RELEASE_VERIFICATION.md" "%STAGE%\" >nul
)
if exist "%REVIEW_DIR%\RELEASE_VERIFICATION.json" (
    copy /y "%REVIEW_DIR%\RELEASE_VERIFICATION.json" "%STAGE%\" >nul
)

rem The staged tree must actually contain what the reviewer is promised. An
rem earlier run exited with a partial stage that was missing src, tests and
rem tools entirely, because the copy step reported "nothing copied" as
rem success.
for %%D in ("src" "tests" "tools" "constraints" "docs\architecture") do (
    if not exist "%STAGE%\%%~D" (
        echo The staged tree is missing %%~D.
        goto :copy_failed
    )
)

pushd "%STAGE%"
"%PROJECT_PY%" tools\create_review_evidence.py
if errorlevel 1 (
    popd
    echo Review verification failed. The review ZIP was not created.
    rem Rescue the report before the staging folder is removed. This used to
    rem survive only because a failed run leaked the whole stage; now that
    rem cleanup is reliable, the one file worth reading has to be copied out
    rem deliberately.
    rem
    rem Announced only when it exists. The gates write this report, so a
    rem failure *before* them leaves none — release-evidence validation is
    rem exactly such a case, and the old unconditional message sent the
    rem operator looking for a file that was never created.
    if exist "%STAGE%\REVIEW_VERIFICATION.md" (
        copy /y "%STAGE%\REVIEW_VERIFICATION.md" "%FAILED_REPORT%" >nul
        echo See the recorded gate results in:
        echo   %FAILED_REPORT%
    ) else (
        echo It stopped before the gates ran, so no gate report was produced.
        echo The reason is printed above.
    )
    set "EXITCODE=8"
    goto :cleanup
)
start "" /wait "%WINRAR_EXE%" a -afzip -m5 -r -ep1 -y "%TEMP_ARCHIVE%" "*"

set "RAR_RESULT=%ERRORLEVEL%"
popd

if not "%RAR_RESULT%"=="0" (
    echo WinRAR failed with exit code %RAR_RESULT%.
    set "EXITCODE=%RAR_RESULT%"
    goto :cleanup
)

start "" /wait "%WINRAR_EXE%" t -y "%TEMP_ARCHIVE%"
set "RAR_RESULT=%ERRORLEVEL%"
if not "%RAR_RESULT%"=="0" (
    echo WinRAR could not verify the new ZIP. The previous ZIP was preserved.
    set "EXITCODE=%RAR_RESULT%"
    goto :cleanup
)

move /y "%TEMP_ARCHIVE%" "%ARCHIVE%" >nul
if errorlevel 1 (
    echo The new ZIP passed verification, but the previous ZIP could not be replaced:
    echo   %ARCHIVE%
    set "EXITCODE=5"
    goto :cleanup
)

rem Hashed into a temporary sidecar and moved into place only once it is
rem complete, so the published name never holds a partial digest.
rem
rem The archive has already been replaced by this point, so the previous
rem sidecar now describes a file that is gone. Writing straight over it left
rem the new ZIP paired with the old ZIP's digest whenever hashing failed, and
rem a wrong digest is worse than a missing one: an absent sidecar is visibly
rem absent, while a stale one looks authoritative and describes a different
rem archive. Either the digest matches the published ZIP or there is none.
if exist "%DIGEST_TEMP%" del /q "%DIGEST_TEMP%"
powershell.exe -NoProfile -Command "$hash=(Get-FileHash -Algorithm SHA256 -LiteralPath '%ARCHIVE%').Hash.ToLowerInvariant(); Set-Content -LiteralPath '%DIGEST_TEMP%' -Value ($hash + '  Youtube_Comment_Generation_review.zip') -Encoding ascii"
if errorlevel 1 goto :digest_failed
if not exist "%DIGEST_TEMP%" goto :digest_failed
move /y "%DIGEST_TEMP%" "%ARCHIVE_DIGEST%" >nul
if errorlevel 1 goto :digest_failed

powershell.exe -NoProfile -Command "(Get-Item -LiteralPath '%ARCHIVE%').LastWriteTime = Get-Date"
if errorlevel 1 (
    echo The ZIP was created, but its displayed modified time could not be updated.
    set "EXITCODE=7"
    goto :cleanup
)

echo.
echo Review ZIP created and tested:
echo   %ARCHIVE%
set "EXITCODE=0"
goto :cleanup

:copy_failed
echo Could not prepare the review files.
set "EXITCODE=6"
goto :cleanup

rem --------------------------------------------------------------------------
rem The published ZIP is already in place and cannot be un-replaced, so the only
rem safe end state is no sidecar at all. Removing the stale one is what keeps
rem "the digest beside the archive describes the archive" true at every moment.
rem --------------------------------------------------------------------------
:digest_failed
echo The ZIP passed verification, but its SHA-256 sidecar could not be written.
echo The stale digest was removed; the archive is published without one:
echo   %ARCHIVE%
if exist "%DIGEST_TEMP%" del /q "%DIGEST_TEMP%"
if exist "%ARCHIVE_DIGEST%" del /q "%ARCHIVE_DIGEST%"
set "EXITCODE=7"
goto :cleanup

rem --------------------------------------------------------------------------
rem The single exit. Every failure above reaches this, because each one used to
rem exit directly and leave the staging folder behind; a failed run silently
rem cost a few megabytes that nothing ever reclaimed.
rem --------------------------------------------------------------------------
:cleanup
rem Never rmdir the current directory. The WinRAR step runs inside the stage,
rem and an early failure there could otherwise leave us standing in it.
cd /d "%PROJECT_ROOT%"
if defined STAGE_CREATED rd /s /q "%STAGE%" 2>nul
rem A partial archive is never left for the next run to trip over. The
rem published ZIP is already renamed by this point, so this only ever removes
rem an incomplete temporary file.
if not "%EXITCODE%"=="0" (
    if exist "%TEMP_ARCHIVE%" del /q "%TEMP_ARCHIVE%"
)
exit /b %EXITCODE%
