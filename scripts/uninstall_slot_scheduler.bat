@echo off
REM Remove the slot scheduler tasks installed by install_slot_scheduler.bat.
REM Safe to run multiple times.

setlocal
echo === Removing slot scheduler tasks ===

for %%D in (mon tue wed thu fri) do (
    schtasks /delete /tn "ai-publish-slot-%%D" /f >nul 2>&1
    if errorlevel 1 (
        echo [skip] ai-publish-slot-%%D not found
    ) else (
        echo [OK]   ai-publish-slot-%%D removed
    )
)

REM Legacy task names (pre-2026-05-28 evening revision) — clean up
REM if anyone still has the old install.
schtasks /delete /tn "ai-publish-slot-tue" /f >nul 2>&1
schtasks /delete /tn "ai-publish-slot-fri" /f >nul 2>&1

echo.
echo === Done. ===
endlocal
