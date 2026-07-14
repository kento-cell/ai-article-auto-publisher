"""URL sanitisation and shortening for LLM-generated article content.

Local LLMs (Gemma3 etc.) hallucinate external URLs with alarming
confidence and often emit them as ugly `[https://very-long-url](https://very-long-url)`
blobs. This module is the post-processing pass that runs after
generation and before scoring, with three responsibilities:

1. **Whitelist enforcement** — any bare URL inside the article body
   that points to a domain outside the allow-list is stripped. The
   reasoning: we can only be confident in URLs we ourselves supplied
   (source post URL, Google Maps query URL, domains Places API
   returned). Everything else is assumed hallucinated.

2. **Markdown anchor shortening** — `[https://...](https://...)` and
   similar duplicated-label anchors get a short, meaningful label
   based on their host so the reader sees ``[Googleマップ](...)`` or
   ``[食べログ](...)`` instead of a 300-character URL.

3. **Reference section preservation** — the ``## 参考文献`` section is
   scanned leniently: we shorten labels but do not strip URLs there,
   so citations stay intact even for domains outside the allow-list.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Domains whose URLs are trusted enough to remain in the prose body.
# Anything else gets stripped from prose (but preserved in 参考文献).
_BODY_ALLOW_HOSTS: set[str] = {
    "bsky.app",
    "www.google.com",
    "google.com",
    "maps.google.com",
    "goo.gl",
    "maps.app.goo.gl",
}

# Map host → short label used when we rewrite a duplicated anchor.
_HOST_LABELS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(^|\.)google\.com$"), "Googleマップ"),
    (re.compile(r"(^|\.)goo\.gl$"), "Googleマップ"),
    (re.compile(r"(^|\.)maps\.app\.goo\.gl$"), "Googleマップ"),
    (re.compile(r"(^|\.)bsky\.app$"), "Blueskyの投稿"),
    (re.compile(r"(^|\.)tabelog\.com$"), "食べログ"),
    (re.compile(r"(^|\.)retty\.me$"), "Retty"),
    (re.compile(r"(^|\.)hotpepper\.jp$"), "ホットペッパー"),
    (re.compile(r"(^|\.)gnavi\.co\.jp$"), "ぐるなび"),
    (re.compile(r"(^|\.)instagram\.com$"), "Instagram"),
    (re.compile(r"(^|\.)twitter\.com$"), "X（Twitter）"),
    (re.compile(r"(^|\.)x\.com$"), "X（Twitter）"),
    (re.compile(r"(^|\.)note\.com$"), "note"),
    (re.compile(r"(^|\.)github\.com$"), "GitHub"),
    (re.compile(r"(^|\.)arxiv\.org$"), "arXiv"),
    (re.compile(r"(^|\.)huggingface\.co$"), "Hugging Face"),
]

# Regex for markdown inline links: [label](url)
_MARKDOWN_LINK_RE = re.compile(
    r"\[(?P<label>[^\]]+)\]\((?P<url>https?://[^)\s]+)\)"
)

# Bare URLs not wrapped in markdown.
# Incident #25 (2026-07-14): the old class [^\s\)\]] treated full-width
# CJK punctuation (）。、」etc.) as part of the URL, so stripping a
# non-allowlisted URL also swallowed the closing full-width paren AND
# the rest of the sentence (「…（出典: X — https://…）。続き」→
# 「…（出典: X — 」). URLs are ASCII — stop at any non-ASCII char.
_BARE_URL_RE = re.compile(r"(?<!\]\()(?<!\()https?://[^\s\)\]-￿]+")

# Heading that marks the start of the references section.
_REF_HEADING_RE = re.compile(r"(?m)^##+\s*参考(文献|リンク)")


def _host_label(url: str) -> str:
    """Return a short human-readable label for *url*'s host."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return "リンク"
    for pat, label in _HOST_LABELS:
        if pat.search(host):
            return label
    # Fall back to the registered domain (last two labels).
    if host:
        parts = host.split(".")
        if len(parts) >= 2:
            return parts[-2]
    return "リンク"


def _is_allowed_in_body(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _BODY_ALLOW_HOSTS


def _shorten_markdown_links(text: str, enforce_allowlist: bool) -> str:
    """Replace duplicated-label anchors with a clean host label.

    Patterns touched:
      - ``[https://...](https://...)`` (label == url)
      - ``[URL](https://...)`` style ASCII-only label
      - Labels that are just the bare host/path of the URL

    When *enforce_allowlist* is True, any markdown link pointing to a
    host outside :data:`_BODY_ALLOW_HOSTS` is dropped entirely (the
    whole ``[label](url)`` is replaced with just ``label``), so
    hallucinated links to fabricated shops disappear.
    """

    def _replace(match: re.Match[str]) -> str:
        label = match.group("label").strip()
        url = match.group("url").strip()
        if enforce_allowlist and not _is_allowed_in_body(url):
            # Keep the human-readable label, drop the fake URL so we
            # do not send readers to a nonexistent page.
            if re.fullmatch(r"https?://\S+", label) or label == url:
                return ""  # label was just the URL → drop entirely
            return label
        # If the label is itself a URL or only ASCII punctuation/URL fragment,
        # replace it with a host label.
        if re.fullmatch(r"https?://\S+", label) or label == url:
            return f"[{_host_label(url)}]({url})"
        # Excessively long labels (>60 chars) with mostly ASCII content are
        # usually just the URL pasted — shorten.
        if len(label) > 60 and sum(
            ch.isascii() for ch in label
        ) > 0.7 * len(label):
            return f"[{_host_label(url)}]({url})"
        return match.group(0)

    return _MARKDOWN_LINK_RE.sub(_replace, text)


def _strip_unwhitelisted_bare_urls(body: str) -> str:
    """Remove bare URLs from *body* unless host is in the allow-list."""

    def _replace(match: re.Match[str]) -> str:
        url = match.group(0)
        return url if _is_allowed_in_body(url) else ""

    return _BARE_URL_RE.sub(_replace, body)


# Incident #25 (2026-07-14): stripping a non-allowlisted bare URL out of
# an inline citation eats the URL *and* the trailing full-width paren
# (the bare-URL regex is \S-greedy), leaving 「（出典: ROOMIE — 」
# dangling mid-sentence — observed 9-10 times per article across all 4
# published notes. Repair pass: close the citation cleanly with just
# the media name.
# The media-name group excludes ``/`` so a HEALTHY citation that still
# carries its URL (e.g. an allowlisted 「（出典: X — https://…）」) can
# never be matched/rewritten — the slash forces a non-match.
_DANGLING_CITE_RE = re.compile(
    r"（\s*(?:出典|Source)\s*[:：]\s*([^\n（）/]{1,30}?)\s*[—ー–-]?\s*(?:）|(?=\n)|$)",
    re.MULTILINE | re.IGNORECASE,
)


def _repair_dangling_citations(body: str) -> str:
    def _fix(m: re.Match[str]) -> str:
        name = m.group(1).strip().rstrip("—ー–- ")
        if not name:
            return ""  # nothing left worth keeping
        return f"（出典: {name}）"

    return _DANGLING_CITE_RE.sub(_fix, body)


def clean_article_urls(content: str) -> str:
    """Shorten inline links and strip hallucinated bare URLs.

    Body vs. references are processed separately so citation URLs in
    ``## 参考文献`` survive even if their host isn't whitelisted.
    """
    if not content:
        return content

    match = _REF_HEADING_RE.search(content)
    if match:
        body, refs = content[: match.start()], content[match.start():]
    else:
        body, refs = content, ""

    body = _shorten_markdown_links(body, enforce_allowlist=True)
    body = _strip_unwhitelisted_bare_urls(body)
    body = _repair_dangling_citations(body)
    if refs:
        refs = _shorten_markdown_links(refs, enforce_allowlist=False)
    return body + refs
