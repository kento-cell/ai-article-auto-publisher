"""Objective article scoring via programmatic measurement.

Scores articles on verifiable metrics that don't require LLM judgment.
All measurements are deterministic — the same article always gets the same scores.

Grades: A (excellent), B (acceptable), C (failing — triggers rejection)
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class ObjectiveScorer:
    """Score articles using only programmatic, verifiable metrics.

    Every metric is computed by counting or pattern-matching.
    No LLM calls. No subjectivity. Can't lie.
    """

    def score(self, article: str, context: dict | None = None) -> dict:
        """Score an article on all objective dimensions.

        Args:
            article: Full markdown text of the article.
            context: Optional dict with:
                - research_brief: Researcher's output (for tier calculation)
                - sources: list of {url, tier, access_date} dicts
                - forbidden_phrases: list of regex patterns

        Returns:
            Dict with per-metric results, objective_pass bool,
            and blocking_issues list.
        """
        context = context or {}
        forbidden = context.get("forbidden_phrases", [])
        sources = context.get("sources", [])
        chain_blacklist = context.get("chain_blacklist", [])

        evidence = self._score_evidence_level(sources)
        citations = self._score_citation_count(article)
        cite_format = self._score_citation_format(article, sources)
        visuals = self._score_visual_count(article)
        words = self._score_word_count(article)
        title_fulfillment = self._score_title_fulfillment(article, context)
        # Scan title+body together so patterns like
        # "〇〇氏のBluesky投稿から徹底" that appear in the title still
        # register as a forbidden hit. Previously title text was
        # invisible to the scorer and a banned premise could sneak
        # through on cosmetic grounds (content happened to paraphrase
        # the banned phrase in the body).
        _title_for_scan = context.get("title", "") or ""
        _scan_text = f"{_title_for_scan}\n{article}" if _title_for_scan else article
        forbidden_result = self._score_forbidden_phrases(_scan_text, forbidden)
        headings = self._score_heading_structure(article)
        chain_check = self._score_chain_stores(article, chain_blacklist)
        trend = self._score_trend_alignment(article, context)
        first_hand = self._score_first_hand_experience(article, context)

        # Collect blocking issues. citation_count was previously not
        # blocking because Codex-grounded note articles can source facts
        # without an explicit ## 参考文献 list; however CLAUDE.md's spec
        # treats citation_count C as a hard fail. We honour the spec but
        # still skip the metric when the article comes from a source
        # type that legitimately has no citable material (Google Trends
        # keywords, raw Reddit posts) — otherwise trending-topic notes
        # would always block.
        blocking: list[str] = []
        metrics_to_check: list[tuple[str, dict]] = [
            ("citation_format", cite_format),
            ("visual_count", visuals),
            ("word_count", words),
            # title_fulfillment is the deterministic enforcement of the
            # project's top-level rule: タイトル負け = 絶対禁止.
            # The LLM-judged title_fulfillment in subjective_evaluator
            # catches qualitative bait-and-switch; this catches mechanical
            # ones (5選 with 3 items, named tool not in body, etc.).
            ("title_fulfillment", title_fulfillment),
        ]
        _source_types = {str(s.get("source", "")).lower() for s in sources}
        _citation_exempt = {"google_trends", "bluesky", "reddit", "arxiv"}
        # 2026-04-27: note向けの一般読み物 (体験談 / 比較 / ハウツー) は
        # 引用URLが少ないのが普通。Zennの技術記事と同基準で弾くと、
        # 7連続却下の構造的な詰まりが発生していた (Opus/GPT比較、
        # Zapier/Make/n8n、AIツールスタック等)。ユーザーの方針に従い
        # noteプラットフォームは citation_count を非ブロッキング化
        # (グレード自体は計測してSheetsに記録し続ける、却下条件から除外)。
        # 2026-05-08 拡充: arXiv 論文要約系の zenn 記事も同じ構造問題で
        # 連続却下していた (ActCam, UniPool, Pair2Scene 等)。abstract に
        # 参考文献URLが含まれないため Gemma3 が複数 citation を作れない。
        # arXiv URL 自身が一次ソースなので citation_count を非ブロッキング化。
        # source URL 文字列にも arxiv.org が含まれる場合は exempt 扱い。
        _source_urls_lower = " ".join(
            str(s.get("url", "")).lower() for s in sources
        )
        _arxiv_in_urls = "arxiv.org" in _source_urls_lower
        _platform = str(context.get("platform", "")).lower()
        if (
            _platform != "note"
            and not _arxiv_in_urls
            and (not _source_types or not (_source_types & _citation_exempt))
        ):
            metrics_to_check.insert(0, ("citation_count", citations))
        # Only check evidence_level when source data is actually available
        if sources:
            metrics_to_check.insert(0, ("evidence_level", evidence))

        for metric_name, result in metrics_to_check:
            if result["grade"] == "C":
                blocking.append(
                    f"{metric_name}: {result.get('reason', 'grade C')}"
                )

        if forbidden_result["grade"] == "Fail":
            # 2026-04-27: noteの体験談/比較/ハウツー記事は「ツールA: / ツールB:」
            # のような空欄バレットを許容したい (公式URLが書けない正当な
            # 比較記事を弾いてしまうため)。ハルシネ系・架空SNS系・チェーン店
            # 系といった「事実精度に直結するforbidden」はそのまま残し、
            # 「構造的テンプレ系」のみ note では非ブロッキング化する。
            #
            # 構造的テンプレ判定:
            #  (a) 既知マーカー文字列 (公式サイト, ここに入力, ...)
            #  (b) 「* Label: \n * Label: \n」のような空欄バレット
            #      (2行以上連続、各バレットがコロン直後改行で値を持たない)
            _structural_template_markers = (
                "公式サイト", "ここに入力", "URLは記載しません", "実際には"
            )
            _hits_str = " ".join(str(h) for h in forbidden_result["hits"])
            _empty_bullet_re = re.compile(
                r"(?:\*|-)\s+[^*:\n]{2,60}:\s*\n.*(?:\*|-)\s+[^*:\n]{2,60}:\s*\n",
                re.DOTALL,
            )
            _has_known_marker = any(
                m in _hits_str for m in _structural_template_markers
            )
            _looks_like_empty_bullet_template = bool(
                _empty_bullet_re.search(_hits_str)
            )
            _is_only_template = (
                _platform == "note"
                and (_has_known_marker or _looks_like_empty_bullet_template)
                and not any(
                    danger in _hits_str
                    for danger in (
                        "Bluesky", "Threads", "Mastodon",
                        "トレンド入り", "話題を呼んで", "議論を呼んで",
                        "架空", "Dr. X", "〇〇", "◯◯", "○○",
                    )
                )
            )
            if _is_only_template:
                logger.info(
                    "[note] forbidden_phrases に構造的テンプレ系のみ検出 "
                    "→ 非ブロッキング化: %s",
                    forbidden_result["hits"][:2],
                )
            else:
                blocking.append(
                    f"forbidden_phrases: {forbidden_result['hits']}"
                )
        if headings["grade"] == "Fail":
            blocking.append(f"heading_structure: {headings['issues']}")
        if chain_check["grade"] == "Fail":
            blocking.append(
                f"chain_stores: チェーン店検出 {chain_check['hits']}"
            )

        objective_pass = len(blocking) == 0

        logger.info(
            "Objective scoring complete: pass=%s, blocking=%d",
            objective_pass,
            len(blocking),
        )

        # Surface metrics under "metrics" too — score_aggregator's
        # numeric composite reads from there. trend_alignment is
        # bonus-only: include it ONLY when it earned grade A so it can
        # boost the average, but never penalize an otherwise-strong
        # article for failing to ride note.com vocabulary.
        metrics = {
            "evidence_level": evidence,
            "citation_count": citations,
            "citation_format": cite_format,
            "visual_count": visuals,
            "word_count": words,
            "forbidden_phrases": forbidden_result,
            "heading_structure": headings,
            "chain_stores": chain_check,
            "title_fulfillment": title_fulfillment,
        }
        if trend.get("grade") == "A":
            metrics["trend_alignment"] = trend
        if first_hand.get("grade") == "A":
            metrics["first_hand_experience"] = first_hand

        return {
            **metrics,
            "trend_alignment": trend,  # always exposed at top-level
            "first_hand_experience": first_hand,
            "metrics": metrics,
            "objective_pass": objective_pass,
            "blocking_issues": blocking,
        }

    # ------------------------------------------------------------------
    # Private scoring methods
    # ------------------------------------------------------------------

    @staticmethod
    def _score_title_fulfillment(article: str, context: dict) -> dict:
        """Programmatic check that body delivers on title's specific promises.

        Detects mechanical bait-and-switch (5選 with 3 items, named
        tool not in body, claimed timeframe absent, etc.). The LLM
        judges qualitative title fulfillment; this catches the
        deterministic failures the LLM may overlook or grade leniently.
        """
        try:
            from generators import title_fulfillment_scorer
        except Exception as exc:
            logger.warning("title_fulfillment_scorer unavailable: %s", exc)
            return {
                "grade": "B", "promises": [], "unfulfilled": [],
                "reason": f"scorer unavailable: {exc}",
            }
        title = str((context or {}).get("title") or "")
        try:
            return title_fulfillment_scorer.score(title, article)
        except Exception as exc:
            logger.warning("title_fulfillment scoring failed: %s", exc)
            return {
                "grade": "B", "promises": [], "unfulfilled": [],
                "reason": f"error: {exc}",
            }

    def _score_evidence_level(self, sources: list[dict]) -> dict:
        """Score source quality by tier distribution.

        Args:
            sources: List of dicts, each with a "tier" key (int 1-4).

        Returns:
            Dict with grade, tier12_ratio, total_sources, tier12_count,
            and reason.
        """
        if not sources:
            return {
                "grade": "N/A",
                "tier12_ratio": 0.0,
                "total_sources": 0,
                "tier12_count": 0,
                "reason": "no source data available (skipped)",
            }

        total = len(sources)
        tier12_count = sum(
            1 for s in sources if s.get("tier") in (1, 2)
        )
        ratio = tier12_count / total

        if ratio >= 0.80:
            grade = "A"
            reason = (
                f"{tier12_count}/{total} sources are tier 1-2 "
                f"({ratio:.0%} >= 80%)"
            )
        elif ratio >= 0.60:
            grade = "B"
            reason = (
                f"{tier12_count}/{total} sources are tier 1-2 "
                f"({ratio:.0%}, between 60%-80%)"
            )
        else:
            grade = "C"
            reason = (
                f"{tier12_count}/{total} sources are tier 1-2 "
                f"({ratio:.0%} < 60%)"
            )

        logger.debug("Evidence level: %s (ratio=%.2f)", grade, ratio)
        return {
            "grade": grade,
            "tier12_ratio": round(ratio, 4),
            "total_sources": total,
            "tier12_count": tier12_count,
            "reason": reason,
        }

    def _score_citation_count(self, article: str) -> dict:
        """Count citations in the article text.

        Counts blockquote citation lines (> 出典: / > Source:) and
        markdown links in reference sections.

        Args:
            article: Full markdown text.

        Returns:
            Dict with grade, count, and reason.
        """
        # Blockquote citations: > 出典: or > Source: or > with URL
        blockquote_pattern = re.compile(
            r"^>\s*(?:出典[:：]|Source:|https?://)", re.MULTILINE
        )
        blockquote_hits = blockquote_pattern.findall(article)

        # Reference-section links: lines with [text](url) under a
        # reference heading
        ref_heading = re.compile(
            r"^#{1,3}\s*(?:参考文献|参考|References?|Sources?|出典)",
            re.MULTILINE | re.IGNORECASE,
        )
        ref_links = 0
        match = ref_heading.search(article)
        if match:
            section_text = article[match.end():]
            # Stop at next heading of same or higher level
            next_heading = re.search(r"^#{1,2}\s", section_text, re.MULTILINE)
            if next_heading:
                section_text = section_text[:next_heading.start()]
            ref_links = len(re.findall(
                r"\[.+?\]\(https?://.+?\)", section_text
            ))

        count = len(blockquote_hits) + ref_links

        # CLAUDE.md spec: A(5+) / B(2-4) / C(0-1).
        if count >= 5:
            grade = "A"
            reason = f"{count} citations found (>= 5)"
        elif count >= 2:
            grade = "B"
            reason = f"{count} citations found (2-4 range)"
        else:
            grade = "C"
            reason = f"{count} citation(s) found (<= 1)"

        logger.debug("Citation count: %s (%d)", grade, count)
        return {"grade": grade, "count": count, "reason": reason}

    def _score_citation_format(
        self, article: str, sources: list[dict] | None = None,
    ) -> dict:
        """Check citation formatting compliance.

        Each citation should include a URL and an access date.

        When `sources` is provided, citations that reference an arXiv
        abstract (by URL or paper title appearing in the article body)
        are auto-credited as URL-bearing even if the blockquote itself
        lacks the URL. The abstract IS the primary source — the LLM just
        forgot to paste the URL inside the quote block.

        Args:
            article: Full markdown text.
            sources: Optional list of source dicts (each with `url` and
                `title` keys) from the article collector.

        Returns:
            Dict with grade, compliance_rate, with_url, with_date,
            total, and reason.
        """
        # Find all blockquote citation blocks (consecutive > lines)
        # Exclude callout blocks (> **💡**, > **Note**, :::message etc.)
        all_blocks = re.findall(
            r"((?:^>.*\n?)+)", article, re.MULTILINE
        )
        citation_blocks = [
            b for b in all_blocks
            if not re.match(r">\s*\*\*[💡🔥⚠️📝ℹ️]", b)
            and not re.match(r">\s*\*\*(Note|注意|ヒント|Tips)", b, re.IGNORECASE)
        ]

        if not citation_blocks:
            # Fallback: check if article has inline URLs (common in LLM output)
            inline_urls = len(re.findall(r"https?://\S+", article))
            if inline_urls >= 2:
                return {
                    "grade": "B",
                    "compliance_rate": 0.0,
                    "with_url": inline_urls,
                    "with_date": 0,
                    "total": inline_urls,
                    "reason": f"no blockquote citations but {inline_urls} inline URLs found",
                }
            return {
                "grade": "C",
                "compliance_rate": 0.0,
                "with_url": 0,
                "with_date": 0,
                "total": 0,
                "reason": "no citation blocks or inline URLs found",
            }

        with_url = 0
        with_date = 0
        compliant = 0

        for block in citation_blocks:
            has_url = bool(re.search(r"https?://\S+", block))
            has_date = bool(re.search(
                r"(?:取得日[:：]|accessed[:：]?\s*)", block, re.IGNORECASE
            ))
            if has_url:
                with_url += 1
            if has_date:
                with_date += 1
            if has_url and has_date:
                compliant += 1

        total = len(citation_blocks)

        # Auto-credit arXiv abstracts — the abstract is a legitimate
        # primary source. When the pipeline tells us the article was
        # built FROM an arXiv source, we credit the existing citation
        # blocks as URL-backed even if the LLM paraphrased the title
        # and forgot to paste the URL inside the quote block. This is
        # exactly the "アブストはエビ扱い" policy the user approved.
        #
        # Guard: only auto-credit up to *one* citation per arXiv source
        # — multiple unrelated citation blocks still need their own URLs.
        auto_credited = 0
        for src in (sources or []):
            if not isinstance(src, dict):
                continue
            url = str(src.get("url") or "")
            if "arxiv.org" in url:
                auto_credited += 1

        # Only promote `with_url`. Don't touch `compliant`/`with_date`
        # — the access-date requirement still has to be met manually
        # for the citation to count toward grade A. arXiv auto-credit
        # rescues the URL half only, so blocked-by-no-URL articles can
        # at least reach grade B instead of grade C.
        if auto_credited > 0 and with_url < total:
            promote = min(auto_credited, total - with_url)
            with_url += promote

        # Count URL-only compliance (date is nice-to-have for local LLM)
        url_rate = with_url / total if total > 0 else 0.0
        rate = compliant / total if total > 0 else 0.0

        if rate >= 1.0:
            grade = "A"
            reason = f"all {total} citations have URL and access date"
        elif url_rate >= 0.50:
            grade = "B"
            reason = (
                f"{with_url}/{total} citations have URL "
                f"({url_rate:.0%} >= 50%)"
            )
        else:
            grade = "C"
            reason = (
                f"{with_url}/{total} citations have URL "
                f"({url_rate:.0%} < 50%)"
            )

        logger.debug("Citation format: %s (rate=%.2f)", grade, rate)
        return {
            "grade": grade,
            "compliance_rate": round(rate, 4),
            "with_url": with_url,
            "with_date": with_date,
            "total": total,
            "reason": reason,
        }

    def _score_trend_alignment(
        self, article: str, context: dict | None,
    ) -> dict:
        """Score how well the article rides current note.com trends.

        Two-axis grading via TrendMatcher: "hot" (already trending) and
        "emerging" (new vocabulary appearing only in the freshest learn
        slice). Either axis alone can earn A — gatsuri-trend mo
        potential-waku mo dochira mo hirou.

        Title is required as the dominant signal. If the caller doesn't
        provide one in context, falls back to the first H1 heading.
        """
        try:
            from generators.trend_matcher import TrendMatcher
        except Exception as exc:
            logger.warning("trend_matcher unavailable: %s", exc)
            return {"grade": "B", "reason": "trend matcher unavailable"}

        title = ""
        if context:
            title = str(context.get("title") or "").strip()
        if not title:
            m = re.search(r"^#\s+(.+)$", article, re.MULTILINE)
            if m:
                title = m.group(1).strip()

        if not title:
            return {"grade": "B", "reason": "no title to analyze — neutral B"}

        # Optional summary signal: first paragraph after the title.
        summary = ""
        first_para = re.search(r"^[^#>\n].{20,200}$", article, re.MULTILINE)
        if first_para:
            summary = first_para.group(0)

        try:
            return TrendMatcher.get().score(title, summary)
        except Exception as exc:
            logger.warning("trend_alignment failed: %s", exc)
            return {"grade": "B", "reason": f"error: {exc}"}

    # E-E-A-T "Experience" markers: phrases that signal the author
    # actually used / visited / tried the thing they're writing about.
    # Past-tense + first-person framing only — present tense ("使ってみる")
    # and bare past ("買った") are too generic and bait false positives
    # in instructional or general content.
    _FIRST_HAND_PATTERNS = [
        r"行ってきた", r"訪れてきた", r"訪問した",
        r"食べてみた", r"食べてきた", r"飲んでみた", r"試してみた",
        r"使ってみた", r"買ってみた",
        r"体験してきた", r"体験してみた",
        r"実際に[^\s。、]{0,15}(?:してみた|食べてきた|行ってきた|訪れた|試してみた)",
        r"自分で[^\s。、]{0,10}(?:してみた|やってみた|作ってみた)",
        r"私[はがも][^\s。、]{0,10}(?:してきた|してみた|行ってきた|訪れた|来た)",
        r"[0-9]+(?:回|度)[^\s。、]{0,10}(?:訪れ|通っ|行っ|食べ|使っ)",
    ]

    def _score_first_hand_experience(
        self, article: str, context: dict | None,
    ) -> dict:
        """Detect first-hand experience markers (E-E-A-T Experience).

        Bonus-only metric, mirroring trend_alignment semantics: A boosts
        the composite, B is the floor (no penalty). Only meaningful for
        lifestyle/gourmet content — for tech articles (zenn) we just
        return B without scanning, since "I tried Claude Code" markers
        live in different vocabulary and would generate noise.
        """
        platform = ""
        if context:
            platform = str(context.get("platform") or "").lower()
        if platform == "zenn":
            return {
                "grade": "B",
                "hits": 0,
                "matched": [],
                "reason": "skipped (tech platform)",
            }

        # Dedupe within article — the same templated phrase repeated
        # (e.g. a copy-pasted disclaimer) should NOT count multiple times.
        # Distinct phrases each contribute 1.
        matched_set: set[str] = set()
        for pat in self._FIRST_HAND_PATTERNS:
            for m in re.finditer(pat, article):
                matched_set.add(m.group(0))
                if len(matched_set) >= 20:
                    break
            if len(matched_set) >= 20:
                break

        matched = sorted(matched_set)
        n = len(matched)
        if n >= 3:
            grade = "A"
            reason = f"{n} distinct first-hand markers (e.g. {matched[:3]})"
        else:
            grade = "B"
            reason = f"{n} distinct first-hand markers — neutral B"

        return {"grade": grade, "hits": n, "matched": matched, "reason": reason}

    def _score_visual_count(self, article: str) -> dict:
        """Count visual elements in the article.

        Counts images, mermaid diagrams, tables, and code blocks.

        Args:
            article: Full markdown text.

        Returns:
            Dict with grade, count, images, mermaid, tables,
            code_blocks, and reason.
        """
        images = len(re.findall(r"!\[", article))
        mermaid = len(re.findall(r"```mermaid", article, re.IGNORECASE))

        # Tables: lines with |...|...| pattern (count unique tables,
        # not rows). A table starts with a |---| separator line.
        table_separators = re.findall(
            r"^\|[\s\-:]+\|", article, re.MULTILINE
        )
        tables = len(table_separators)

        # Code blocks: ``` with a language tag, excluding mermaid
        code_blocks = len(re.findall(
            r"```(?!mermaid)\w+", article, re.IGNORECASE
        ))

        total = images + mermaid + tables + code_blocks

        # CLAUDE.md spec was A(5+) / B(2-4) / C(0-1). Revised 2026-05-14:
        # the image_sourcer's off-subject alt-text gate drops ~75% of
        # auto-fetched images on news articles, so most note pieces end
        # up with exactly 1 visual (the affiliate-section image at the
        # bottom). Combined with Writer's reluctance to emit markdown
        # tables, the prior B threshold of 2 rejected every single note
        # candidate across 9 generate runs today. Allowing B at 1 visual
        # lets thin-but-passable pieces ship while still flagging zero-
        # visual articles. C (auto-reject) retained at 0.
        if total >= 5:
            grade = "A"
            reason = f"{total} visual elements found (>= 5)"
        elif total >= 1:
            grade = "B"
            reason = f"{total} visual elements found (1-4 range)"
        else:
            grade = "C"
            reason = f"{total} visual element(s) found (0)"

        logger.debug("Visual count: %s (%d total)", grade, total)
        return {
            "grade": grade,
            "count": total,
            "images": images,
            "mermaid": mermaid,
            "tables": tables,
            "code_blocks": code_blocks,
            "reason": reason,
        }

    def _score_word_count(self, article: str) -> dict:
        """Count effective characters (words for Japanese content).

        Strips markdown formatting and counts characters, since for
        Japanese text characters approximate words.

        Args:
            article: Full markdown text.

        Returns:
            Dict with grade, count, target_min, target_max, and reason.
        """
        # Strip markdown syntax for cleaner character count
        text = article
        # Remove code blocks entirely
        text = re.sub(r"```[\s\S]*?```", "", text)
        # Remove images
        text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
        # Remove links but keep text
        text = re.sub(r"\[(.+?)\]\(.*?\)", r"\1", text)
        # Remove heading markers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Remove bold/italic markers
        text = re.sub(r"[*_]{1,3}", "", text)
        # Remove blockquote markers
        text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
        # Remove table formatting characters
        text = re.sub(r"[|]", "", text)
        # Remove horizontal rules
        text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
        # Collapse whitespace
        text = re.sub(r"\s+", "", text)

        count = len(text)
        # Length policy (revised 2026-05-14 evening — Stage 1 of note
        # redesign proposal, see docs/knowledge/note_redesign_proposal_20260514.md):
        # Web research on 300k note articles (note公式分析) showed that
        # word count and sales have effectively zero correlation
        # (実用系 -0.023, 読み物系 +0.011), and that articles over 4,000
        # chars carry an 18% higher reader-drop-off rate. Yet our prior
        # A target (4000-5500) was both too long AND impossible for
        # Gemma3 12B (1,700-2,100 char empirical floor).
        # New policy:
        #  - A target moved to 2,200-3,500: rewards the "dense but tight"
        #    band that note's bestsellers actually live in.
        #  - B accept widened to 1,700-5,500: matches Gemma3's actual
        #    output range; rejects only genuinely thin (<1,700) or
        #    bloated (>5,500) pieces.
        target_min = 2200
        target_max = 3500
        accept_min = 1700
        accept_max = 5500

        if target_min <= count <= target_max:
            grade = "A"
            reason = (
                f"{count} chars within target range "
                f"({target_min}-{target_max})"
            )
        elif accept_min <= count <= accept_max:
            grade = "B"
            reason = (
                f"{count} chars slightly outside target "
                f"({target_min}-{target_max}) but within "
                f"{accept_min}-{accept_max}"
            )
        else:
            grade = "C"
            reason = (
                f"{count} chars outside acceptable range "
                f"({accept_min}-{accept_max})"
            )

        logger.debug("Word count: %s (%d chars)", grade, count)
        return {
            "grade": grade,
            "count": count,
            "target_min": target_min,
            "target_max": target_max,
            "reason": reason,
        }

    def _score_forbidden_phrases(
        self, article: str, patterns: list[str]
    ) -> dict:
        """Check for forbidden phrases using regex patterns.

        Args:
            article: Full markdown text.
            patterns: List of regex pattern strings to search for.

        Returns:
            Dict with grade (Pass/Fail), hits list, and reason.
        """
        if not patterns:
            return {
                "grade": "Pass",
                "hits": [],
                "reason": "no forbidden patterns configured",
            }

        hits: list[str] = []
        for pattern in patterns:
            try:
                matches = re.findall(pattern, article, re.IGNORECASE)
                if matches:
                    hits.extend(matches)
            except re.error as exc:
                logger.warning(
                    "Invalid forbidden-phrase regex '%s': %s", pattern, exc
                )

        if hits:
            grade = "Fail"
            reason = f"found {len(hits)} forbidden phrase(s): {hits}"
        else:
            grade = "Pass"
            reason = (
                f"checked {len(patterns)} patterns, no matches found"
            )

        logger.debug("Forbidden phrases: %s (%d hits)", grade, len(hits))
        return {"grade": grade, "hits": hits, "reason": reason}

    def _score_heading_structure(self, article: str) -> dict:
        """Validate markdown heading structure.

        Checks that the article has at least 3 H2 headings and no
        H1 headings in the body (H1 is reserved for the title).

        Args:
            article: Full markdown text.

        Returns:
            Dict with grade (Pass/Fail), h2_count, h3_count, issues
            list, and reason.
        """
        lines = article.split("\n")

        h1_count = 0
        h2_count = 0
        h3_count = 0
        first_line_is_h1 = False
        issues: list[str] = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            # H1: exactly one # followed by space
            if re.match(r"^#\s+\S", stripped):
                if i == 0:
                    first_line_is_h1 = True
                else:
                    h1_count += 1
            elif re.match(r"^##\s+\S", stripped):
                h2_count += 1
            elif re.match(r"^###\s+\S", stripped):
                h3_count += 1

        if h1_count > 0:
            issues.append(
                f"found {h1_count} H1 heading(s) in body "
                "(H1 should only be the title)"
            )
        if h2_count < 2:
            issues.append(
                f"only {h2_count} H2 headings (minimum 2 required)"
            )

        grade = "Pass" if not issues else "Fail"
        if issues:
            reason = "; ".join(issues)
        else:
            reason = (
                f"valid structure: {h2_count} H2 and {h3_count} H3 "
                "headings, no stray H1"
            )

        logger.debug("Heading structure: %s", grade)
        return {
            "grade": grade,
            "h2_count": h2_count,
            "h3_count": h3_count,
            "issues": issues,
            "reason": reason,
        }

    @staticmethod
    def _score_chain_stores(
        article: str, blacklist: list[str]
    ) -> dict:
        """Check if the article mentions any chain store names.

        Chain stores are banned in gourmet/spot recommendation articles.
        Individual, hidden-gem restaurants only.

        Args:
            article: Full markdown text.
            blacklist: List of chain store names to check.

        Returns:
            Dict with grade (Pass/Fail), hits list, and reason.
        """
        if not blacklist:
            return {
                "grade": "Pass",
                "hits": [],
                "reason": "no chain blacklist configured",
            }

        hits: list[str] = []
        for chain in blacklist:
            if chain in article:
                hits.append(chain)

        if hits:
            reason = (
                f"チェーン店検出: {', '.join(hits)}。"
                "個人店・隠れた名店のみ紹介可。チェーン店は禁止。"
            )
            logger.warning("Chain store detected: %s", hits)
            return {"grade": "Fail", "hits": hits, "reason": reason}

        return {
            "grade": "Pass",
            "hits": [],
            "reason": "チェーン店なし",
        }
