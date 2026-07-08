@echo off
REM Opt-in voice digest for the most recent catchup run.
REM
REM Does nothing unless you double-click this file. catchup itself
REM (main.py / run_catchup.py) does NOT trigger this automatically —
REM gemma4 + edge-tts only run when you explicitly ask (2026-07-08,
REM user: "毎回自動で回るのはもったいない").
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
