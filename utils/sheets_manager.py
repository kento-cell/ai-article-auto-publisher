"""Google Sheets integration for article tracking.

Uses *gspread* with a service-account JSON key whose path is read from
the ``GOOGLE_SHEETS_CREDENTIALS_PATH`` environment variable.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from utils.logger import get_logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENV_CREDENTIALS = "GOOGLE_SHEETS_CREDENTIALS_PATH"
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Expected column layout (1-indexed).
_COL_TITLE = 1
_COL_URL = 2
_COL_STATUS = 3
_COL_SCORE = 4
_COL_PUBLISHED_DATE = 5

_HEADER_ROW = [
    "title",
    "url",
    "status",
    "score",
    "published_date",
]


class SheetsManager:
    """Read/write article metadata in a Google Sheets spreadsheet.

    Args:
        spreadsheet_name: Display name (or ID) of the target spreadsheet.
            Defaults to the ``GOOGLE_SHEET_NAME`` or ``GOOGLE_SHEET_ID``
            environment variable.
        worksheet_name: Name of the worksheet tab. Defaults to ``"articles"``.
    """

    def __init__(
        self,
        spreadsheet_name: str | None = None,
        worksheet_name: str = "articles",
    ) -> None:
        self._logger: logging.Logger = get_logger("sheets_manager")
        self._spreadsheet_name = (
            spreadsheet_name
            or os.getenv("GOOGLE_SHEET_NAME")
            or os.getenv("GOOGLE_SHEET_ID")
        )
        self._worksheet_name = worksheet_name
        self._client: gspread.Client | None = self._authorize()
        self._sheet: gspread.Worksheet | None = self._open_worksheet()

    # ------------------------------------------------------------------
    # Auth & setup
    # ------------------------------------------------------------------

    def _authorize(self) -> gspread.Client | None:
        """Build an authorized gspread client from service-account JSON.

        Returns ``None`` and logs a warning when credentials are not
        configured, so the rest of the pipeline can continue without
        Sheets integration.
        """
        cred_path = os.getenv(_ENV_CREDENTIALS)
        if not cred_path:
            self._logger.warning(
                "Environment variable %s is not set; Sheets integration disabled",
                _ENV_CREDENTIALS,
            )
            return None
        if not os.path.isfile(cred_path):
            self._logger.warning(
                "Credentials file not found: %s; Sheets integration disabled",
                cred_path,
            )
            return None

        try:
            credentials = Credentials.from_service_account_file(
                cred_path, scopes=_SCOPES
            )
            client = gspread.authorize(credentials)
            self._logger.info("Authorized with Google Sheets API")
            return client
        except Exception as exc:
            self._logger.warning("Google Sheets auth failed: %s", exc)
            return None

    def _open_worksheet(self) -> gspread.Worksheet | None:
        """Open (or create) the target worksheet and ensure headers exist."""
        if self._client is None or not self._spreadsheet_name:
            return None
        try:
            spreadsheet = self._client.open(self._spreadsheet_name)
            try:
                ws = spreadsheet.worksheet(self._worksheet_name)
            except gspread.WorksheetNotFound:
                ws = spreadsheet.add_worksheet(
                    title=self._worksheet_name, rows=1000, cols=10
                )
                self._logger.info(
                    "Created worksheet '%s'", self._worksheet_name
                )

            self._ensure_headers(ws)
            return ws
        except Exception as exc:
            self._logger.warning("Failed to open worksheet: %s", exc)
            return None

    def _ensure_headers(self, ws: gspread.Worksheet) -> None:
        """Write the header row if cell A1 is empty."""
        if not ws.acell("A1").value:
            ws.update("A1:E1", [_HEADER_ROW])
            self._logger.info("Header row written")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_article(
        self,
        data: dict[str, Any] | None = None,
        /,
        *,
        title: str = "",
        url: str = "",
        status: str = "pending",
        score: float = 0.0,
        published_date: str = "",
        **kwargs: Any,
    ) -> int | None:
        """Append a new article row and return its (1-based) row number.

        Accepts either a dict as the first positional argument **or**
        keyword arguments.  Dict keys are mapped to the column names:
        ``title``, ``url``, ``status``, ``score``, ``published_date``.
        Extra keys (e.g. ``platform``, ``price``) are silently ignored.

        Returns:
            Row number of the newly appended row, or ``None`` if Sheets
            is not configured.
        """
        if self._sheet is None:
            self._logger.warning("Sheets not configured; skipping add_article")
            return None

        if data is not None:
            title = data.get("title", title)
            url = data.get("url", url)
            status = data.get("status", status)
            score = data.get("score", score)
            published_date = data.get("published_date", published_date)

        row = [title, url, status, str(score), published_date]
        self._sheet.append_row(row, value_input_option="USER_ENTERED")
        row_num = len(self._sheet.get_all_values())
        self._logger.info("Added article row %d: %s", row_num, title)
        return row_num

    def update_status(self, row: int, status: str) -> None:
        """Update the status cell for the given row.

        Args:
            row: 1-based row number (must be > 1 to skip header).
            status: New status value.

        Raises:
            ValueError: If *row* refers to the header row.
        """
        if self._sheet is None:
            self._logger.warning("Sheets not configured; skipping update_status")
            return
        if row <= 1:
            raise ValueError("Cannot update the header row")
        self._sheet.update_cell(row, _COL_STATUS, status)
        self._logger.info("Row %d status -> '%s'", row, status)

    def get_pending_articles(self) -> list[dict[str, Any]]:
        """Return all rows whose status is ``'pending'``.

        Returns:
            List of dicts with keys matching :data:`_HEADER_ROW`.
        """
        return [
            rec
            for rec in self.get_all_articles()
            if rec.get("status", "").lower() == "pending"
        ]

    def get_all_articles(self) -> list[dict[str, Any]]:
        """Return every data row as a list of dicts.

        Returns:
            List of dicts with keys matching :data:`_HEADER_ROW`.
        """
        if self._sheet is None:
            self._logger.warning("Sheets not configured; returning empty list")
            return []
        records = self._sheet.get_all_records(expected_headers=_HEADER_ROW)
        self._logger.debug("Fetched %d article records", len(records))
        return records
