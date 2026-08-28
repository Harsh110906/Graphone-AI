"""
AI News crawler supporting 5 reputable sources with strict 24-hour freshness enforcement.

Sources:
1. TechCrunch AI (Official RSS: https://techcrunch.com/category/artificial-intelligence/feed/)
2. VentureBeat AI (Official RSS: https://venturebeat.com/category/ai/feed/)
3. The Verge AI (Official RSS: https://www.theverge.com/rss/ai-artificial-intelligence/index.xml)
4. MIT Technology Review (Official RSS: https://www.technologyreview.com/feed/)
5. Ars Technica AI / Tech (Official RSS: https://feeds.arstechnica.com/arstechnica/technology-lab)

Process:
Feed Discovery -> Fetch Full Article -> Date Extraction Waterfall -> 24h Freshness Filter -> Boilerplate Removal -> Entity Matching -> Pydantic Schema Validation.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

import feedparser
import structlog

from src.crawler.base import BaseCrawler, CrawlerError, RawDocument
from src.crawler.date_extractor import DateExtractionWaterfall, check_24h_freshness
from src.crawler.incremental import IncrementalCrawlTracker
from src.crawler.rate_limiter import DomainRateLimiter
from src.crawler.text_extractor import TextExtractor
from src.schemas.news import News, NewsContent
from src.schemas.startup import Source

logger = structlog.get_logger(__name__)

# Configured 5 AI News Feeds
AI_NEWS_SOURCES = [
    {
        "name": "TechCrunch AI",
        "feed_url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "domain": "techcrunch.com",
    },
    {
        "name": "VentureBeat AI",
        "feed_url": "https://venturebeat.com/category/ai/feed/",
        "domain": "venturebeat.com",
    },
    {
        "name": "The Verge AI",
        "feed_url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "domain": "theverge.com",
    },
    {
        "name": "MIT Technology Review",
        "feed_url": "https://www.technologyreview.com/feed/",
        "domain": "technologyreview.com",
    },
    {
        "name": "Ars Technica AI",
        "feed_url": "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "domain": "arstechnica.com",
    },
]


class NewsCrawler(BaseCrawler):
    """
    Crawler for multi-source AI news monitoring with guaranteed 24-hour freshness.
    """

    def __init__(
        self,
        sources: List[Dict[str, str]] | None = None,
        max_age_hours: float = 24.0,
        incremental_tracker: IncrementalCrawlTracker | None = None,
        rate_limiter: DomainRateLimiter | None = None,
    ):
        limiter = rate_limiter or DomainRateLimiter(
            requests_per_second=1.0,
            max_concurrent=2,
            burst=2,
        )
        super().__init__(
            source_name="ai_news_aggregator",
            rate_limiter=limiter,
            max_retries=2,
            timeout_seconds=25,
            concurrency=2,
        )
        self.sources = sources or AI_NEWS_SOURCES
        self.max_age_hours = max_age_hours
        self.incremental_tracker = incremental_tracker or IncrementalCrawlTracker()
        self._feed_entries: List[Dict[str, Any]] = []

    async def discover(self) -> AsyncIterator[str]:
        """
        Discover article URLs across all configured RSS/Atom news feeds.
        """
        client = await self._get_client()

        for src in self.sources:
            feed_url = src["feed_url"]
            source_name = src["name"]
            logger.info("discovering_news_feed", source=source_name, feed_url=feed_url)

            try:
                await self.rate_limiter.acquire(feed_url)
                try:
                    response = await client.get(feed_url)
                finally:
                    self.rate_limiter.release(feed_url)

                if response.status_code != 200:
                    logger.warning(
                        "news_feed_fetch_failed",
                        source=source_name,
                        status_code=response.status_code,
                    )
                    continue

                parsed = feedparser.parse(response.text)
                entries = parsed.entries
                logger.info(
                    "news_feed_parsed",
                    source=source_name,
                    entry_count=len(entries),
                )

                for entry in entries:
                    link = entry.get("link")
                    if not link:
                        continue

                    # Store feed entry metadata for fallback matching
                    title = entry.get("title", "")
                    published = entry.get("published") or entry.get("updated")
                    summary = entry.get("summary", "")

                    feed_meta = {
                        "source_name": source_name,
                        "url": link,
                        "title": title,
                        "feed_published": published,
                        "feed_summary": summary,
                    }
                    self._feed_entries.append(feed_meta)
                    yield link

            except Exception as e:
                logger.error(
                    "news_feed_discovery_error",
                    source=source_name,
                    error=str(e),
                )

    async def parse(self, doc: RawDocument) -> list[dict[str, Any]]:
        """
        Parse raw HTML document into a validated News record.
        Strictly enforces 24-hour freshness via the 6-step date waterfall.
        """
        url = doc.source_url

        # Locate corresponding feed metadata
        feed_meta = next((f for f in self._feed_entries if f["url"] == url), {})
        source_name = feed_meta.get("source_name", doc.source_name)
        feed_title = feed_meta.get("title", "")
        feed_timestamp = feed_meta.get("feed_published")

        # ── Step 1: Execute Date Extraction Waterfall ──
        last_modified = doc.headers.get("last-modified")
        extracted_date, date_method = DateExtractionWaterfall.extract_date(
            html=doc.raw_content,
            feed_timestamp=feed_timestamp,
            last_modified_header=last_modified,
        )

        if not extracted_date:
            logger.warning(
                "news_record_rejected_no_date",
                url=url,
                reason="Failed to extract verifiable publication date across 6 waterfall steps.",
            )
            return []

        # ── Step 2: Enforce Hard 24-Hour Freshness Window ──
        is_fresh, age_hours = check_24h_freshness(extracted_date, max_age_hours=self.max_age_hours)
        if not is_fresh:
            logger.info(
                "news_record_skipped_stale",
                url=url,
                published_at=extracted_date.isoformat(),
                age_hours=round(age_hours, 2),
                max_allowed_hours=self.max_age_hours,
            )
            return []

        # ── Step 3: Full-Text Boilerplate Removal ──
        full_text, excerpt = TextExtractor.clean_html_to_text(doc.raw_content)
        if not full_text or len(full_text) < 80:
            # If HTML parsing stripped too much, fallback to feed summary + visible snippet
            full_text = feed_meta.get("feed_summary", full_text)

        if not full_text:
            logger.warning("news_record_rejected_empty_body", url=url)
            return []

        # ── Step 4: Title Extraction ──
        title = feed_title
        if not title:
            # Extract from <title> or <h1>
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(doc.raw_content, "lxml")
                h1 = soup.find("h1")
                if h1 and h1.text.strip():
                    title = h1.text.strip()
                elif soup.title and soup.title.text.strip():
                    title = soup.title.text.strip()
            except Exception:
                pass

        if not title:
            title = "Untitled AI Article"

        # ── Step 5: Entity Mention Extraction (Simple Keyword Matcher) ──
        mentioned_entities = self._extract_mentioned_entities(full_text + " " + title)

        # ── Step 6: Validate Pydantic Schema ──
        collected_at = datetime.now(timezone.utc)
        record = {
            "schemaVersion": "1.0",
            "recordType": "NEWS",
            "source": {
                "name": source_name,
                "url": url,
            },
            "content": {
                "title": title,
                "fullText": full_text,
                "publishedAt": extracted_date.isoformat(),
                "mentionedEntities": mentioned_entities,
            },
            "collectedAt": collected_at.isoformat(),
            "_metadata": {
                "date_extraction_method": date_method,
                "age_hours": round(age_hours, 2),
                "excerpt": excerpt,
            },
        }

        # Validate with Pydantic model
        try:
            News(
                schemaVersion="1.0",
                recordType="NEWS",
                source=Source(name=source_name, url=url),
                content=NewsContent(
                    title=title,
                    fullText=full_text,
                    publishedAt=extracted_date,
                    mentionedEntities=mentioned_entities,
                ),
                collectedAt=collected_at,
            )
        except Exception as e:
            logger.error("news_schema_validation_failed", url=url, error=str(e))
            return []

        logger.info(
            "news_record_accepted_fresh",
            title=title[:60],
            source=source_name,
            published_at=extracted_date.isoformat(),
            age_hours=round(age_hours, 2),
            method=date_method,
        )

        return [record]

    @staticmethod
    def _extract_mentioned_entities(text: str) -> list[str]:
        """Extract canonical AI entity mentions from text."""
        known_entities = [
            "OpenAI", "Anthropic", "Google DeepMind", "Meta AI", "Mistral AI",
            "Cohere", "xAI", "Stability AI", "Midjourney", "Runway",
            "Hugging Face", "LangChain", "Pinecone", "NVIDIA", "AMD",
            "Databricks", "Snowflake", "Scale AI", "Perplexity AI", "Cursor",
            "DeepSeek", "Microsoft", "Amazon AWS", "Apple", "Groq",
        ]
        found = []
        for ent in known_entities:
            pattern = r"\b" + re.escape(ent) + r"\b"
            if re.search(pattern, text, re.IGNORECASE):
                found.append(ent)
        return found
