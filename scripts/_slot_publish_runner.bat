@echo off
REM Wrapper called by Windows Task Scheduler for peak-slot publishing.
REM Kept as a separate file so install_slot_scheduler.bat can register
REM a simple /tr "<path>" without needing in-line cmd escapes.
REM
REM Behavior: cd into repo, run _publish_at_slot.py, append all output
REM to data/_logs/slot_publish.log. _publish_at_slot.py itself decides
REM whether to publish (slot check) — this wrapper just routes I/O.

setlocal
set "REPO=%~dp0..\"
pushd "%REPO%"
set "REPO=%CD%"
popd

if not exist "%REPO%\data\_logs" mkdir "%REPO%\data\_logs"
set "LOG=%REPO%\data\_logs\slot_publish.log"

echo. >> "%LOG%"
echo === slot fire %DATE% %TIME% === >> "%LOG%"
cd /d "%REPO%"
py scripts\_publish_at_slot.py >> "%LOG%" 2>&1
echo --- exit %ERRORLEVEL% --- >> "%LOG%"
endlocal
