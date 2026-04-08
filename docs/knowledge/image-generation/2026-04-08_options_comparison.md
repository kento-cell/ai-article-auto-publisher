# 画像生成ツール比較（2026-04-08時点）

## コスト0円で使えるもの

### Pollinations.ai (推奨)
- URL: https://pollinations.ai/
- APIキー不要、即使える
- `https://image.pollinations.ai/prompt/{PROMPT}` に GETするだけで画像が返る
- 解像度・モデル指定可能
- レートリミット緩い

### Stable Diffusion ローカル
- ComfyUI or AUTOMATIC1111
- RTX 3070 (8GB VRAM) で SD 1.5は快適、SDXLはギリギリ
- セットアップに時間がかかる
- 完全ローカル、プライバシー安全

### Bing Image Creator
- https://www.bing.com/create
- Microsoft認証必要
- DALL-E 3を無料で（制限あり）
- API化が面倒（Cookieベース）

## 有料

### DALL-E 3 (OpenAI)
- 高品質、プロンプト理解が優秀
- $0.040/枚 (standard) ~ $0.080/枚 (HD)
- OpenAI APIキー必要

### Leonardo.ai
- 無料枠150トークン/日
- 商用OK

## 記事カバー画像に何を使うべきか

| 優先度 | 選択肢 | 理由 |
|--------|--------|------|
| 1 | Pollinations.ai | 0円、APIキー不要、即時利用 |
| 2 | Unsplash/Pexels (既存) | ストック写真、確実 |
| 3 | SD ローカル | 品質重視なら |

## Pollinations.ai の使い方

```python
import requests
from urllib.parse import quote

def generate_cover(prompt: str, output_path: str) -> str:
    url = f"https://image.pollinations.ai/prompt/{quote(prompt)}"
    params = {
        "width": 1200,
        "height": 630,  # note cover ratio
        "model": "flux",
        "nologo": "true",
    }
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        f.write(resp.content)
    return output_path
```

## プロンプト設計

記事のトピックから英語プロンプトを生成:
- 日本語タイトル → キーワード抽出 → 英訳 → ビジュアルディスクリプション化
- 例: 「AIエージェント5体が議論して記事を書く」
  → "Five AI agents discussing around a futuristic table, cyberpunk style, blue and purple lighting, tech illustration"
