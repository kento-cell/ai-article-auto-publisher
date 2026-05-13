# bootstrap.ps1 — Windows 環境の初回セットアップ
# 別マシンに repo clone した直後に走らせる: venv 構築 + 依存 + Playwright + Ollama 確認
# + 設定ファイル雛形作成 + 手動セットアップ手順の案内。
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
#
# 副作用: venv ディレクトリ作成、site-packages インストール、ollama pull。
# .env / config/settings.yaml がなければ .example からコピーするが既存は触らない。

$ErrorActionPreference = "Stop"

function Section($msg) {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host $msg -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Need($cmd, $url) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "  [MISSING] $cmd — install from $url" -ForegroundColor Yellow
        return $false
    }
    Write-Host "  [OK] $cmd" -ForegroundColor Green
    return $true
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repo
Write-Host "repo: $repo"

# 1. 前提チェック
Section "前提コマンド"
$ok = $true
$ok = (Need "py" "https://www.python.org/downloads/") -and $ok
$ok = (Need "git" "https://git-scm.com/download/win") -and $ok
$_brave_warn = -not (Test-Path "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe")
if ($_brave_warn) {
    Write-Host "  [MISSING] Brave — install from https://brave.com" -ForegroundColor Yellow
    Write-Host "    (note publishing と ChatGPT 画像生成で必要)" -ForegroundColor Yellow
}
$ollama_ok = Need "ollama" "https://ollama.ai/download"
if (-not $ok) {
    Write-Host "前提コマンドが揃っていません。上記をインストールしてから再実行してください。" -ForegroundColor Red
    exit 1
}

# 2. venv
Section "Python 仮想環境 (venv)"
if (-not (Test-Path "venv")) {
    py -m venv venv
    Write-Host "  venv 作成完了" -ForegroundColor Green
} else {
    Write-Host "  venv 既存 — そのまま使う" -ForegroundColor Green
}
$venvPy = Join-Path $repo "venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "  venv/Scripts/python.exe が見つからない — venv 作成失敗?" -ForegroundColor Red
    exit 1
}

# 3. 依存
Section "Python 依存パッケージ"
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt
Write-Host "  pip install 完了" -ForegroundColor Green

# 4. Playwright
Section "Playwright (Chromium for note/Zenn/ChatGPT 自動操作)"
& $venvPy -m playwright install chromium
Write-Host "  playwright install 完了" -ForegroundColor Green

# 5. Ollama + gemma3
if ($ollama_ok) {
    Section "Ollama gemma3:12b モデル"
    $models = (& ollama list 2>$null) -join "`n"
    if ($models -match "gemma3:12b") {
        Write-Host "  gemma3:12b 既存" -ForegroundColor Green
    } else {
        Write-Host "  gemma3:12b ダウンロード中 (約 8GB)…"
        & ollama pull gemma3:12b
        Write-Host "  gemma3:12b 完了" -ForegroundColor Green
    }
}

# 6. 設定ファイル雛形
Section "設定ファイル"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "  .env を .env.example から作成 — 編集要" -ForegroundColor Yellow
} else {
    Write-Host "  .env 既存" -ForegroundColor Green
}
if ((Test-Path "config/settings.yaml.example") -and -not (Test-Path "config/settings.yaml")) {
    Copy-Item "config/settings.yaml.example" "config/settings.yaml"
    Write-Host "  config/settings.yaml を .example から作成 — 編集要" -ForegroundColor Yellow
} else {
    Write-Host "  config/settings.yaml 既存 or example なし" -ForegroundColor Green
}

# 7. ディレクトリ
foreach ($d in @("logs", "data/articles", "data/scraps", "data/images/covers", "data/images/stock")) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}
Write-Host "  ローカルディレクトリ作成完了" -ForegroundColor Green

# 8. git hook
Section "git pre-commit hook"
& git config core.hooksPath scripts/git-hooks
Write-Host "  core.hooksPath = scripts/git-hooks に設定" -ForegroundColor Green

# 9. デグレチェック
Section "import デグレチェック"
$envBak = $env:PYTHONIOENCODING
$env:PYTHONIOENCODING = "utf-8"
try {
    & $venvPy -c "import main; print('OK')"
    Write-Host "  main import OK" -ForegroundColor Green
} catch {
    Write-Host "  main import FAILED — pip install を疑う or 依存が足りない" -ForegroundColor Red
}
$env:PYTHONIOENCODING = $envBak

# 10. 次のステップ
Section "次のステップ (手動セットアップが必要)"
@"
1. .env を編集して以下を設定:
   - GOOGLE_SHEET_ID (Google Sheets ダッシュボードの ID)
   - SLACK_BOT_TOKEN / SLACK_CHANNEL_ID (使うなら)
   - UNSPLASH_ACCESS_KEY / PEXELS_API_KEY (画像 fallback 用)
   - ZENN_REPO_PATH (Zenn 投稿用のローカル git clone パス)
   - CHATGPT_CDP_PORT=9222 (既定でセット済、Brave を CDP モードで使うため)

2. config/credentials.json に Google Sheets のサービスアカウント JSON を配置

3. config/settings.yaml を編集 (チェーン店ブラックリスト、deny patterns 等)

4. 認証:
   - Brave で note.com / zenn.dev / chatgpt.com にログイン
     ※ note は scripts/note_login.py、Zenn は scripts/zenn_login.py で
       cookie 永続化補助あり
   - ChatGPT 画像生成チャットの share URL を data/chatgpt-image-chat-url.txt に保存

5. 動作確認:
   venv\Scripts\python.exe -c "import main"
   venv\Scripts\python.exe scripts/test_hallucination_deny.py
   venv\Scripts\python.exe main.py --collect-only

6. 通常運用は CLAUDE.md / AGENTS.md の Compound Workflow Playbook を参照
"@ | Write-Host

Write-Host ""
Write-Host "bootstrap 完了" -ForegroundColor Green
