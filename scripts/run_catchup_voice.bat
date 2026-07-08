@echo off
REM Manual rerun/debug entry point for the voice digest.
REM
REM catchup itself (main.py / run_catchup.py) now triggers this
REM automatically (detached) after every successful Slack post
REM (2026-07-08, user: "全自動に戻してほしい，MP3をデスクトップに
REM 置くまで"). Use this .bat only to re-voice the last delivered
REM digest by hand (e.g. after tweaking CATCHUP_TTS_RATE/VOICE).
REM
REM Takes ~1-2 minutes to run (gemma4 script + edge-tts synthesis),
REM then updates the "AIキャッチアップを聞く" desktop shortcut to
REM point at the fresh mp3. This window closes itself once the
REM detached worker has been launched.

cd /d "%~dp0.."
py -m catchup.tts --last
echo.
echo デスクトップの「AIキャッチアップを聞く」を更新しています...
echo (gemma4 + 音声合成で1〜2分かかります。完了したらこのウィンドウは閉じてOKです)
pause
