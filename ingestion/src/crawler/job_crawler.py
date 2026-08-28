"""
AI Jobs crawler supporting 5 reputable official job endpoints with strict 24-hour freshness enforcement.

Sources:
1. Greenhouse Public Board API — OpenAI (https://boards-api.greenhouse.io/v1/boards/openai/jobs)
2. Greenhouse Public Board API — Anthropic (https://boards-api.greenhouse.io/v1/boards/anthropic/jobs)
3. Greenhouse Public Board API — Scale AI (https://boards-api.greenhouse.io/v1/boards/scaleai/jobs)
4. Lever Public Board API — Cohere (https://api.lever.co/v0/postings/cohere?mode=json)
5. RemoteOK AI Jobs API (https://remoteok.com/api?tag=ai)

Process:
Endpoint Fetch -> Extract Timestamps -> 24h Freshness Filter -> Role Family Classification -> Remote Status Detection -> Pydantic Schema Validation.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

import structlog

from src.crawler.base import BaseCrawler, CrawlerError, RawDocument
from src.crawler.date_extractor import parse_datetime_to_utc, check_24h_freshness
from src.crawler.rate_limiter import DomainRateLimiter
from src.schemas.job import Job, JobContent, RoleFamily
from src.schemas.startup import Source

logger = structlog.get_logger(__name__)

# 5 Configured AI Job Board Endpoints
AI_JOB_SOURCES = [
    {
        "company": "Anthropic",
        "type": "greenhouse",
        "api_url": "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        "domain": "anthropic.com",
    },
    {
        "company": "Scale AI",
        "type": "greenhouse",
        "api_url": "https://boards-api.greenhouse.io/v1/boards/scaleai/jobs",
        "domain": "scale.com",
    },
    {
        "company": "Databricks",
        "type": "greenhouse",
        "api_url": "https://boards-api.greenhouse.io/v1/boards/databricks/jobs",
        "domain": "databricks.com",
    },
    {
        "company": "Together AI",
        "type": "greenhouse",
        "api_url": "https://boards-api.greenhouse.io/v1/boards/togetherai/jobs",
        "domain": "together.ai",
    },
    {
        "company": "RemoteOK AI",
        "type": "remoteok",
        "api_url": "https://remoteok.com/api?tag=ai",
        "domain": "remoteok.com",
    },
]


class JobCrawler(BaseCrawler):
    """
    Crawler for multi-source AI job postings with guaranteed 24-hour freshness.
    """

    def __init__(
        self,
        sources: List[Dict[str, str]] | None = None,
        max_age_hours: float = 24.0,
        rate_limiter: DomainRateLimiter | None = None,
    ):
        limiter = rate_limiter or DomainRateLimiter(
            requests_per_second=1.0,
            max_concurrent=2,
            burst=2,
        )
        super().__init__(
            source_name="ai_jobs_aggregator",
            rate_limiter=limiter,
            max_retries=2,
            timeout_seconds=25,
            concurrency=2,
        )
        self.sources = sources or AI_JOB_SOURCES
        self.max_age_hours = max_age_hours

    async def discover(self) -> AsyncIterator[str]:
        """Yield configured API endpoints."""
        for src in self.sources:
            yield src["api_url"]

    async def parse(self, doc: RawDocument) -> list[dict[str, Any]]:
        """
        Parse structured JSON responses from Greenhouse, Lever, and RemoteOK job endpoints.
        Enforces verified timestamp within the 24h freshness window.
        """
        url = doc.source_url
        src_config = next((s for s in self.sources if s["api_url"] == url), None)
        if not src_config:
            return []

        job_type = src_config["type"]
        company = src_config["company"]
        records: list[dict[str, Any]] = []

        try:
            data = json.loads(doc.raw_content)
        except json.JSONDecodeError as e:
            logger.error("job_json_parse_error", url=url, error=str(e))
            return []

        if job_type == "greenhouse":
            records.extend(self._parse_greenhouse_jobs(data, company, src_config))
        elif job_type == "lever":
            records.extend(self._parse_lever_jobs(data, company, src_config))
        elif job_type == "remoteok":
            records.extend(self._parse_remoteok_jobs(data, src_config))

        return records

    def _parse_greenhouse_jobs(
        self,
        data: dict[str, Any],
        company: str,
        src_config: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Parse Greenhouse API jobs list."""
        jobs_list = data.get("jobs", [])
        valid_records = []

        for item in jobs_list:
            job_url = item.get("absolute_url")
            if not job_url:
                continue

            title = item.get("title", "")
            first_pub_str = item.get("first_published")
            updated_at_str = item.get("updated_at")

            # Strict Precedence: first_published (original creation) -> fallback to updated_at only if missing/null
            job_date = parse_datetime_to_utc(first_pub_str)
            date_source = "first_published"
            if not job_date:
                job_date = parse_datetime_to_utc(updated_at_str)
                date_source = "updated_at"

            # Freshness check against the true creation timestamp
            if not job_date:
                logger.debug("greenhouse_job_no_date", url=job_url)
                continue

            is_fresh, age_hours = check_24h_freshness(job_date, max_age_hours=self.max_age_hours)
            if not is_fresh:
                continue

            # Location & Remote status
            location_info = item.get("location", {}).get("name", "")
            is_remote = self._detect_remote(location_info + " " + title)
            role_family = self._classify_role_family(title)

            record = self._build_job_record(
                company=company,
                title=title,
                job_url=job_url,
                source_name=f"{company} Careers",
                date=job_date,
                age_hours=age_hours,
                is_remote=is_remote,
                role_family=role_family,
                location=location_info,
            )
            if record:
                record["_metadata"]["date_source_field"] = date_source
                valid_records.append(record)

        logger.info(
            "greenhouse_jobs_parsed",
            company=company,
            total_found=len(jobs_list),
            fresh_24h_count=len(valid_records),
        )
        return valid_records

    def _parse_lever_jobs(
        self,
        data: list[dict[str, Any]],
        company: str,
        src_config: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Parse Lever API postings."""
        if not isinstance(data, list):
            return []

        valid_records = []
        for item in data:
            job_url = item.get("hostedUrl") or item.get("applyUrl")
            if not job_url:
                continue

            title = item.get("text", "")
            created_at_epoch = item.get("createdAt")  # Lever gives epoch ms
            job_date = None
            if created_at_epoch:
                try:
                    job_date = datetime.fromtimestamp(created_at_epoch / 1000.0, tz=timezone.utc)
                except Exception:
                    pass

            if not job_date:
                continue

            is_fresh, age_hours = check_24h_freshness(job_date, max_age_hours=self.max_age_hours)
            if not is_fresh:
                continue

            categories = item.get("categories", {})
            location_info = categories.get("location", "")
            is_remote = categories.get("workplaceType", "").lower() == "remote" or self._detect_remote(location_info + " " + title)
            role_family = self._classify_role_family(title + " " + categories.get("team", ""))

            record = self._build_job_record(
                company=company,
                title=title,
                job_url=job_url,
                source_name=f"{company} Lever",
                date=job_date,
                age_hours=age_hours,
                is_remote=is_remote,
                role_family=role_family,
                location=location_info,
            )
            if record:
                valid_records.append(record)

        logger.info(
            "lever_jobs_parsed",
            company=company,
            total_found=len(data),
            fresh_24h_count=len(valid_records),
        )
        return valid_records

    def _parse_remoteok_jobs(
        self,
        data: list[dict[str, Any]],
        src_config: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Parse RemoteOK JSON feed."""
        if not isinstance(data, list):
            return []

        valid_records = []
        # First element is legal disclaimer/metadata
        items = data[1:] if len(data) > 1 and "legal" in data[0] else data

        for item in items:
            if not isinstance(item, dict):
                continue

            job_url = item.get("url")
            if not job_url:
                continue

            company = item.get("company", "Remote Company")
            title = item.get("position", "")
            date_str = item.get("date")  # ISO format string
            job_date = parse_datetime_to_utc(date_str)

            if not job_date:
                continue

            is_fresh, age_hours = check_24h_freshness(job_date, max_age_hours=self.max_age_hours)
            if not is_fresh:
                continue

            location_info = item.get("location", "Remote")
            is_remote = True  # RemoteOK is inherently remote
            role_family = self._classify_role_family(title + " " + " ".join(item.get("tags", [])))

            record = self._build_job_record(
                company=company,
                title=title,
                job_url=job_url,
                source_name="RemoteOK",
                date=job_date,
                age_hours=age_hours,
                is_remote=is_remote,
                role_family=role_family,
                location=location_info,
            )
            if record:
                valid_records.append(record)

        logger.info(
            "remoteok_jobs_parsed",
            total_found=len(items),
            fresh_24h_count=len(valid_records),
        )
        return valid_records

    @staticmethod
    def _detect_remote(text: str) -> bool:
        """Detect remote work allowance from location string or title."""
        pattern = r"\b(remote|anywhere|wfh|telecommute|distributed)\b"
        return bool(re.search(pattern, text, re.IGNORECASE))

    @staticmethod
    def _classify_role_family(text: str) -> RoleFamily:
        """Classify job title into structured RoleFamily enum."""
        text_lower = text.lower()

        # 1. Product
        if any(w in text_lower for w in ["product manager", "product lead", "head of product", "group product manager", "director of product", "vp of product", "technical product manager", "pm "]):
            return RoleFamily.PRODUCT

        # 2. Design
        if any(w in text_lower for w in ["designer", "design lead", "ui/ux", "product designer", "creative director"]):
            return RoleFamily.DESIGN

        # 3. Research
        if any(w in text_lower for w in ["research scientist", "research engineer", "scientist", "phd", "fellow", "postdoc", "alignment researcher", "research fellow"]):
            return RoleFamily.RESEARCH

        # 4. Data
        if any(w in text_lower for w in ["data analyst", "data scientist", "analytics", "bi analyst", "business intelligence"]):
            return RoleFamily.DATA

        # 5. Sales & GTM
        if any(w in text_lower for w in ["sales", "account executive", "business development", "bdr", "sdr", "partnerships", "deal desk", "gtm "]):
            return RoleFamily.SALES

        # 6. Marketing & DevRel
        if any(w in text_lower for w in ["marketing", "growth", "content", "community", "developer advocate", "devrel"]):
            return RoleFamily.MARKETING

        # 7. Operations & Legal & People
        if any(w in text_lower for w in ["operations", "finance", "legal", "counsel", "hr", "recruiting", "talent", "people ops", "compliance"]):
            return RoleFamily.OPERATIONS

        # 8. Engineering (Default tech role)
        if any(w in text_lower for w in ["engineer", "developer", "backend", "frontend", "fullstack", "infrastructure", "systems", "mlops", "devops", "platform", "architect", "programmer", "software"]):
            return RoleFamily.ENGINEERING

        return RoleFamily.ENGINEERING

    def _build_job_record(
        self,
        company: str,
        title: str,
        job_url: str,
        source_name: str,
        date: datetime,
        age_hours: float,
        is_remote: bool,
        role_family: RoleFamily,
        location: str = "",
    ) -> Optional[dict[str, Any]]:
        """Validate and construct a schema-compliant Job record."""
        collected_at = datetime.now(timezone.utc)

        record = {
            "schemaVersion": "1.0",
            "recordType": "JOB",
            "source": {
                "name": source_name,
                "url": job_url,
            },
            "content": {
                "company": company,
                "date": date.isoformat(),
                "is_remote": is_remote,
                "role_family": role_family.value,
            },
            "collectedAt": collected_at.isoformat(),
            "_metadata": {
                "job_title": title,
                "location": location,
                "age_hours": round(age_hours, 2),
            },
        }

        # Pydantic schema validation
        try:
            Job(
                schemaVersion="1.0",
                recordType="JOB",
                source=Source(name=source_name, url=job_url),
                content=JobContent(
                    company=company,
                    date=date,
                    is_remote=is_remote,
                    role_family=role_family,
                ),
                collectedAt=collected_at,
            )
            return record
        except Exception as e:
            logger.error("job_schema_validation_error", url=job_url, error=str(e))
            return None
