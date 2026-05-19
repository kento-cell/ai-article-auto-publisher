"""Google Sheets integration for article tracking.

Uses *gspread* with a service-account JSON key whose path is read from
the ``GOOGLE_SHEETS_CREDENTIALS_PATH`` environment variable.

Column schema (15 columns — new ``numeric_score`` appended at the end
to avoid shifting existing data in deployed sheets):
    A: article_id, B: title, C: status, D: evidence_level,
    E: overall_grade, F: platform, G: tier12_ratio, H: citation_count,
    I: visual_count, J: originality, K: accuracy, L: readability,
    M: engagement, N: critic_summary, O: numeric_score
"""

from __future__ import annotations

import logging
import os
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

HEADER_ROW = [
    "article_id",      # A: slug or unique ID
    "title",            # B: article title
    "status",           # C: approval status
    "evidence_level",   # D: A/B/C
    "overall_grade",    # E: A/B/C
    "platform",         # F: zenn / note
    "tier12_ratio",     # G: e.g. 83%
    "citation_count",   # H: e.g. 6
    "visual_count",     # I: e.g. 5
    "originality",      # J: A/B/C
    "accuracy",         # K: A/B/C
    "readability",      # L: A/B/C
    "engagement",       # M: A/B/C
    "critic_summary",   # N: 1-line summary
    "numeric_score",    # O: 0-100 composite (Zenn article threshold: 82.5)
]

REJECTED_HEADER_ROW = [
    "title",            # A: article title
    "platform",         # B: zenn / note
    "rejection_reasons",# C: blocking issues
    "timestamp",        # D: ISO timestamp
    "content",          # E: generated content (truncated)
]

STATUS_CHOICES = [
    "\u23f3\u627f\u8a8d\u5f85\u3061",   # ⏳承認待ち
    "\u2705\u627f\u8a8d",               # ✅承認
    "\U0001f504\u518d\u751f\u6210",     # 🔄再生成
    "\u274c\u5374\u4e0b",               # ❌却下
]

# Column indices (1-based) keyed by header name.
_COL_INDEX = {name: idx + 1 for idx, name in enumerate(HEADER_ROW)}

# Colour definitions for conditional formatting (RGB 0-1 scale).
_GREEN_BG = {"red": 0.78, "green": 0.93, "blue": 0.78}
_YELLOW_BG = {"red": 1.0, "green": 0.95, "blue": 0.6}
_RED_BG = {"red": 0.96, "green": 0.74, "blue": 0.74}


class SheetsManager:
    """Read/write article metadata in a Google Sheets spreadsheet.

    If credentials or the spreadsheet ID are not configured the instance
    degrades gracefully -- all public methods return safe defaults and log
    a warning instead of raising.

    Args:
        spreadsheet_id: Google Sheets spreadsheet ID.  Falls back to the
            ``GOOGLE_SHEET_ID`` environment variable.
        worksheet_name: Name of the worksheet tab.  Defaults to
            ``"articles"``.
    """

    def __init__(
        self,
        spreadsheet_id: str | None = None,
        worksheet_name: str = "articles",
    ) -> None:
        self._logger: logging.Logger = get_logger("sheets_manager")
        self._spreadsheet_id: str | None = (
            spreadsheet_id or os.getenv("GOOGLE_SHEET_ID")
        )
        self._worksheet_name = worksheet_name
        self._client: gspread.Client | None = self._authorize()
        self._sheet: gspread.Worksheet | None = self._open_worksheet()
        self._rejected_sheet: gspread.Worksheet | None = self._open_rejected_worksheet()

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _authorize(self) -> gspread.Client | None:
        """Build an authorized gspread client from service-account JSON.

        Returns ``None`` when credentials are not available so the rest
        of the pipeline can continue without Sheets integration.
        """
        cred_path = os.getenv(_ENV_CREDENTIALS)
        if not cred_path:
            self._logger.warning(
                "%s not set; Sheets integration disabled",
                _ENV_CREDENTIALS,
            )
            return None
        if not os.path.isfile(cred_path):
            self._logger.warning(
                "Credentials file not found: %s; Sheets disabled",
                cred_path,
            )
            return None
        try:
            credentials = Credentials.from_service_account_file(
                cred_path, scopes=_SCOPES,
            )
            client = gspread.authorize(credentials)
            self._logger.info("Authorized with Google Sheets API")
            return client
        except Exception as exc:
            self._logger.warning("Google Sheets auth failed: %s", exc)
            return None

    def _open_worksheet(self) -> gspread.Worksheet | None:
        """Open (or create) the target worksheet and ensure headers."""
        if self._client is None or not self._spreadsheet_id:
            return None
        try:
            spreadsheet = self._client.open_by_key(self._spreadsheet_id)
            try:
                ws = spreadsheet.worksheet(self._worksheet_name)
            except gspread.WorksheetNotFound:
                ws = spreadsheet.add_worksheet(
                    title=self._worksheet_name,
                    rows=1000,
                    cols=len(HEADER_ROW),
                )
                self._logger.info(
                    "Created worksheet '%s'", self._worksheet_name,
                )
            self._ensure_headers(ws)
            return ws
        except Exception as exc:
            self._logger.warning("Failed to open worksheet: %s", exc)
            return None

    def _ensure_headers(self, ws: gspread.Worksheet) -> None:
        """Write or refresh the header row to match HEADER_ROW exactly.

        Overwrites the existing row-1 labels when they drift from the
        current schema (new columns, renames) so deployed sheets pick
        up schema additions automatically. Existing data rows are
        untouched — we only append new columns at the end of
        HEADER_ROW, never in the middle, to keep old rows aligned.
        """
        end_col = chr(ord("A") + len(HEADER_ROW) - 1)
        existing = ws.row_values(1)
        if existing == HEADER_ROW:
            return
        ws.update(f"A1:{end_col}1", [HEADER_ROW])
        if existing:
            self._logger.info("Header row refreshed (schema drift fixed)")
        else:
            self._logger.info("Header row written")

    def _open_rejected_worksheet(self) -> gspread.Worksheet | None:
        """Open (or create) the '不合格' worksheet for rejected articles."""
        if self._client is None or not self._spreadsheet_id:
            return None
        try:
            spreadsheet = self._client.open_by_key(self._spreadsheet_id)
            try:
                ws = spreadsheet.worksheet("不合格")
            except gspread.WorksheetNotFound:
                ws = spreadsheet.add_worksheet(
                    title="不合格",
                    rows=1000,
                    cols=len(REJECTED_HEADER_ROW),
                )
                self._logger.info("Created worksheet '不合格'")
            # Ensure headers
            if not ws.acell("A1").value:
                end_col = chr(ord("A") + len(REJECTED_HEADER_ROW) - 1)
                ws.update(f"A1:{end_col}1", [REJECTED_HEADER_ROW])
                self._logger.info("Rejected sheet header row written")
            return ws
        except Exception as exc:
            self._logger.warning("Failed to open rejected worksheet: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_article(self, data: dict[str, Any]) -> int | None:
        """Append a new article row and return its 1-based row number.

        Args:
            data: Dict whose keys match :data:`HEADER_ROW` names.
                Extra keys are silently ignored; missing keys become
                empty strings.

        Returns:
            Row number of the newly appended row, or ``None`` if Sheets
            is not configured.
        """
        if self._sheet is None:
            self._logger.warning(
                "Sheets not configured; skipping add_article",
            )
            return None
        row = [str(data.get(col, "")) for col in HEADER_ROW]
        self._sheet.append_row(row, value_input_option="USER_ENTERED")
        row_num = len(self._sheet.get_all_values())
        self._logger.info(
            "Added article row %d: %s", row_num, data.get("title", ""),
        )
        return row_num

    def add_rejected_article(self, data: dict[str, Any]) -> int | None:
        """Append a rejected article row to the '不合格' sheet.

        Args:
            data: Dict with keys: title, platform, rejection_reasons,
                timestamp, content. Content is truncated to 40000 chars
                to stay within Google Sheets cell limits.

        Returns:
            Row number of the newly appended row, or ``None`` if Sheets
            is not configured.
        """
        if self._rejected_sheet is None:
            self._logger.warning(
                "Rejected sheet not configured; skipping add_rejected_article",
            )
            return None
        # Truncate content to avoid exceeding Sheets cell character limit
        content = str(data.get("content", ""))
        if len(content) > 40000:
            content = content[:40000] + "\n...(truncated)"
        row = [
            str(data.get("title", "")),
            str(data.get("platform", "")),
            str(data.get("rejection_reasons", "")),
            str(data.get("timestamp", "")),
            content,
        ]
        self._rejected_sheet.append_row(
            row, value_input_option="USER_ENTERED",
        )
        row_num = len(self._rejected_sheet.get_all_values())
        self._logger.info(
            "Added rejected article row %d: %s",
            row_num, data.get("title", ""),
        )
        return row_num

    def update_status(self, article_id: str, status: str) -> None:
        """Update the status cell for the row matching *article_id*.

        When multiple rows exist with the same article_id (which
        shouldn't happen but has been observed after re-generation
        pushed a second row for an already-registered id), prefer a
        row whose status is NOT already *status* — otherwise the
        caller's "mark this as ✅投稿済み" intent lands on the older
        already-published row and the fresh ✅承認 duplicate keeps
        getting re-picked by ``get_approved_articles``, causing
        duplicate publishes. Falls back to the first match when no
        row is behind the target status.

        Args:
            article_id: Value to look up in column A.
            status: New status string.

        Raises:
            ValueError: If *article_id* is not found.
        """
        if self._sheet is None:
            self._logger.warning(
                "Sheets not configured; skipping update_status",
            )
            return
        cells = self._sheet.findall(
            article_id, in_column=_COL_INDEX["article_id"],
        )
        if not cells:
            raise ValueError(f"article_id '{article_id}' not found")
        target_cell = None
        for cell in cells:
            current = self._sheet.cell(
                cell.row, _COL_INDEX["status"],
            ).value
            if current != status:
                target_cell = cell
                break
        if target_cell is None:
            target_cell = cells[0]
        self._sheet.update_cell(
            target_cell.row, _COL_INDEX["status"], status,
        )
        self._logger.info(
            "article_id=%s status -> '%s' (row=%d, dup_count=%d)",
            article_id, status, target_cell.row, len(cells),
        )

    def update_row(self, article_id: str, data: dict[str, Any]) -> None:
        """Overwrite every column of an existing row for *article_id*.

        Used after regeneration to push the freshly computed grade,
        evidence level, tier ratio, numeric score, critic summary and
        updated title back to Sheets — previously ``update_status`` was
        the only write path and all those other columns went stale.

        Args:
            article_id: Value to look up in column A.
            data: Dict whose keys match :data:`HEADER_ROW` names.

        Raises:
            ValueError: If *article_id* is not found.
        """
        if self._sheet is None:
            self._logger.warning(
                "Sheets not configured; skipping update_row",
            )
            return
        cell = self._sheet.find(article_id, in_column=_COL_INDEX["article_id"])
        if cell is None:
            raise ValueError(f"article_id '{article_id}' not found")
        row_values = [str(data.get(col, "")) for col in HEADER_ROW]
        end_col = chr(ord("A") + len(HEADER_ROW) - 1)
        self._sheet.update(
            f"A{cell.row}:{end_col}{cell.row}",
            [row_values],
            value_input_option="USER_ENTERED",
        )
        self._logger.info(
            "article_id=%s row updated (%s)",
            article_id, data.get("title", "")[:40],
        )

    def get_pending_articles(self) -> list[dict[str, Any]]:
        """Return rows where status is '⏳承認待ち'.

        Returns:
            List of dicts keyed by :data:`HEADER_ROW` names.
        """
        return [
            rec for rec in self.get_all_articles()
            if rec.get("status") == STATUS_CHOICES[0]
        ]

    def get_approved_articles(self) -> list[dict[str, Any]]:
        """Return rows where status is '✅承認'.

        Returns:
            List of dicts keyed by :data:`HEADER_ROW` names.
        """
        return [
            rec for rec in self.get_all_articles()
            if rec.get("status") == STATUS_CHOICES[1]
        ]

    def get_regeneration_requests(self) -> list[dict[str, Any]]:
        """Return rows where status is '🔄再生成'.

        Returns:
            List of dicts keyed by :data:`HEADER_ROW` names.
        """
        return [
            rec for rec in self.get_all_articles()
            if rec.get("status") == STATUS_CHOICES[2]
        ]

    def archive_old_rows(self, keep_last_n: int = 20) -> dict[str, int]:
        """Delete stale rows to keep the sheet readable.

        Rules:
          - "⏳承認待ち" and "✅承認" rows are NEVER deleted (still actionable).
          - "✅投稿済み" rows: keep only the newest *keep_last_n*
            (by row position — the sheet is append-only so higher row =
            newer). Older ones are deleted.
          - The '不合格' worksheet: keep only the newest *keep_last_n*.

        Returns a dict `{"main_deleted": N, "rejected_deleted": M}`.
        Safe to call when sheets is not configured (no-op, returns zeros).
        """
        deleted = {"main_deleted": 0, "rejected_deleted": 0}
        if self._sheet is None:
            self._logger.warning("Sheets not configured; cleanup skipped")
            return deleted

        # --- Main sheet: purge old 投稿済み ---
        try:
            records = self._sheet.get_all_records(expected_headers=HEADER_ROW)
        except Exception as e:
            self._logger.warning("cleanup: failed to fetch main records: %s", e)
            records = []

        posted_positions: list[int] = []
        for idx, rec in enumerate(records):
            if str(rec.get("status", "")).strip() == "✅投稿済み":
                # Row number = header(1) + data index(0-based) + 1
                posted_positions.append(idx + 2)

        if len(posted_positions) > keep_last_n:
            # Keep the tail (newest). Sheet is append-only so highest row = newest.
            posted_positions.sort()  # ascending row numbers
            to_delete = posted_positions[:-keep_last_n]
            # Group into contiguous ranges and delete each range in ONE
            # API call. Deleting row-by-row blows the Sheets per-minute
            # write-request quota (429) as soon as there are more than
            # ~60 stale rows to purge.
            ranges: list[list[int]] = []
            for row in to_delete:  # ascending
                if ranges and row == ranges[-1][1] + 1:
                    ranges[-1][1] = row
                else:
                    ranges.append([row, row])
            # Delete bottom-up so lower (earlier) ranges keep valid indices.
            for start, end in sorted(ranges, reverse=True):
                try:
                    self._sheet.delete_rows(start, end)
                    deleted["main_deleted"] += end - start + 1
                except Exception as e:
                    self._logger.warning(
                        "cleanup: delete_rows(%d, %d) failed: %s",
                        start, end, e,
                    )

        # --- Rejected sheet: trim to last keep_last_n ---
        rej_ws = self._open_rejected_worksheet()
        if rej_ws is not None:
            try:
                total_rows = rej_ws.row_count
                all_values = rej_ws.get_all_values()
                data_rows = len(all_values) - 1  # exclude header
                excess = data_rows - keep_last_n
                if excess > 0:
                    # Delete rows 2..(1+excess) — the oldest data rows
                    # after the header — in ONE call (row-by-row blows
                    # the per-minute write quota).
                    rej_ws.delete_rows(2, 1 + excess)
                    deleted["rejected_deleted"] += excess
            except Exception as e:
                self._logger.warning("cleanup: rejected sheet trim failed: %s", e)

        self._logger.info(
            "Sheet cleanup: main_deleted=%d rejected_deleted=%d (kept %d)",
            deleted["main_deleted"], deleted["rejected_deleted"], keep_last_n,
        )
        return deleted

    def get_all_articles(self) -> list[dict[str, Any]]:
        """Return every data row as a list of dicts.

        Returns:
            List of dicts keyed by :data:`HEADER_ROW` names.
        """
        if self._sheet is None:
            self._logger.warning(
                "Sheets not configured; returning empty list",
            )
            return []
        try:
            records = self._sheet.get_all_records(expected_headers=HEADER_ROW)
        except IndexError:
            self._logger.debug("No data rows in sheet; returning empty list")
            return []
        except Exception as e:
            self._logger.warning("Failed to fetch sheet records: %s", e)
            return []
        self._logger.debug("Fetched %d article records", len(records))
        return records

    # ------------------------------------------------------------------
    # Formatting setup
    # ------------------------------------------------------------------

    def setup_formatting(self, spreadsheet_id: str | None = None) -> None:
        """Apply data validation, conditional formatting, and layout.

        This method is idempotent -- safe to call multiple times.

        Args:
            spreadsheet_id: Override spreadsheet ID.  Defaults to the ID
                used during construction.
        """
        sid = spreadsheet_id or self._spreadsheet_id
        if self._client is None or not sid:
            self._logger.warning(
                "Sheets not configured; skipping setup_formatting",
            )
            return
        try:
            spreadsheet = self._client.open_by_key(sid)
            sheet_id = self._resolve_sheet_id(spreadsheet)
            requests = self._build_format_requests(sheet_id)
            spreadsheet.batch_update({"requests": requests})
            self._logger.info("Formatting applied to sheet %s", sid)
        except Exception as exc:
            self._logger.warning("setup_formatting failed: %s", exc)

    def _resolve_sheet_id(self, spreadsheet: Any) -> int:
        """Return the numeric sheet ID for the target worksheet."""
        for ws in spreadsheet.worksheets():
            if ws.title == self._worksheet_name:
                return ws.id
        return 0

    def _build_format_requests(self, sheet_id: int) -> list[dict]:
        """Compose batchUpdate request bodies for formatting."""
        requests: list[dict] = []
        requests.append(self._req_status_validation(sheet_id))
        requests.extend(self._req_grade_formatting(sheet_id, col_index=4))
        requests.extend(self._req_grade_formatting(sheet_id, col_index=3))
        requests.extend(self._req_column_widths(sheet_id))
        requests.append(self._req_freeze(sheet_id))
        requests.append(self._req_bold_header(sheet_id))
        return requests

    # --- individual request builders (kept short) ---

    @staticmethod
    def _req_status_validation(sheet_id: int) -> dict:
        """Data-validation dropdown on the status column (C, index 2)."""
        return {
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "startColumnIndex": 2,
                    "endColumnIndex": 3,
                },
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [
                            {"userEnteredValue": v} for v in STATUS_CHOICES
                        ],
                    },
                    "showCustomUi": True,
                    "strict": True,
                },
            },
        }

    @staticmethod
    def _req_grade_formatting(
        sheet_id: int,
        col_index: int,
    ) -> list[dict]:
        """Conditional formatting for a grade column (A/B/C colours)."""
        rules: list[dict] = []
        for value, colour in [("A", _GREEN_BG), ("B", _YELLOW_BG), ("C", _RED_BG)]:
            rules.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "startColumnIndex": col_index,
                            "endColumnIndex": col_index + 1,
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": value}],
                            },
                            "format": {
                                "backgroundColor": colour,
                            },
                        },
                    },
                    "index": 0,
                },
            })
        return rules

    @staticmethod
    def _req_column_widths(sheet_id: int) -> list[dict]:
        """Set column widths: title=250px, status=100px, others=80px."""
        requests: list[dict] = []
        widths = {1: 250, 2: 100}  # 0-indexed: col B=title, col C=status
        for col_idx in range(len(HEADER_ROW)):
            pixel_size = widths.get(col_idx, 80)
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": col_idx,
                        "endIndex": col_idx + 1,
                    },
                    "properties": {"pixelSize": pixel_size},
                    "fields": "pixelSize",
                },
            })
        return requests

    @staticmethod
    def _req_freeze(sheet_id: int) -> dict:
        """Freeze header row and columns A-E."""
        return {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {
                        "frozenRowCount": 1,
                        "frozenColumnCount": 5,
                    },
                },
                "fields": "gridProperties.frozenRowCount,"
                          "gridProperties.frozenColumnCount",
            },
        }

    @staticmethod
    def _req_bold_header(sheet_id: int) -> dict:
        """Bold the entire header row."""
        return {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                    },
                },
                "fields": "userEnteredFormat.textFormat.bold",
            },
        }
