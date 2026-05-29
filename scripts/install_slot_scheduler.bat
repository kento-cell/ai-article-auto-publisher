@echo off
REM Install Windows Task Scheduler tasks for note publish slot automation.
REM
REM Registers 5 weekly tasks (Mon-Fri 12:00 JST) that fire the wrapper.
REM Per user 2026-05-28: 平日 daytime only (user at office, PC idle).
REM Weekend + evening slots intentionally excluded.
REM
REM Tasks:
REM   ai-publish-slot-mon  Mon 12:00 JST
REM   ai-publish-slot-tue  Tue 12:00 JST
REM   ai-publish-slot-wed  Wed 12:00 JST
REM   ai-publish-slot-thu  Thu 12:00 JST
REM   ai-publish-slot-fri  Fri 12:00 JST
REM
REM Each task runs scripts\_slot_publish_runner.bat which routes
REM output to data\_logs\slot_publish.log. _publish_at_slot.py itself
REM decides whether to publish (slot validation, cap check).
REM
REM cap=1/day so 5 weekly fires = up to 5 publishes/week (one queue
REM article per weekday). If queue empty on a given day, task just
REM exits — no harm done.
REM
REM Idempotent: deletes existing tasks before recreating. Survives
REM reboot. Pause / disable individual days via Task Scheduler GUI
REM (taskschd.msc) or `schtasks /change /tn <name> /disable`.
REM
REM Run as: scripts\install_slot_scheduler.bat
REM Uninstall: scripts\uninstall_slot_scheduler.bat

setlocal
set "REPO=%~dp0..\"
pushd "%REPO%"
set "REPO=%CD%"
popd

set "RUNNER=%REPO%\scripts\_slot_publish_runner.bat"

echo === Installing slot scheduler tasks ===
echo Repo:   %REPO%
echo Runner: %RUNNER%
echo.

if not exist "%RUNNER%" (
    echo [FATAL] runner not found: %RUNNER%
    exit /b 1
)

REM --- Delete existing tasks (ignore errors) ---
for %%D in (mon tue wed thu fri) do schtasks /delete /tn "ai-publish-slot-%%D" /f >nul 2>&1

REM --- Register Mon-Fri 12:00 ---
for %%D in (MON TUE WED THU FRI) do (
    schtasks /create /tn "ai-publish-slot-%%D" /sc weekly /d %%D /st 12:00 /tr "\"%RUNNER%\"" /rl LIMITED /f >nul
    if errorlevel 1 (
        echo [FAIL] ai-publish-slot-%%D
    ) else (
        echo [OK]   ai-publish-slot-%%D ^(12:00 JST^)
    )
)

echo.
echo === Done. ===
echo === Verify: schtasks /query /tn ai-publish-slot-mon ===
echo === GUI:    taskschd.msc ^(タスクスケジューラ ライブラリ^) ===
echo === Pause day: schtasks /change /tn ai-publish-slot-wed /disable ===
echo === Log:    data\_logs\slot_publish.log ===
endlocal
