"""Gmail notification sender — DISABLED.

Gmail notifications were removed on 2026-04-18. The service-account path
kept hitting ``unauthorized_client`` because the sender address never had
Domain-Wide Delegation attached, and rotating credentials for a
best-effort email channel was not worth the maintenance cost. Slack
already carries the same events (see ``publishers/slack_notifier.py``).

The ``GmailNotifier`` class is kept as a no-op so existing callers
(``main.py``, ``bot/slack_bot.py``) do not need to be refactored, and so
that adding Gmail back later is a single-file change.

Anything email-shaped should be sent via Slack for now. If Gmail is
re-enabled, restore the previous implementation from git history
(pre-2026-04-18 ``publishers/gmail_notifier.py``) and grant
Domain-Wide Delegation to the service account for
``https://www.googleapis.com/auth/gmail.send``.
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger


class GmailNotifier:
    """No-op replacement for the removed Gmail notifier.

    Every method logs a single DEBUG line and returns ``False`` so
    callers can keep their ``if sent: ...`` branches without triggering
    a real network call or credential lookup.
    """

    def __init__(
        self,
        credentials_path: str | None = None,  # kept for signature compat
        sender_email: str | None = None,
        recipient_email: str | None = None,
    ) -> None:
        self._logger = get_logger("gmail_notifier")
        self._logger.debug(
            "GmailNotifier is a no-op (Gmail notifications disabled "
            "2026-04-18)",
        )

    # ------------------------------------------------------------------
    # Public API — all return False so callers fall through cleanly.
    # ------------------------------------------------------------------

    def notify_pending_approval(
        self, articles: list[dict[str, Any]], sheets_url: str = "",
    ) -> bool:
        return False

    def notify_published(
        self, platform: str, title: str, url: str,
    ) -> bool:
        """Signature matches the caller in ``main.py`` / ``slack_bot.py``
        (platform, title, url) — the earlier stub used
        ``notify_publish_success`` with swapped args and caused publish
        failures after Zenn push on 2026-04-18."""
        return False

    def notify_error(self, error: str, context: str) -> bool:
        return False

    def notify_daily_summary(self, stats: dict[str, Any]) -> bool:
        return False
