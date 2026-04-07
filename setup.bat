@echo off
chcp 65001 >nul
echo =========================================
echo AI記事自動生成システム セットアップ (Windows)
echo =========================================

:: Python確認
python --version >nul 2>&1
if errorlevel 1 (
    echo エラー: Pythonが見つかりません。インストールしてください。
    pause
    exit /b 1
)
echo [OK] Python確認済み

:: venv作成
if not exist "venv" (
    echo --- 仮想環境作成 ---
    python -m venv venv
    echo [OK] venv作成完了
) else (
    echo [OK] venv既存
)

:: venv有効化
call venv\Scripts\activate.bat
echo [OK] venv有効化

:: pip更新 + 依存インストール
echo --- 依存関係インストール ---
pip install --upgrade pip
pip install -r requirements.txt
echo [OK] 依存関係インストール完了

:: ディレクトリ作成
if not exist "logs" mkdir logs
if not exist "data" mkdir data
if not exist "docs\images" mkdir docs\images
echo [OK] ディレクトリ作成完了

:: 設定ファイルコピー
if not exist ".env" (
    copy .env.example .env
    echo [OK] .env作成 → 編集してください
) else (
    echo [OK] .env既存
)

if not exist "config\settings.yaml" (
    copy config\settings.yaml.example config\settings.yaml
    echo [OK] config\settings.yaml作成 → 編集してください
) else (
    echo [OK] config\settings.yaml既存
)

:: Ollama確認
ollama --version >nul 2>&1
if errorlevel 1 (
    echo [注意] Ollamaが見つかりません。https://ollama.ai/download からインストールしてください。
) else (
    echo [OK] Ollama確認済み
    echo --- CodeLlamaモデル確認 ---
    ollama list 2>nul | findstr /i "codellama" >nul
    if errorlevel 1 (
        echo CodeLlamaをダウンロードします...
        ollama pull codellama
    ) else (
        echo [OK] CodeLlama既存
    )
)

echo.
echo =========================================
echo セットアップ完了！
echo.
echo 次のステップ:
echo   1. .env を編集（APIキー等を設定）
echo   2. config\settings.yaml を編集
echo   3. config\credentials.json にGoogle認証情報を配置
echo   4. python main.py --setup-sheets でSheets初期設定
echo   5. python main.py --collect-only で動作確認
echo =========================================
pause
