"""One-shot (v3, final): replace the membership-add methods in
publishers/note_publisher.py with the verified selection-mode flow.

Verified 2026-06-01 via scripts/_diag_note_membership_dom.py v6-v9:
  * /notes -> row 「その他」 -> 「メンバーシップ特典追加・解除」 puts the page
    into selection mode (stays on /notes; .t-settings panel + per-plan
    「追加」 buttons appear; every article row gets input.a-checkbox__field).
  * A JS click on the INPUT toggles it WITHOUT triggering the full-card
    overlay link (a label click navigates to the article -- bug source).
  * There are 2 plans, each with its own 「追加」 button:
    「メンバー全員に公開」 and 「有益なAIプラン」. We pick by plan-card text.
"""
from __future__ import annotations
from pathlib import Path

T = Path(__file__).resolve().parent.parent / "publishers" / "note_publisher.py"

START = "    def _add_to_memberships_via_dashboard(self, article_url: str) -> bool:"
END = "    def _click_publish(self) -> str:"

NEW = '''    def _add_to_memberships_via_dashboard(self, article_url: str) -> bool:
        """Add the just-published article to the default membership plan.
        Delegates to :meth:`add_articles_to_membership`. Best-effort;
        never raises (the article is already live)."""
        slug = article_url.rstrip("/").split("/")[-1].split("?")[0]
        try:
            return self.add_articles_to_membership([slug]).get(slug, False)
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            logger.warning("[note] membership-add failed for %s: %s", slug, exc)
            return False

    def add_articles_to_membership(
        self, slugs: list[str], plan_name: str = "メンバー全員に公開",
    ) -> dict:
        """Add published articles to a membership plan's benefit list.

        Mechanism (verified scripts/_diag_note_membership_dom.py v6-v9,
        2026-06-01): /notes -> a row's 「その他」 -> 「メンバーシップ特典追加・解除」
        switches /notes into selection mode -- each article row exposes an
        ``input.a-checkbox__field`` (matched here by the row's /n/<slug>
        link) and a panel with a 「追加」 button per membership plan appears.

        Two subtleties this handles:
          * The checkbox sits under a full-card overlay <a>; a *label*
            click navigates to the article. We toggle the ``<input>``
            directly via JS, which checks it without navigating.
          * note has multiple plans, each with its own 「追加」. We click the
            one whose plan card text contains ``plan_name`` (default
            「メンバー全員に公開」 -- the general all-members plan).

        Adds only the ticked rows. Returns {slug: added}. Never raises.
        """
        result = {s: False for s in slugs}
        if self._page is None or not slugs:
            return result
        page = self._page
        try:
            page.goto(
                "https://note.com/notes",
                wait_until="domcontentloaded", timeout=30_000,
            )
            page.wait_for_timeout(2_500)
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            logger.warning("[note] /notes navigation failed: %s", exc)
            return result

        if not self._open_membership_modal(slugs[0]):
            return result

        ticked: list[str] = []
        for s in slugs:
            try:
                inp = page.locator(
                    f".o-articleList__item:has(a[href*='/n/{s}']) input.a-checkbox__field"
                ).first
                inp.wait_for(state="attached", timeout=4_000)
                inp.evaluate("el => el.click()")
                page.wait_for_timeout(200)
                if inp.evaluate("el => el.checked"):
                    ticked.append(s)
                else:
                    logger.warning("[note] membership: %s did not check", s)
            except (PlaywrightTimeoutError, PlaywrightError) as exc:
                logger.warning(
                    "[note] membership: checkbox for %s not found: %s", s, exc,
                )

        if not ticked:
            logger.warning("[note] membership: no target rows ticked -- aborting")
            self._dismiss_membership_modal()
            return result

        # Find the 「追加」 button for the requested plan (match by the
        # plan-card text around each 追加 button).
        add_btn = None
        try:
            btns = page.locator("button", has_text="追加")
            count = btns.count()
            for i in range(count):
                b = btns.nth(i)
                try:
                    ctx = b.evaluate(
                        "el => { let e=el; for(let i=0;i<6 && e && e.parentElement;"
                        " i++){ e=e.parentElement; const t=(e.innerText||'').trim();"
                        " if(t.length>4) return t; } return ''; }"
                    )
                except (PlaywrightTimeoutError, PlaywrightError):
                    ctx = ""
                if plan_name in (ctx or ""):
                    add_btn = b
                    break
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            logger.warning("[note] membership: plan-button scan failed: %s", exc)

        if add_btn is None:
            logger.warning(
                "[note] membership: 「追加」 button for plan %r not found", plan_name,
            )
            self._dismiss_membership_modal()
            return result

        try:
            add_btn.click(timeout=3_000)
            page.wait_for_timeout(2_500)
            for s in ticked:
                result[s] = True
            logger.info(
                "[note] membership: added %d article(s) to %r: %s",
                len(ticked), plan_name, ticked,
            )
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            logger.warning("[note] membership: 「追加」 click failed: %s", exc)
        return result

    def _open_membership_modal(self, slug) -> bool:
        """Enter membership selection mode from /notes via a row's
        「その他」 -> 「メンバーシップ特典追加・解除」. Returns True once the
        per-article checkboxes are present."""
        page = self._page
        if page is None:
            return False
        try:
            if slug:
                link = page.locator(f"a[href*='/n/{slug}']").first
                link.wait_for(state="visible", timeout=8_000)
                card = link.locator(
                    "xpath=ancestor::*[.//button[@aria-label='その他']][1]"
                )
                more = card.locator("button[aria-label='その他']").first
            else:
                more = page.locator("button[aria-label='その他']").first
            more.scroll_into_view_if_needed()
            more.click(timeout=4_000)
            page.wait_for_timeout(800)
            item = page.locator(
                "button.m-basicBalloonList__button:has-text('メンバーシップ特典追加'), "
                "button:has-text('メンバーシップ特典追加')"
            ).first
            item.wait_for(state="visible", timeout=5_000)
            item.click(timeout=3_000)
            # selection mode active once article checkboxes exist
            page.locator(
                ".o-articleList__item input.a-checkbox__field"
            ).first.wait_for(state="attached", timeout=8_000)
            page.wait_for_timeout(800)
            return True
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            logger.warning("[note] membership modal open failed: %s", exc)
            return False

    def _dismiss_membership_modal(self) -> None:
        page = self._page
        if page is None:
            return
        try:
            page.keyboard.press("Escape")
        except PlaywrightError:
            pass

'''


def main() -> int:
    src = T.read_text(encoding="utf-8")
    assert src.count(START) == 1, f"START count={src.count(START)}"
    assert src.count(END) == 1, f"END count={src.count(END)}"
    a = src.index(START)
    b = src.index(END)
    assert a < b
    T.write_text(src[:a] + NEW + src[b:], encoding="utf-8")
    print("OK replaced method block (v3 final)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
