"""
Inspect updated startup dataset and entity mapping logs after fixes.
"""

import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

# 1. Startups Inspection
with open("output/pipeline_results.json", "r", encoding="utf-8") as f:
    records = json.load(f)

startups = [r for r in records if r.get("recordType") == "STARTUP"]
print(f"TOTAL FILTERED STARTUPS: {len(startups)}")

sources = Counter(s["source"]["name"] for s in startups)
print("\nSOURCE BREAKDOWN FOR STARTUPS:")
for src, count in sources.items():
    print(f"  - {src:<45}: {count} records")

random.seed(1337)
sample = random.sample(startups, 20)
print("\nRANDOM SAMPLE OF 20 VERIFIED STARTUP RECORDS:")
print("-" * 85)
for i, s in enumerate(sample, 1):
    print(f"{i:2d}. entityName: {s['content']['entityName']:<30} | source.url: {s['source']['url']}")

# 2. Entity Mapping Log Inspection
with open("output/entity_mapping_logs.json", "r", encoding="utf-8") as f:
    mapping_logs = json.load(f)

print(f"\nTOTAL ENTITY MAPPING LOG RECORDS: {len(mapping_logs)}")

methods = Counter(m["method"] for m in mapping_logs)
print("\nENTITY MAPPING DECISION BY METHOD:")
for meth, count in methods.items():
    print(f"  - {meth:<25}: {count} records")

decisions = Counter(m["decision"] for m in mapping_logs)
print("\nENTITY MAPPING DECISIONS:")
for dec, count in decisions.items():
    print(f"  - {dec:<25}: {count} records")
