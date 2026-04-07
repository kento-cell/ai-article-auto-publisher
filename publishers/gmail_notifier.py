"""Gmail notification sender for article publishing events.

Uses Gmail API via service account (same credentials as Google Sheets).
Sends notifications for: pending approval, publish success, errors,
and daily summary.
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from utils.logger import get_logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENV_CREDENTIALS = "GOOGLE_SHEETS_CREDENTIALS_PATH"
_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


class GmailNotifier:
    """Send email notifications via Gmail API.

    Uses a service account with domain-wide delegation, or falls back to
    user OAuth credentials.

    If not configured, all methods silently skip (graceful degradation).

    Args:
        credentials_path: Path to service account JSON.  Falls back to
            ``GOOGLE_SHEETS_CREDENTIALS_PATH`` env var (shared creds).
        sender_email: Gmail address to send from.  Falls back to
            ``GMAIL_SENDER`` env var.
        recipient_email: Email to send to.  Falls back to
            ``GMAIL_RECIPIENT`` env var.
    """

    def __init__(
        self,
        credentials_path: str | None = None,
        sender_email: str | None = None,
        recipient_email: str | None = None,
    ) -> None:
        self._logger: logging.Logger = get_logger("gmail_notifier")
        self._credentials_path: str | None = (
            credentials_path or os.getenv(_ENV_CREDENTIALS)
        )
        self._sender: str | None = (
            sender_email or os.getenv("GMAIL_SENDER")
        )
        self._recipient: str | None = (
            recipient_email or os.getenv("GMAIL_RECIPIENT")
        )
        self._service: Any | None = self._authorize()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _authorize(self) -> Any | None:
        """Build Gmail API service from credentials.

        Returns ``None`` when configuration is incomplete so that
        notification methods degrade gracefully.
        """
        if not self._sender or not self._recipient:
            self._logger.warning(
                "GMAIL_SENDER or GMAIL_RECIPIENT not set; "
                "Gmail notifications disabled",
            )
            return None
        if not self._credentials_path:
            self._logger.warning(
                "%s not set; Gmail notifications disabled",
                _ENV_CREDENTIALS,
            )
            return None
        if not os.path.isfile(self._credentials_path):
            self._logger.warning(
                "Credentials file not found: %s; Gmail disabled",
                self._credentials_path,
            )
            return None
        try:
            credentials = Credentials.from_service_account_file(
                self._credentials_path, scopes=_SCOPES,
            )
            delegated = credentials.with_subject(self._sender)
            service = build("gmail", "v1", credentials=delegated)
            self._logger.info("Gmail API service initialized")
            return service
        except Exception as exc:
            self._logger.warning("Gmail auth failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Public notification methods
    # ------------------------------------------------------------------

    def notify_pending_approval(
        self,
        articles: list[dict[str, Any]],
        sheets_url: str,
    ) -> bool:
        """Send email when articles are ready for review.

        Args:
            articles: List of article dicts (keys: title, overall_grade,
                evidence_level, tier12_ratio).
            sheets_url: URL to the Google Sheets review page.

        Returns:
            ``True`` if sent, ``False`` if skipped or failed.
        """
        count = len(articles)
        subject = f"[ai-publisher] {count}\u4ef6\u306e\u8a18\u4e8b\u304c\u627f\u8a8d\u5f85\u3061\u3067\u3059"
        rows_html = self._build_article_table_rows(articles)
        html = (
            "<h2>\u627f\u8a8d\u5f85\u3061\u306e\u8a18\u4e8b</h2>"
            "<table border='1' cellpadding='6' cellspacing='0'>"
            "<tr><th>\u30bf\u30a4\u30c8\u30eb</th>"
            "<th>\u7dcf\u5408</th>"
            "<th>\u8a3c\u62e0Lv</th></tr>"
            f"{rows_html}"
            "</table>"
            f"<p><a href='{sheets_url}'>Google Sheets\u3067\u78ba\u8a8d</a></p>"
        )
        return self._send(subject, html)

    def notify_published(
        self,
        platform: str,
        title: str,
        url: str,
    ) -> bool:
        """Send email confirming an article was published.

        Args:
            platform: Publishing platform (e.g. ``"zenn"``).
            title: Article title.
            url: Published article URL.

        Returns:
            ``True`` if sent, ``False`` if skipped or failed.
        """
        subject = f"[ai-publisher] \u6295\u7a3f\u5b8c\u4e86: {title}"
        html = (
            f"<h2>\u6295\u7a3f\u5b8c\u4e86</h2>"
            f"<p><strong>\u30d7\u30e9\u30c3\u30c8\u30d5\u30a9\u30fc\u30e0:</strong> {platform}</p>"
            f"<p><strong>\u30bf\u30a4\u30c8\u30eb:</strong> {title}</p>"
            f"<p><a href='{url}'>\u8a18\u4e8b\u3092\u898b\u308b</a></p>"
        )
        return self._send(subject, html)

    def notify_error(self, error: str, context: str) -> bool:
        """Send email about a pipeline error.

        Args:
            error: Error message or traceback excerpt.
            context: Short description of the failing step.

        Returns:
            ``True`` if sent, ``False`` if skipped or failed.
        """
        subject = f"[ai-publisher] \u30a8\u30e9\u30fc: {context}"
        html = (
            f"<h2>\u30a8\u30e9\u30fc\u767a\u751f</h2>"
            f"<p><strong>\u30b3\u30f3\u30c6\u30ad\u30b9\u30c8:</strong> {context}</p>"
            f"<pre style='background:#f8f8f8;padding:12px;'>"
            f"{error}</pre>"
        )
        return self._send(subject, html)

    def notify_daily_summary(self, stats: dict[str, Any]) -> bool:
        """Send a daily summary email.

        Args:
            stats: Dict with keys such as ``generated``, ``published``,
                ``avg_grade``, ``errors``.

        Returns:
            ``True`` if sent, ``False`` if skipped or failed.
        """
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        subject = f"[ai-publisher] \u65e5\u6b21\u30b5\u30de\u30ea\u30fc {today}"
        rows = "".join(
            f"<tr><td>{k}</td><td>{v}</td></tr>"
            for k, v in stats.items()
        )
        html = (
            f"<h2>\u65e5\u6b21\u30b5\u30de\u30ea\u30fc -- {today}</h2>"
            "<table border='1' cellpadding='6' cellspacing='0'>"
            "<tr><th>\u9805\u76ee</th><th>\u5024</th></tr>"
            f"{rows}"
            "</table>"
        )
        return self._send(subject, html)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send(self, subject: str, html_body: str) -> bool:
        """Build a MIME message and send via Gmail API.

        Args:
            subject: Email subject line.
            html_body: HTML content for the email body.

        Returns:
            ``True`` on success, ``False`` otherwise.
        """
        if self._service is None:
            self._logger.debug(
                "Gmail not configured; skipping send for '%s'", subject,
            )
            return False
        try:
            message = MIMEMultipart("alternative")
            message["From"] = self._sender
            message["To"] = self._recipient
            message["Subject"] = subject
            message.attach(MIMEText(html_body, "html", "utf-8"))
            raw = base64.urlsafe_b64encode(
                message.as_bytes(),
            ).decode("ascii")
            self._service.users().messages().send(
                userId="me", body={"raw": raw},
            ).execute()
            self._logger.info("Email sent: %s", subject)
            return True
        except Exception as exc:
            self._logger.warning("Failed to send email '%s': %s", subject, exc)
            return False

    @staticmethod
    def _build_article_table_rows(
        articles: list[dict[str, Any]],
    ) -> str:
        """Render HTML table rows for the pending-approval email."""
        rows: list[str] = []
        for art in articles:
            grade = art.get("overall_grade", "")
            colour = {"A": "green", "B": "orange", "C": "red"}.get(
                grade, "black",
            )
            ev = art.get("evidence_level", "")
            ratio = art.get("tier12_ratio", "")
            ev_display = f"{ev} ({ratio})" if ratio else ev
            rows.append(
                f"<tr>"
                f"<td>{art.get('title', '')}</td>"
                f"<td style='color:{colour}'>{grade}</td>"
                f"<td>{ev_display}</td>"
                f"</tr>"
            )
        return "".join(rows)
