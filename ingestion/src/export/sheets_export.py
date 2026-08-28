"""
Google Sheets export — pushes pipeline output to a public Google Sheet.

6 required tabs:
1. Startups (min 1,000 rows)
2. Products (min 1,000 rows)
3. Research Papers (min 1,000 rows)
4. Jobs (all 24h-fresh)
5. News (all 24h-fresh)
6. Entity Mapping Log (all resolution decisions)

Dev fallback: writes CSV files to output/ when no Google credentials configured.
This is a DEVELOPMENT CONVENIENCE ONLY — not a submission substitute.

The export is idempotent: clear-and-rewrite each tab on every run.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)

# Tab definitions: (tab_name, columns, min_rows_for_submission)
TAB_DEFINITIONS = [
    (
        "Startups",
        [
            "schemaVersion", "recordType", "source.name", "source.url",
            "content.entityName", "content.data.employeeCount", "collectedAt",
        ],
        1000,
    ),
    (
        "Products",
        [
            "schemaVersion", "recordType", "source.name", "source.url",
            "content.startupName", "content.pricingModel", "collectedAt",
        ],
        1000,
    ),
    (
        "Research Papers",
        [
            "schemaVersion", "recordType", "content.title", "content.authors",
            "content.paper_url", "content.github_url", "content.github_stars",
            "content.published_date",
        ],
        1000,
    ),
    (
        "Jobs",
        [
            "schemaVersion", "recordType", "source.name", "source.url",
            "content.company", "content.date", "content.is_remote", "content.role_family",
        ],
        0,  # All 24h-fresh jobs found
    ),
    (
        "News",
        [
            "source.name", "source.url", "content.title",
            "content.publishedAt", "content.fullText", "collectedAt",
        ],
        0,  # All 24h-fresh news found
    ),
    (
        "Entity Mapping Log",
        [
            "rawName", "canonicalName", "method", "confidence",
            "sourceUrl", "decision",
        ],
        0,  # All resolution decisions
    ),
]


def flatten_record(record: dict[str, Any], columns: list[str]) -> list[str]:
    """
    Flatten a nested record into a flat row based on column definitions.

    Handles dotted paths like 'content.entityName' and 'source.url'.
    Lists are JSON-serialized for spreadsheet readability.
    """
    row = []
    for col in columns:
        parts = col.split(".")
        value = record
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break

        # Format value for spreadsheet
        if value is None:
            row.append("")
        elif isinstance(value, list):
            row.append(json.dumps(value, ensure_ascii=False))
        elif isinstance(value, bool):
            row.append(str(value).upper())
        elif isinstance(value, datetime):
            row.append(value.isoformat())
        else:
            row.append(str(value))

    return row


def export_to_csv(
    data: dict[str, list[dict[str, Any]]],
    output_dir: str | Path = "output",
) -> dict[str, int]:
    """
    Export data to CSV files (development fallback when no Google credentials).

    Args:
        data: Dict mapping tab names to lists of records.
        output_dir: Directory to write CSV files to.

    Returns:
        Dict mapping tab name to row count.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    row_counts = {}

    for tab_name, columns, _min_rows in TAB_DEFINITIONS:
        records = data.get(tab_name, [])
        filename = output_path / f"{tab_name.lower().replace(' ', '_')}.csv"

        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for record in records:
                writer.writerow(flatten_record(record, columns))

        row_counts[tab_name] = len(records)
        logger.info(
            "csv_export_complete",
            tab=tab_name,
            rows=len(records),
            file=str(filename),
        )

    return row_counts


def export_to_google_sheets(
    data: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    """
    Export data to Google Sheets.

    Requires GOOGLE_SHEETS_CREDENTIALS_PATH and GOOGLE_SHEET_ID in .env.
    Each tab is cleared and rewritten (idempotent).

    The sheet must be shared with the service account email and set to
    "Anyone with the link can view" for submission.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        logger.error(
            "google_sheets_deps_missing",
            hint="Install gspread and google-auth: pip install gspread google-auth",
        )
        raise

    # Authenticate
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_path = Path(settings.google_sheets_credentials_path)
    if not creds_path.is_absolute() and not creds_path.exists():
        candidate = Path(__file__).resolve().parent.parent.parent / creds_path
        if candidate.exists():
            creds_path = candidate

    creds = Credentials.from_service_account_file(
        str(creds_path),
        scopes=scopes,
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(settings.google_sheet_id)

    row_counts = {}

    for tab_name, columns, _min_rows in TAB_DEFINITIONS:
        records = data.get(tab_name, [])

        # Get or create worksheet
        try:
            worksheet = spreadsheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=tab_name,
                rows=max(len(records) + 1, 100),
                cols=len(columns),
            )

        # Clear existing content (idempotent)
        worksheet.clear()

        # Build rows: header + data
        all_rows = [columns]
        for record in records:
            all_rows.append(flatten_record(record, columns))

        # Batch update for efficiency
        if all_rows:
            worksheet.update(
                range_name=f"A1:{_col_letter(len(columns))}{len(all_rows)}",
                values=all_rows,
            )

        row_counts[tab_name] = len(records)
        logger.info(
            "sheets_export_complete",
            tab=tab_name,
            rows=len(records),
        )

    return row_counts


def _col_letter(n: int) -> str:
    """Convert 1-indexed column number to letter (1='A', 26='Z', 27='AA')."""
    result = ""
    while n > 0:
        n -= 1
        result = chr(65 + n % 26) + result
        n //= 26
    return result


def run_export(data: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """
    Run the export — Google Sheets if credentials available, CSV fallback otherwise.

    Returns row counts per tab.
    """
    if settings.has_sheets_credentials:
        logger.info("export_target", target="google_sheets")
        row_counts = export_to_google_sheets(data)
    else:
        logger.warning(
            "export_fallback_csv",
            reason="No Google Sheets credentials configured",
            hint="Set GOOGLE_SHEETS_CREDENTIALS_PATH and GOOGLE_SHEET_ID in .env",
        )
        row_counts = export_to_csv(data)

    # Print summary
    print("\n" + "=" * 60)
    print("EXPORT SUMMARY")
    print("=" * 60)
    for tab_name, _, min_rows in TAB_DEFINITIONS:
        count = row_counts.get(tab_name, 0)
        status = "[OK]" if count >= min_rows or min_rows == 0 else f"[FAIL] (need {min_rows})"
        print(f"  {tab_name:25s} {count:>8,d} rows  {status}")
    print("=" * 60)

    return row_counts
