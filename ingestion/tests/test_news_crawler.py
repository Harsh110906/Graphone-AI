"""
Unit tests for NewsCrawler.

Verifies:
- 24-hour freshness enforcement on news articles
- Rejection of dateless articles
- Rejection of stale (>24h) articles
- Pydantic schema conformance of accepted news records
- Mentioned entity keyword resolution
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest

from src.crawler.base import RawDocument
from src.crawler.news_crawler import NewsCrawler


class TestNewsCrawler:
    """Test suite for NewsCrawler parsing and freshness filtering."""

    @pytest.mark.asyncio
    async def test_fresh_news_article_accepted(self):
        """Article published 2 hours ago is parsed, cleaned, and accepted."""
        now = datetime.now(timezone.utc)
        pub_iso = (now - timedelta(hours=2)).isoformat()

        raw_html = f"""
        <html>
          <head>
            <title>Anthropic Launches Claude 3.5 Sonnet Update</title>
            <meta property="article:published_time" content="{pub_iso}" />
          </head>
          <body>
            <header><nav>Home | AI</nav></header>
            <main>
              <h1>Anthropic Launches Claude 3.5 Sonnet Update</h1>
              <p>Anthropic has released a significant update to their flagship Claude 3.5 Sonnet model.</p>
              <p>The new checkpoint demonstrates enhanced agentic reasoning and coding capabilities.</p>
            </main>
            <footer>&copy; 2026 Tech News</footer>
          </body>
        </html>
        """

        doc = RawDocument(
            source_name="TechCrunch AI",
            source_url="https://techcrunch.com/2026/08/28/anthropic-claude-update",
            raw_content=raw_html,
            http_status=200,
        )

        crawler = NewsCrawler()
        crawler._feed_entries = [{
            "url": doc.source_url,
            "source_name": "TechCrunch AI",
            "title": "Anthropic Launches Claude 3.5 Sonnet Update",
            "feed_published": pub_iso,
            "feed_summary": "Anthropic update",
        }]

        records = await crawler.parse(doc)
        assert len(records) == 1
        record = records[0]

        assert record["recordType"] == "NEWS"
        assert record["source"]["name"] == "TechCrunch AI"
        assert "Anthropic" in record["content"]["mentionedEntities"]
        assert "Claude 3.5 Sonnet" in record["content"]["title"]
        assert record["_metadata"]["age_hours"] <= 2.5
        assert "Home | AI" not in record["content"]["fullText"]

    @pytest.mark.asyncio
    async def test_stale_news_article_rejected_over_24h(self):
        """Article published 30 hours ago is rejected by the 24h filter."""
        now = datetime.now(timezone.utc)
        stale_iso = (now - timedelta(hours=30)).isoformat()

        raw_html = f"""
        <html>
          <head>
            <meta property="article:published_time" content="{stale_iso}" />
          </head>
          <body>
            <h1>Old AI News Story</h1>
            <p>This story broke yesterday morning.</p>
          </body>
        </html>
        """

        doc = RawDocument(
            source_name="VentureBeat AI",
            source_url="https://venturebeat.com/ai/old-news",
            raw_content=raw_html,
            http_status=200,
        )

        crawler = NewsCrawler()
        records = await crawler.parse(doc)
        assert len(records) == 0  # REJECTED due to age > 24h

    @pytest.mark.asyncio
    async def test_dateless_news_article_rejected(self):
        """Article without verifiable date across all 6 waterfall steps is rejected."""
        raw_html = """
        <html>
          <head><title>No Dates Here</title></head>
          <body>
            <h1>Dateless Article</h1>
            <p>Some interesting content without any dates or timestamps.</p>
          </body>
        </html>
        """

        doc = RawDocument(
            source_name="The Verge AI",
            source_url="https://theverge.com/ai/dateless-post",
            raw_content=raw_html,
            http_status=200,
        )

        crawler = NewsCrawler()
        records = await crawler.parse(doc)
        assert len(records) == 0  # REJECTED (never assumed)
