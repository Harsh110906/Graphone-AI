"""
Export a rich web dataset for instant Vercel search rendering.
"""

import json
from pathlib import Path

pipeline_file = Path(__file__).resolve().parent.parent / "ingestion" / "output" / "pipeline_results.json"
web_data_dir = Path(__file__).resolve().parent.parent / "web" / "src" / "data"
web_data_dir.mkdir(parents=True, exist_ok=True)
output_file = web_data_dir / "records.json"

with open(pipeline_file, "r", encoding="utf-8") as f:
    records = json.load(f)

# Take representative samples across all 5 categories
startups = [r for r in records if r.get("recordType") == "STARTUP"][:400]
products = [r for r in records if r.get("recordType") == "PRODUCT"][:400]
papers = [r for r in records if r.get("recordType") == "RESEARCH_PAPER"][:400]
jobs = [r for r in records if r.get("recordType") == "JOB"]
news = [r for r in records if r.get("recordType") == "NEWS"]

combined = startups + products + papers + jobs + news
print(f"Exporting {len(combined)} records to {output_file}...")

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(combined, f, indent=2, default=str)

print("Done!")
