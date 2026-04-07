#!/bin/bash
# AI記事自動生成システム セットアップスクリプト
set -e

echo "========================================="
echo "AI記事自動生成システム セットアップ"
echo "========================================="

# Python確認
if ! command -v python3 &> /dev/null; then
    echo "エラー: Python3が見つかりません。インストールしてください。"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1)
echo "✓ $PYTHON_VERSION"

# venv作成
echo ""
echo "--- 仮想環境作成 ---"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ venv作成完了"
else
    echo "✓ venv既存"
fi

# venv有効化
source venv/bin/activate
echo "✓ venv有効化"

# pip更新 & 依存インストール
echo ""
echo "--- 依存関係インストール ---"
pip install --upgrade pip
pip install -r requirements.txt
echo "✓ 依存関係インストール完了"

# Ollamaインストール確認
echo ""
echo "--- Ollama確認 ---"
if command -v ollama &> /dev/null; then
    echo "✓ Ollama既存: $(ollama --version)"
else
    echo "Ollamaをインストールします..."
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        curl -fsSL https://ollama.ai/install.sh | sh
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "macOS: https://ollama.ai/download からインストールしてください"
    else
        echo "Windows: https://ollama.ai/download からインストールしてください"
    fi
fi

# CodeLlamaモデル
echo ""
echo "--- CodeLlamaモデル ---"
if command -v ollama &> /dev/null; then
    if ollama list 2>/dev/null | grep -q "codellama"; then
        echo "✓ CodeLlama既存"
    else
        echo "CodeLlamaをダウンロードします（約4GB）..."
        ollama pull codellama
        echo "✓ CodeLlamaダウンロード完了"
    fi
fi

# ディレクトリ作成
echo ""
echo "--- ディレクトリ作成 ---"
mkdir -p logs data docs/images
echo "✓ logs/ data/ docs/images/ 作成完了"

# 設定ファイルコピー
echo ""
echo "--- 設定ファイル ---"
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✓ .env作成 → 編集してください"
else
    echo "✓ .env既存"
fi

if [ ! -f "config/settings.yaml" ]; then
    cp config/settings.yaml.example config/settings.yaml
    echo "✓ config/settings.yaml作成 → 編集してください"
else
    echo "✓ config/settings.yaml既存"
fi

echo ""
echo "========================================="
echo "セットアップ完了！"
echo ""
echo "次のステップ:"
echo "  1. .env を編集（API キー等を設定）"
echo "  2. config/settings.yaml を編集"
echo "  3. config/credentials.json にGoogle認証情報を配置"
echo "  4. python main.py --collect-only で動作確認"
echo "========================================="
