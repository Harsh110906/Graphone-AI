#!/usr/bin/env python3
"""
Google Sheets export script.

Reads pipeline output JSON and exports to Google Sheets (or CSV fallback).

Usage:
    python scripts/run_sheets_export.py --input output/pipeline_results.json
    python scripts/run_sheets_export.py --input output/ --format csv
"""

import argparse
import json
import sys
from pathlib import Path

# Add ingestion root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.observability.logger import setup_logging
from src.export.sheets_export import run_export


def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="GraphOne Sheets Export")
    parser.add_argument(
        "--input",
        type=str,
        default="output/pipeline_results.json",
        help="Input JSON file or directory with per-type JSON files",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input path does not exist: {input_path}")
        sys.exit(1)

    # Load data and organize by tab
    if input_path.is_file():
        with open(input_path, encoding="utf-8") as f:
            records = json.load(f)

        # Group by recordType → tab name mapping
        type_to_tab = {
            "STARTUP": "Startups",
            "PRODUCT": "Products",
            "RESEARCH_PAPER": "Research Papers",
            "JOB": "Jobs",
            "NEWS": "News",
        }

        data: dict[str, list] = {tab: [] for tab in type_to_tab.values()}

        for record in records:
            record_type = record.get("recordType", "")
            tab = type_to_tab.get(record_type)
            if tab:
                data[tab].append(record)

        # Check for entity_mapping_logs.json
        mapping_file = input_path.parent / "entity_mapping_logs.json"
        if mapping_file.exists():
            with open(mapping_file, encoding="utf-8") as f:
                data["Entity Mapping Log"] = json.load(f)
        else:
            data["Entity Mapping Log"] = []

    row_counts = run_export(data)

    print("\nExport complete.")


if __name__ == "__main__":
    main()
