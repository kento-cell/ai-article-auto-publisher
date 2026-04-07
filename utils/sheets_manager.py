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
        spreadsheet_name: Display name of the target spreadsheet.
        worksheet_name: Name of the worksheet tab. Defaults to ``"articles"``.
    """

    def __init__(
        self,
        spreadsheet_name: str,
        worksheet_name: str = "articles",
    ) -> None:
        self._logger: logging.Logger = get_logger("sheets_manager")
        self._spreadsheet_name = spreadsheet_name
        self._worksheet_name = worksheet_name
        self._client: gspread.Client = self._authorize()
        self._sheet: gspread.Worksheet = self._open_worksheet()

    # ------------------------------------------------------------------
    # Auth & setup
    # ------------------------------------------------------------------

    def _authorize(self) -> gspread.Client:
        """Build an authorized gspread client from service-account JSON.

        Raises:
            EnvironmentError: If the credentials env var is missing.
            FileNotFoundError: If the credentials file does not exist.
        """
        cred_path = os.getenv(_ENV_CREDENTIALS)
        if not cred_path:
            raise EnvironmentError(
                f"Environment variable {_ENV_CREDENTIALS} is not set"
            )
        if not os.path.isfile(cred_path):
            raise FileNotFoundError(
                f"Credentials file not found: {cred_path}"
            )

        credentials = Credentials.from_service_account_file(
            cred_path, scopes=_SCOPES
        )
        client = gspread.authorize(credentials)
        self._logger.info("Authorized with Google Sheets API")
        return client

    def _open_worksheet(self) -> gspread.Worksheet:
        """Open (or create) the target worksheet and ensure headers exist."""
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
        title: str,
        url: str,
        status: str = "pending",
        score: float = 0.0,
        published_date: str = "",
    ) -> int:
        """Append a new article row and return its (1-based) row number.

        Args:
            title: Article title.
            url: Article URL.
            status: Workflow status (e.g. ``"pending"``, ``"published"``).
            score: Relevance or quality score.
            published_date: ISO-format date string, or empty.

        Returns:
            Row number of the newly appended row.
        """
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
        records = self._sheet.get_all_records(expected_headers=_HEADER_ROW)
        self._logger.debug("Fetched %d article records", len(records))
        return records
