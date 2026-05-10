"""One-shot Slack webhook health-check.

Posts a small ping to SLACK_WEBHOOK_URL and prints the HTTP status.
Used to confirm whether the webhook URL is still valid after the
"Slack 有効期限" event on 2026-05-07.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
env_file = _REPO / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import requests  # noqa: E402

url = os.environ.get("SLACK_WEBHOOK_URL")
if not url:
    print("NO_WEBHOOK_CONFIGURED")
    sys.exit(2)

try:
    r = requests.post(
        url,
        json={"text": "[ai-publisher] webhook health-check (2026-05-07)"},
        timeout=10,
    )
    print(f"status={r.status_code} body={r.text[:200]}")
    sys.exit(0 if r.status_code == 200 else 1)
except Exception as exc:
    print(f"ERROR: {exc}")
    sys.exit(3)
