"""
Analyze source breakdown and sample 20 records from the current startups dataset.
"""

import json
import random
from pathlib import Path
from collections import Counter

results_file = Path("output/pipeline_results.json")
with open(results_file, "r", encoding="utf-8") as f:
    records = json.load(f)

startups = [r for r in records if r.get("recordType") == "STARTUP"]
print(f"Total Startups: {len(startups)}")

# Source breakdown
sources = Counter(s["source"]["name"] for s in startups)
print("\nSOURCE BREAKDOWN:")
for src, count in sources.items():
    print(f"  - {src}: {count} records")

# Sample 20 records
random.seed(42)
sample = random.sample(startups, min(20, len(startups)))
print("\nRANDOM SAMPLE OF 20 STARTUP RECORDS:")
print("-" * 70)
for i, s in enumerate(sample, 1):
    print(f"{i:2d}. entityName: {s['content']['entityName']:<30} | source.url: {s['source']['url']}")
