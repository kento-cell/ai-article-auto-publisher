"""Slack webhook notifier for article publishing events.

Sends formatted messages to a Slack channel via an incoming webhook
URL, covering publication success, errors, and daily summaries.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT: int = 10


class SlackNotifier:
    """Send notifications to Slack via an incoming webhook.

    Args:
        webhook_url: Slack incoming webhook URL.
            Falls back to the ``SLACK_WEBHOOK_URL`` environment variable.

    If no webhook URL is available, the notifier is inactive and all
    notification calls silently return ``False``.
    """

    def __init__(self, webhook_url: str | None = None) -> None:
        resolved = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")
        if not resolved:
            logger.warning("SLACK_WEBHOOK_URL not set; notifications will be silently skipped")
            self._webhook_url = None
        else:
            self._webhook_url = resolved
        logger.info("SlackNotifier initialised (active=%s)", self._webhook_url is not None)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def notify_published(
        self, platform: str, title: str, url: str
    ) -> bool:
        """Send a success notification for a published article.

        Args:
            platform: Publishing platform name (e.g. ``"Zenn"``).
            title: Article title.
            url: Published article URL.

        Returns:
            ``True`` if the webhook accepted the message.
        """
        payload = {
            "text": f":white_check_mark: *Article Published on {platform}*",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f":white_check_mark: *Article Published on {platform}*\n"
                            f"*Title:* {title}\n"
                            f"*URL:* <{url}>"
                        ),
                    },
                },
            ],
        }
        return self._send(payload)

    def notify_error(self, error: str, context: str) -> bool:
        """Send an error alert.

        Args:
            error: Error message or exception text.
            context: Description of what was happening when the error occurred.

        Returns:
            ``True`` if the webhook accepted the message.
        """
        payload = {
            "text": f":x: Publishing Error: {error}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            ":x: *Publishing Error*\n"
                            f"*Context:* {context}\n"
                            f"*Error:* ```{error}```"
                        ),
                    },
                },
            ],
        }
        return self._send(payload)

    def notify_daily_summary(self, stats: dict[str, Any]) -> bool:
        """Send a daily summary with counts and scores.

        Expected *stats* keys::

            {
                "articles_generated": int,
                "articles_published": int,
                "platforms": {"Zenn": int, "note": int, ...},
                "avg_quality_score": float,
                "errors": int,
            }

        Args:
            stats: Dictionary of daily statistics.

        Returns:
            ``True`` if the webhook accepted the message.
        """
        generated = stats.get("articles_generated", 0)
        published = stats.get("articles_published", 0)
        platforms = stats.get("platforms", {})
        avg_score = stats.get("avg_quality_score", 0.0)
        errors = stats.get("errors", 0)

        platform_lines = "\n".join(
            f"  - {name}: {count}" for name, count in platforms.items()
        )
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary_text = (
            f":bar_chart: *Daily Summary ({timestamp})*\n"
            f"*Generated:* {generated}\n"
            f"*Published:* {published}\n"
            f"*Platforms:*\n{platform_lines}\n"
            f"*Avg Quality Score:* {avg_score:.1f}\n"
            f"*Errors:* {errors}"
        )

        payload = {
            "text": f"Daily Summary ({timestamp})",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": summary_text},
                },
            ],
        }
        return self._send(payload)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _send(self, payload: dict[str, Any]) -> bool:
        """POST *payload* as JSON to the Slack webhook.

        Args:
            payload: Slack message payload.

        Returns:
            ``True`` if the request succeeded (HTTP 2xx).
        """
        if self._webhook_url is None:
            logger.debug("Slack notification skipped (no webhook configured)")
            return False
        try:
            response = requests.post(
                self._webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=_REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                logger.debug("Slack message sent successfully")
                return True
            logger.warning(
                "Slack webhook returned %d: %s",
                response.status_code,
                response.text,
            )
            return False
        except requests.RequestException:
            logger.exception("Failed to send Slack notification")
            return False
