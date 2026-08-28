"""
Audit and verification script for Phase 2:
1. Probes all 5 job boards and checks both `updated_at` and `first_published` fields.
2. Probes all 5 news feeds and checks total fetched, rejected for stale date (>24h), and accepted (<24h).
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import httpx
import feedparser

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.crawler.date_extractor import parse_datetime_to_utc, check_24h_freshness
from src.crawler.news_crawler import AI_NEWS_SOURCES
from src.crawler.job_crawler import AI_JOB_SOURCES


async def audit_job_boards():
    now = datetime.now(timezone.utc)
    print("================================================================")
    print(f"JOB BOARDS TRANSPARENCY AUDIT (Current UTC: {now.isoformat()})")
    print("================================================================")

    total_jobs_fetched = 0
    total_jobs_fresh_updated = 0
    total_jobs_fresh_first_pub = 0
    total_stale_jobs = 0

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for src in AI_JOB_SOURCES:
            name = src["company"]
            url = src["api_url"]
            try:
                res = await client.get(url)
                if res.status_code != 200:
                    print(f"\n[!] {name:15s}: HTTP {res.status_code} ({url})")
                    continue

                data = res.json()
                jobs = data.get("jobs", []) if isinstance(data, dict) else (data[1:] if isinstance(data, list) and len(data) > 1 else [])
                total_jobs_fetched += len(jobs)

                fresh_updated_list = []
                fresh_first_pub_list = []

                for j in jobs:
                    u_date = parse_datetime_to_utc(j.get("updated_at") or j.get("date"))
                    f_date = parse_datetime_to_utc(j.get("first_published"))

                    is_u_fresh, u_age = check_24h_freshness(u_date, now=now)
                    if is_u_fresh:
                        fresh_updated_list.append((j.get("title") or j.get("position"), j.get("absolute_url") or j.get("url"), u_date, u_age))

                    if f_date:
                        is_f_fresh, f_age = check_24h_freshness(f_date, now=now)
                        if is_f_fresh:
                            fresh_first_pub_list.append((j.get("title") or j.get("position"), j.get("absolute_url") or j.get("url"), f_date, f_age))

                total_jobs_fresh_updated += len(fresh_updated_list)
                total_jobs_fresh_first_pub += len(fresh_first_pub_list)
                total_stale_jobs += (len(jobs) - len(fresh_updated_list))

                print(f"\n=== {name.upper()} ({url}) ===")
                print(f"  Total raw jobs fetched   : {len(jobs)}")
                print(f"  Fresh (<24h) by updated  : {len(fresh_updated_list)}")
                print(f"  Fresh (<24h) by first_pub: {len(fresh_first_pub_list)}")
                print(f"  Stale (>24h) rejected    : {len(jobs) - len(fresh_updated_list)}")

                if fresh_updated_list:
                    for sample in fresh_updated_list[:2]:
                        safe_title = sample[0].encode("ascii", "ignore").decode("ascii")
                        print(f"  -> Sample fresh job: \"{safe_title}\" | Age: {sample[3]:.2f}h | Date: {sample[2].isoformat()}")
                        print(f"     URL: {sample[1]}")
                else:
                    print(f"  -> Live status: Board is active ({len(jobs)} total jobs), but 0 posted/updated within last 24h.")

            except Exception as e:
                print(f"\n[ERROR] {name}: {e}")

    print("\n----------------------------------------------------------------")
    print(f"JOB BOARDS SUMMARY:")
    print(f"  Total raw jobs fetched across 5 boards : {total_jobs_fetched}")
    print(f"  Total fresh (<24h) jobs passed         : {total_jobs_fresh_updated}")
    print(f"  Total stale (>24h) jobs rejected       : {total_stale_jobs}")
    print("----------------------------------------------------------------\n")


async def audit_news_sources():
    now = datetime.now(timezone.utc)
    print("================================================================")
    print(f"AI NEWS SOURCES TRANSPARENCY AUDIT (Current UTC: {now.isoformat()})")
    print("================================================================")

    total_news_fetched = 0
    total_news_fresh = 0
    total_news_stale = 0
    total_news_dateless = 0

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for src in AI_NEWS_SOURCES:
            name = src["name"]
            feed_url = src["feed_url"]
            try:
                res = await client.get(feed_url)
                if res.status_code != 200:
                    print(f"\n[!] {name:20s}: HTTP {res.status_code}")
                    continue

                parsed = feedparser.parse(res.text)
                entries = parsed.entries
                total_news_fetched += len(entries)

                fresh_entries = []
                stale_count = 0
                dateless_count = 0

                for entry in entries:
                    date_str = entry.get("published") or entry.get("updated")
                    dt = parse_datetime_to_utc(date_str)
                    if not dt:
                        dateless_count += 1
                        continue

                    is_fresh, age = check_24h_freshness(dt, now=now)
                    if is_fresh:
                        fresh_entries.append((entry.get("title", ""), entry.get("link", ""), dt, age))
                    else:
                        stale_count += 1

                total_news_fresh += len(fresh_entries)
                total_news_stale += stale_count
                total_news_dateless += dateless_count

                print(f"\n=== {name.upper()} ({feed_url}) ===")
                print(f"  Total raw entries fetched: {len(entries)}")
                print(f"  Fresh (<24h) passed      : {len(fresh_entries)}")
                print(f"  Stale (>24h) rejected    : {stale_count}")
                print(f"  Dateless rejected        : {dateless_count}")

                if fresh_entries:
                    for sample in fresh_entries[:2]:
                        print(f"  -> Fresh article: \"{sample[0][:60]}...\" | Age: {sample[3]:.2f}h | Published: {sample[2].isoformat()}")
                        print(f"     URL: {sample[1]}")
                else:
                    print(f"  -> Live status: Feed active ({len(entries)} items), but 0 published within last 24h.")

            except Exception as e:
                print(f"\n[ERROR] {name}: {e}")

    print("\n----------------------------------------------------------------")
    print(f"NEWS FEEDS SUMMARY:")
    print(f"  Total raw news entries fetched across 5 sources: {total_news_fetched}")
    print(f"  Total fresh (<24h) articles passed             : {total_news_fresh}")
    print(f"  Total stale (>24h) articles rejected           : {total_news_stale}")
    print(f"  Total dateless articles rejected               : {total_news_dateless}")
    print("----------------------------------------------------------------\n")


async def main():
    await audit_job_boards()
    await audit_news_sources()


if __name__ == "__main__":
    asyncio.run(main())
