"""
Phase 4 Scale Run Spot Checker.

Selects 10 random product records, 10 random research paper records, and 10 random startup records
from the live pipeline run and outputs them with their quality score breakdown and lineage.
"""

import json
import random
from pathlib import Path

results_file = Path("output/pipeline_results.json")
with open(results_file, "r", encoding="utf-8") as f:
    records = json.load(f)

products = [r for r in records if r.get("recordType") == "PRODUCT"]
papers = [r for r in records if r.get("recordType") == "RESEARCH_PAPER"]
startups = [r for r in records if r.get("recordType") == "STARTUP"]

print(f"Total Products: {len(products)}, Papers: {len(papers)}, Startups: {len(startups)}")

random.seed(42)

print("\n" + "=" * 60)
print("10 SPOT-CHECKED PRODUCTS (PARENT COMPANY & PRICING ATTRIBUTION)")
print("=" * 60)
for p in random.sample(products, min(10, len(products))):
    print(f"URL: {p['source']['url']}")
    print(f"  startupName (Parent Co) : {p['content'].get('startupName')}")
    print(f"  pricingModel            : {p['content'].get('pricingModel')}")
    print(f"  DQS Score               : {p.get('dataQualityScore')} {p.get('qualityBreakdown')}")
    print("-" * 50)

print("\n" + "=" * 60)
print("10 SPOT-CHECKED RESEARCH PAPERS (HUMAN AUTHOR EXTRACTION)")
print("=" * 60)
for p in random.sample(papers, min(10, len(papers))):
    print(f"Title   : {p['content']['title'][:60]}...")
    print(f"URL     : {p['content']['paper_url']}")
    print(f"Authors : {p['content']['authors']}")
    print(f"Stars   : {p['content']['github_stars']}")
    print(f"DQS     : {p.get('dataQualityScore')}")
    print("-" * 50)

print("\n" + "=" * 60)
print("10 SPOT-CHECKED STARTUPS (NO SEED CONTAMINATION & EMPLOYEE COUNT)")
print("=" * 60)
for s in random.sample(startups, min(10, len(startups))):
    print(f"Entity Name    : {s['content']['entityName']}")
    print(f"Source URL     : {s['source']['url']}")
    print(f"employeeCount  : {s['content']['data'].get('employeeCount')}")
    print(f"DQS            : {s.get('dataQualityScore')}")
    print("-" * 50)
