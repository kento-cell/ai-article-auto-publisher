"""Inspect & purge stray chats from the ChatGPT sidebar via CDP.

Reads the user's current sidebar via ``/backend-api/conversations``,
then soft-deletes everything that matches our throwaway-chat pattern
("New chat", "画像生成制限通知", titles starting with 画像 / image-gen
artefacts). User-owned conversations (e.g. "リモート作業環境提案",
"契約云々") are NEVER touched — they're matched against an explicit
allow-list of test/probe titles.

Pre-condition: Brave running with ``--remote-debugging-port=9222``.

Usage::

    py scripts/_purge_chatgpt_sidebar.py            # dry-run, lists candidates
    py scripts/_purge_chatgpt_sidebar.py --apply    # actually delete
"""
from __future__ import annotations

import argparse
import sys

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402

CDP = "http://localhost:9222"

# Titles we created during today's testing — safe to soft-delete.
DELETE_TITLE_EXACT = {
    "New chat",
    "新しいチャット",
    "画像生成制限通知",
    "画像生成制限について",
    "画像生成制限",
    "画像作成の制限について",
    "画像作成の制限",
    "サムネイル画像作成依頼",
    "画像生成リクエスト",
    "画像生成依頼",
    "画像生成依頼ガイド",
    "画像生成依頼方法",
    "画像生成の依頼",
    "テンプレート確認と指示",
    "格闘ゲーム キービジュアル",
    "夢幻的な雰囲気",
    "cleanup-test",
}

# Match-prefix list — chats whose title STARTS WITH any of these
# strings are also throwaway (covers ChatGPT auto-renaming a chat to
# something like "画像生成制限についてのお知らせ").
DELETE_TITLE_PREFIX = (
    "画像生成制限",
    "画像作成の制限",
    "画像生成依頼",
    "画像生成リクエスト",
    "画像生成テンプレ",
    "テンプレート確認",
    "サムネイル画像",
    "cleanup-test",
)


def _find_or_open_chatgpt_page(ctx):
    """Reuse an existing chatgpt.com tab (so we have an authed origin),
    or open one if none exists."""
    for pg in ctx.pages:
        try:
            if (pg.url or "").startswith("https://chatgpt.com"):
                return pg, False
        except Exception:
            continue
    pg = ctx.new_page()
    pg.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60_000)
    pg.wait_for_timeout(2_500)
    return pg, True


def _list_conversations(page) -> list[dict]:
    return page.evaluate(
        """async () => {
            const sess = await fetch('/api/auth/session', {credentials:'include'});
            const j = await sess.json();
            const token = j.accessToken;
            const r = await fetch(
                '/backend-api/conversations?offset=0&limit=30&order=updated',
                {headers: {'Authorization': 'Bearer ' + token}, credentials:'include'},
            );
            return await r.json();
        }"""
    )


def _delete_conversation(page, chat_id: str) -> dict:
    return page.evaluate(
        """async (id) => {
            const sess = await fetch('/api/auth/session', {credentials:'include'});
            const j = await sess.json();
            const token = j.accessToken;
            const r = await fetch('/backend-api/conversation/' + id, {
                method:'PATCH',
                headers: {'Content-Type':'application/json', 'Authorization':'Bearer ' + token},
                body: JSON.stringify({is_visible:false}),
                credentials:'include',
            });
            return {status:r.status, ok:r.ok};
        }""",
        chat_id,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually delete; without this, dry-run only.")
    ap.add_argument("--limit", type=int, default=30,
                    help="How many recent conversations to consider.")
    args = ap.parse_args()

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP)
        except Exception as exc:
            print(f"ERROR: cannot connect to {CDP}: {exc}")
            return 2
        if not browser.contexts:
            print("ERROR: no contexts")
            return 2
        ctx = browser.contexts[0]
        page, opened_temp = _find_or_open_chatgpt_page(ctx)

        try:
            def _is_throwaway(t: str) -> bool:
                if t in DELETE_TITLE_EXACT:
                    return True
                return any(t.startswith(pre) for pre in DELETE_TITLE_PREFIX)

            data = _list_conversations(page)
            items = data.get("items") or data.get("conversations") or []
            print(f"current sidebar (top {len(items)}):")
            for it in items:
                title = (it.get("title") or "").strip()
                cid = it.get("id", "")
                vis = it.get("is_visible", True)
                marker = "✓" if _is_throwaway(title) else " "
                print(f"  {marker} [{vis}] {title!r:35} {cid}")

            targets = [
                it for it in items
                if _is_throwaway((it.get("title") or "").strip())
                and it.get("is_visible", True)
            ]
            print()
            print(f"deletable targets: {len(targets)}")

            if not args.apply:
                print("DRY RUN — pass --apply to delete")
                return 0

            ok = 0
            fail = 0
            for it in targets:
                cid = it["id"]
                title = (it.get("title") or "").strip()
                resp = _delete_conversation(page, cid)
                if resp.get("ok"):
                    ok += 1
                    print(f"  ✓ deleted: {title!r} ({cid[:12]})")
                else:
                    fail += 1
                    print(f"  ✗ failed:  {title!r} -> {resp}")
            print(f"DONE — deleted={ok} failed={fail}")
            # NOTE: we deliberately do NOT call pg.reload() on existing
            # chatgpt.com tabs. Reloading a /c/<id> tab can cause
            # ChatGPT to redirect to / (lost composer state, lost
            # working chat). Server-side is_visible=false is enough —
            # the sidebar drops the entry the next time the user
            # navigates within ChatGPT manually.
            print(
                "(server-side delete done; if a stale row still appears "
                "in the sidebar, click any other chat to refresh.)"
            )
            return 0 if fail == 0 else 1
        finally:
            if opened_temp:
                try:
                    page.close()
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
