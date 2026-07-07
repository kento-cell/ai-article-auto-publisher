@echo off
REM Launch Brave with the CDP debug port so the ChatGPT image pipeline
REM can attach via connect_over_cdp("http://127.0.0.1:9222"). Tabs and
REM history are shared with normal Brave use (no separate profile);
REM Brave's session-restore brings your open tabs back after the
REM restart below.
REM
REM Usage: double-click this file (or pin it to the taskbar) whenever
REM        you want the ChatGPT image pipeline available -- including
REM        for Slack-bot-triggered `generate` / `publish` runs. While
REM        this Brave stays open, the bot can generate ChatGPT images
REM        without anyone having to close Brave first.
REM
REM Any already-running Brave is killed first ON PURPOSE: a normal
REM Brave launch does NOT expose the debug port, and Chromium silently
REM ignores the --remote-debugging-port flag when an instance is
REM already running. The kill + relaunch guarantees CDP is actually on.

REM 2026-07-07: /min + --disable-backgrounding-occluded-windows so the
REM automation Brave stays minimized in the taskbar instead of stealing
REM the screen during routine runs (user works from home on this PC
REM now). The disable-backgrounding flags keep Chromium rendering
REM (canvas/GPU raster) alive while minimized -- without them the
REM Gemini image extraction (canvas.toDataURL) can return blank frames.
REM To use Brave yourself, just click it in the taskbar as usual.

echo Restarting Brave (minimized) with CDP debug port 9222...
taskkill /F /IM brave.exe >nul 2>&1
timeout /t 2 /nobreak >nul
start "" /min "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222 --disable-backgrounding-occluded-windows --disable-renderer-backgrounding
echo.
echo Brave is now running MINIMIZED with CDP on port 9222.
echo It stays in the taskbar; automation attaches without stealing
echo the screen. Click the taskbar icon to use it yourself.
