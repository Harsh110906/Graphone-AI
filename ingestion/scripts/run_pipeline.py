#!/usr/bin/env python3
"""
CLI entry point for the GraphOne ingestion pipeline.

Supports running specific sources or all sources with strict deduplication, entity resolution, and freshness checks:
    python scripts/run_pipeline.py --source arxiv --max-items 10
    python scripts/run_pipeline.py --source pwc --max-items 10
    python scripts/run_pipeline.py --source startups --max-items 20
    python scripts/run_pipeline.py --source products --max-items 20
    python scripts/run_pipeline.py --source news --max-items 10
    python scripts/run_pipeline.py --source jobs --max-items 10
    python scripts/run_pipeline.py --source all --max-items 20
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add ingestion root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.observability.logger import setup_logging
from src.crawler.arxiv_crawler import ArxivCrawler
from src.crawler.github_client import GitHubClient
from src.crawler.pwc_crawler import PwcCrawler
from src.crawler.startup_crawler import StartupCrawler
from src.crawler.product_crawler import ProductCrawler
from src.crawler.news_crawler import NewsCrawler
from src.crawler.job_crawler import JobCrawler
from src.crawler.incremental import IncrementalCrawlTracker
from src.storage.dedup import DeduplicationEngine
from src.storage.entity_resolver import EntityResolver

import structlog

logger = structlog.get_logger(__name__)


async def run_arxiv_pipeline(max_items: int, dedup: DeduplicationEngine, github_client: GitHubClient) -> list[dict]:
    """Run the arXiv crawler with GitHub star enrichment."""
    records = []
    logger.info("pipeline_start_source", source="arxiv", max_items=max_items)

    async with ArxivCrawler(max_results=max_items, github_client=github_client) as crawler:
        async for record in crawler.run(max_items=max_items):
            result = dedup.check_and_register(record)
            if result.is_duplicate:
                continue
            records.append(record)

    logger.info("pipeline_source_finished", source="arxiv", count=len(records))
    return records


async def run_pwc_pipeline(max_items: int, dedup: DeduplicationEngine, github_client: GitHubClient) -> list[dict]:
    """Run the Papers with Code crawler with live GitHub star metrics."""
    records = []
    logger.info("pipeline_start_source", source="pwc", max_items=max_items)

    async with PwcCrawler(max_results=max_items, github_client=github_client) as crawler:
        async for record in crawler.run(max_items=max_items):
            result = dedup.check_and_register(record)
            if result.is_duplicate:
                continue
            records.append(record)

    logger.info("pipeline_source_finished", source="pwc", count=len(records))
    return records


async def run_startups_pipeline(max_items: int, dedup: DeduplicationEngine, resolver: EntityResolver) -> list[dict]:
    """Run the AI Startups crawler with entity resolution canonicalization."""
    records = []
    logger.info("pipeline_start_source", source="startups", max_items=max_items)

    async with StartupCrawler(max_results=max_items) as crawler:
        async for record in crawler.run(max_items=max_items):
            # Run through entity resolution
            raw_name = record["content"]["entityName"]
            source_url = str(record["source"]["url"])
            canonical, decision, score, method = resolver.resolve(raw_name, source_url=source_url)
            if canonical:
                record["content"]["entityName"] = canonical

            result = dedup.check_and_register(record)
            if result.is_duplicate:
                continue
            records.append(record)

    logger.info("pipeline_source_finished", source="startups", count=len(records))
    return records


async def run_products_pipeline(max_items: int, dedup: DeduplicationEngine, resolver: EntityResolver) -> list[dict]:
    """Run the AI Products crawler with pricing model classification."""
    records = []
    logger.info("pipeline_start_source", source="products", max_items=max_items)

    async with ProductCrawler(max_results=max_items) as crawler:
        async for record in crawler.run(max_items=max_items):
            raw_name = record["content"]["startupName"]
            source_url = str(record["source"]["url"])
            canonical, decision, score, method = resolver.resolve(raw_name, source_url=source_url)
            if canonical:
                record["content"]["startupName"] = canonical

            result = dedup.check_and_register(record)
            if result.is_duplicate:
                continue
            records.append(record)

    logger.info("pipeline_source_finished", source="products", count=len(records))
    return records


async def run_news_pipeline(max_items: int, dedup: DeduplicationEngine) -> list[dict]:
    """Run the AI News crawler with 24h freshness enforcement."""
    tracker = IncrementalCrawlTracker(state_file_path="output/crawl_state.json")
    records = []
    logger.info("pipeline_start_source", source="news", max_items=max_items)

    async with NewsCrawler(max_age_hours=24.0, incremental_tracker=tracker) as crawler:
        async for record in crawler.run(max_items=max_items):
            result = dedup.check_and_register(record)
            if result.is_duplicate:
                continue
            records.append(record)

    tracker.save()
    logger.info("pipeline_source_finished", source="news", count=len(records))
    return records


async def run_jobs_pipeline(max_items: int, dedup: DeduplicationEngine) -> list[dict]:
    """Run the AI Jobs crawler with first_published precedence & 24h freshness enforcement."""
    records = []
    logger.info("pipeline_start_source", source="jobs", max_items=max_items)

    async with JobCrawler(max_age_hours=24.0) as crawler:
        async for record in crawler.run(max_items=max_items):
            result = dedup.check_and_register(record)
            if result.is_duplicate:
                continue
            records.append(record)

    logger.info("pipeline_source_finished", source="jobs", count=len(records))
    return records


async def run_all(source: str, max_items: int) -> tuple[list[dict], DeduplicationEngine, EntityResolver, GitHubClient]:
    """Orchestrate crawler execution across selected sources."""
    setup_logging()
    dedup = DeduplicationEngine()
    resolver = EntityResolver()
    github_client = GitHubClient()
    all_records = []

    try:
        if source in ("arxiv", "all"):
            all_records.extend(await run_arxiv_pipeline(max_items, dedup, github_client))

        if source in ("pwc", "all"):
            all_records.extend(await run_pwc_pipeline(max_items, dedup, github_client))

        if source in ("startups", "all"):
            all_records.extend(await run_startups_pipeline(max_items, dedup, resolver))

        if source in ("products", "all"):
            all_records.extend(await run_products_pipeline(max_items, dedup, resolver))

        if source in ("news", "all"):
            all_records.extend(await run_news_pipeline(max_items, dedup))

        if source in ("jobs", "all"):
            all_records.extend(await run_jobs_pipeline(max_items, dedup))

        logger.info(
            "pipeline_complete_summary",
            total_records=len(all_records),
            dedup_stats=dedup.stats,
            mappings_count=len(resolver.mapping_logs),
            github_quota_remaining=github_client.remaining,
        )
    finally:
        await github_client.close()

    return all_records, dedup, resolver, github_client


def main():
    parser = argparse.ArgumentParser(description="GraphOne Ingestion Pipeline")
    parser.add_argument(
        "--source",
        choices=["arxiv", "pwc", "startups", "products", "news", "jobs", "all"],
        default="all",
        help="Source(s) to crawl",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=10,
        help="Maximum items to fetch per source category",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output/pipeline_results.json",
        help="Output file path",
    )
    args = parser.parse_args()

    records, dedup, resolver, gh_client = asyncio.run(run_all(source=args.source, max_items=args.max_items))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    clean_records = []
    for r in records:
        clean = {k: v for k, v in r.items() if not k.startswith("_")}
        clean_records.append(clean)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(clean_records, f, indent=2, default=str, ensure_ascii=False)

    # Save entity mapping logs
    mapping_logs_path = output_path.parent / "entity_mapping_logs.json"
    with open(mapping_logs_path, "w", encoding="utf-8") as f:
        json.dump(resolver.mapping_logs, f, indent=2, default=str, ensure_ascii=False)

    print(f"\n[OK] Pipeline complete: {len(clean_records)} records written to {output_path}")
    print(f"[OK] Entity mapping logs: {len(resolver.mapping_logs)} entries written to {mapping_logs_path}")

    # Print summary per recordType
    type_counts = {}
    for r in clean_records:
        rt = r.get("recordType", "UNKNOWN")
        type_counts[rt] = type_counts.get(rt, 0) + 1

    print("\n--- INGESTION SUMMARY BY TYPE ---")
    for rt, count in type_counts.items():
        print(f"  {rt:20s}: {count} records")
    print("---------------------------------")
    print(f"Dedup Stats: {dedup.stats}")
    print(f"GitHub API Remaining: {gh_client.remaining} requests\n")


if __name__ == "__main__":
    main()
