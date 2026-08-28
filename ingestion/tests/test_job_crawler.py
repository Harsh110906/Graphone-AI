"""
Unit tests for JobCrawler.

Verifies:
- Parsing of Greenhouse, Lever, and RemoteOK API responses
- 24-hour freshness filter on job postings
- Role family classification (Engineering, Research, Product, Sales, Design)
- Remote work flag detection
- Pydantic schema validation
"""

import json
from datetime import datetime, timedelta, timezone
import pytest

from src.crawler.base import RawDocument
from src.crawler.job_crawler import JobCrawler
from src.schemas.job import RoleFamily


class TestJobCrawler:
    """Test suite for JobCrawler API parsers and filters."""

    @pytest.mark.asyncio
    async def test_greenhouse_recently_edited_old_job_is_rejected_as_stale(self):
        """
        REGRESSION TEST: A job first published 3 days ago but edited/updated 1 hour ago
        MUST be classified as STALE and rejected under the 24-hour freshness rule.
        """
        now = datetime.now(timezone.utc)
        first_pub = (now - timedelta(days=3)).isoformat()
        updated_recently = (now - timedelta(hours=1)).isoformat()

        greenhouse_data = {
            "jobs": [
                {
                    "id": 201,
                    "title": "Senior AI Alignment Researcher",
                    "first_published": first_pub,       # 3 days ago -> STALE
                    "updated_at": updated_recently,     # 1 hour ago (edited/refreshed)
                    "absolute_url": "https://boards.greenhouse.io/anthropic/jobs/201",
                    "location": {"name": "San Francisco, CA"},
                }
            ]
        }

        doc = RawDocument(
            source_name="ai_jobs_aggregator",
            source_url="https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
            raw_content=json.dumps(greenhouse_data),
            http_status=200,
        )

        crawler = JobCrawler()
        records = await crawler.parse(doc)

        # Must be rejected because true creation date (first_published) is 3 days old!
        assert len(records) == 0

    @pytest.mark.asyncio
    async def test_greenhouse_truly_fresh_job_uses_first_published_date(self):
        """A job first published 2h ago uses first_published for content.date."""
        now = datetime.now(timezone.utc)
        first_pub_dt = now - timedelta(hours=2)
        updated_dt = now - timedelta(hours=1)

        greenhouse_data = {
            "jobs": [
                {
                    "id": 202,
                    "title": "Member of Technical Staff, Pre-training",
                    "first_published": first_pub_dt.isoformat(),
                    "updated_at": updated_dt.isoformat(),
                    "absolute_url": "https://boards.greenhouse.io/anthropic/jobs/202",
                    "location": {"name": "San Francisco, CA"},
                }
            ]
        }

        doc = RawDocument(
            source_name="ai_jobs_aggregator",
            source_url="https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
            raw_content=json.dumps(greenhouse_data),
            http_status=200,
        )

        crawler = JobCrawler()
        records = await crawler.parse(doc)

        assert len(records) == 1
        record = records[0]
        # Assert content.date is populated from first_published (2h ago, not 1h ago)
        assert record["_metadata"]["date_source_field"] == "first_published"
        assert record["content"]["date"] == first_pub_dt.isoformat()
        assert record["content"]["role_family"] == "Engineering"

    @pytest.mark.asyncio
    async def test_greenhouse_fallback_when_first_published_missing(self):
        """If first_published is null/missing, fallback to updated_at."""
        now = datetime.now(timezone.utc)
        updated_dt = now - timedelta(hours=2)

        greenhouse_data = {
            "jobs": [
                {
                    "id": 203,
                    "title": "Product Manager, Developer Platform",
                    "first_published": None,  # Missing
                    "updated_at": updated_dt.isoformat(),
                    "absolute_url": "https://boards.greenhouse.io/anthropic/jobs/203",
                    "location": {"name": "San Francisco, CA"},
                }
            ]
        }

        doc = RawDocument(
            source_name="ai_jobs_aggregator",
            source_url="https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
            raw_content=json.dumps(greenhouse_data),
            http_status=200,
        )

        crawler = JobCrawler()
        records = await crawler.parse(doc)

        assert len(records) == 1
        record = records[0]
        assert record["_metadata"]["date_source_field"] == "updated_at"
        assert record["content"]["date"] == updated_dt.isoformat()
        assert record["content"]["role_family"] == "Product"

    @pytest.mark.asyncio
    async def test_remoteok_remote_job_parsed(self):
        now = datetime.now(timezone.utc)
        fresh_time = (now - timedelta(hours=1.5)).isoformat()

        remoteok_data = [
            {"legal": "Notice"},
            {
                "id": "rok_1",
                "company": "DeepMind Partner Lab",
                "position": "Senior ML Platform Engineer",
                "tags": ["python", "ai", "kubernetes"],
                "date": fresh_time,
                "url": "https://remoteok.com/remote-jobs/12345",
                "location": "Worldwide",
            }
        ]

        doc = RawDocument(
            source_name="ai_jobs_aggregator",
            source_url="https://remoteok.com/api?tag=ai",
            raw_content=json.dumps(remoteok_data),
            http_status=200,
        )

        crawler = JobCrawler()
        records = await crawler.parse(doc)

        assert len(records) == 1
        job = records[0]

        assert job["content"]["is_remote"] is True
        assert job["content"]["role_family"] == "Engineering"
        assert job["content"]["company"] == "DeepMind Partner Lab"

    def test_role_family_classification(self):
        """Verify role family categorization logic."""
        assert JobCrawler._classify_role_family("Staff Research Scientist") == RoleFamily.RESEARCH
        assert JobCrawler._classify_role_family("Senior Backend Infrastructure Engineer") == RoleFamily.ENGINEERING
        assert JobCrawler._classify_role_family("Group Product Manager - GenAI") == RoleFamily.PRODUCT
        assert JobCrawler._classify_role_family("Lead Product Designer") == RoleFamily.DESIGN
        assert JobCrawler._classify_role_family("Enterprise Account Executive - AI") == RoleFamily.SALES
        assert JobCrawler._classify_role_family("Director of People Operations") == RoleFamily.OPERATIONS
