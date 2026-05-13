@echo off
REM Launch Brave with CDP debug port so ChatGPT image gen can attach
REM via connect_over_cdp("http://localhost:9222"). Tabs/history are
REM shared with normal Brave use — no separate profile.
REM
REM Usage: just double-click this file (or pin it to taskbar).
REM        After this Brave is running with CDP enabled, and any
REM        `main.py --generate / --publish` run will use the
REM        ChatGPT image pipeline instead of the Pollinations fallback.
REM
REM If Brave is already running normally, close it FIRST (taskkill /F
REM /IM brave.exe) — otherwise the new flag is ignored by the
REM already-running session.

start "" "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222
