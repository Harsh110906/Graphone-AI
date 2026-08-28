"""
Abstract base crawler interface.

All crawlers must subclass BaseCrawler and implement the abstract methods.
New sources are added by creating a new subclass — zero changes to core logic.

Features built into the base:
- Async HTTP client with timeout and retry
- Per-domain rate limiting
- Structured error logging
- Retry with exponential backoff and jitter
"""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

import httpx
import structlog

from src.config import settings
from src.crawler.rate_limiter import DomainRateLimiter

logger = structlog.get_logger(__name__)


@dataclass
class RawDocument:
    """A raw document fetched from a source, before any extraction."""

    id: UUID = field(default_factory=uuid4)
    source_name: str = ""
    source_url: str = ""
    content_type: str = ""          # e.g., "text/html", "application/xml"
    raw_content: str = ""
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    http_status: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """SHA-256 hash of raw content for dedup and change detection."""
        import hashlib
        return hashlib.sha256(self.raw_content.encode("utf-8")).hexdigest()


class CrawlerError(Exception):
    """Base exception for crawler errors."""

    def __init__(self, message: str, url: str = "", status_code: int = 0):
        self.url = url
        self.status_code = status_code
        super().__init__(message)


class BaseCrawler(ABC):
    """
    Abstract base class for all crawlers.

    Subclass this to add a new source. You must implement:
    - discover(): yields URLs or items to crawl
    - parse(doc: RawDocument): extracts structured data from a raw document

    The base class provides:
    - fetch(): HTTP fetching with retry, timeout, and rate limiting
    - run(): orchestrates discover → fetch → parse with concurrency control
    """

    def __init__(
        self,
        source_name: str,
        rate_limiter: DomainRateLimiter | None = None,
        max_retries: int | None = None,
        timeout_seconds: int | None = None,
        concurrency: int | None = None,
    ):
        self.source_name = source_name
        self.rate_limiter = rate_limiter or DomainRateLimiter()
        self.max_retries = max_retries or settings.crawler_max_retries
        self.timeout_seconds = timeout_seconds or settings.crawler_default_timeout_seconds
        self.concurrency = concurrency or settings.crawler_per_domain_concurrency
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                headers={
                    "User-Agent": settings.crawler_user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=self.concurrency * 2,
                    max_keepalive_connections=self.concurrency,
                ),
            )
        return self._client

    async def fetch(self, url: str) -> RawDocument:
        """
        Fetch a URL with retry, backoff, and rate limiting.

        Retry strategy: exponential backoff with jitter.
        delay = min(max_delay, base * 2^attempt) + random_jitter
        Respects Retry-After header when present.
        """
        # Handle local file protocols directly
        if url.startswith("local://") or url.startswith("file://"):
            clean_rel = url.replace("local://", "").replace("file://", "")
            p = Path(clean_rel)
            if not p.is_absolute():
                p = Path(__file__).resolve().parent.parent.parent / clean_rel
                if not p.exists():
                    p = Path(__file__).resolve().parent.parent.parent / "data" / clean_rel
            if p.exists():
                content = p.read_text(encoding="utf-8")
                return RawDocument(
                    source_name=self.source_name,
                    source_url=url,
                    raw_content=content,
                    content_type="application/json" if p.suffix == ".json" else "text/plain",
                    http_status=200,
                )

        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                async with asyncio.timeout(self.timeout_seconds + 10):
                    # Acquire rate-limit slot
                    await self.rate_limiter.acquire(url)
                    try:
                        response = await client.get(url)
                    finally:
                        self.rate_limiter.release(url)

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait = self._compute_backoff(attempt, retry_after)
                    logger.warning(
                        "rate_limited_429",
                        url=url,
                        attempt=attempt,
                        wait_seconds=round(wait, 2),
                        retry_after_header=retry_after,
                    )
                    await asyncio.sleep(wait)
                    continue

                if response.status_code == 413:
                    logger.error(
                        "payload_too_large_413",
                        url=url,
                        status=413,
                    )
                    raise CrawlerError("Payload too large", url=url, status_code=413)

                response.raise_for_status()

                return RawDocument(
                    source_name=self.source_name,
                    source_url=url,
                    content_type=response.headers.get("content-type", ""),
                    raw_content=response.text,
                    http_status=response.status_code,
                    headers=dict(response.headers),
                )

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code >= 500:
                    wait = self._compute_backoff(attempt)
                    logger.warning(
                        "server_error_retry",
                        url=url,
                        status=e.response.status_code,
                        attempt=attempt,
                        wait_seconds=round(wait, 2),
                    )
                    await asyncio.sleep(wait)
                    continue
                raise CrawlerError(
                    str(e), url=url, status_code=e.response.status_code
                ) from e

            except (httpx.ConnectError, httpx.ReadTimeout, asyncio.TimeoutError) as e:
                last_error = e
                wait = self._compute_backoff(attempt)
                logger.warning(
                    "connection_error_retry",
                    url=url,
                    error_type=type(e).__name__,
                    attempt=attempt,
                    wait_seconds=round(wait, 2),
                )
                await asyncio.sleep(wait)
                continue

            except Exception as e:
                logger.error(
                    "fetch_unexpected_error",
                    url=url,
                    error_type=type(e).__name__,
                    error=str(e),
                )
                raise CrawlerError(str(e), url=url) from e

        raise CrawlerError(
            f"All {self.max_retries + 1} attempts failed for {url}: {last_error}",
            url=url,
        )

    @staticmethod
    def _compute_backoff(
        attempt: int,
        retry_after: str | None = None,
        base: float = 1.0,
        max_delay: float = 60.0,
    ) -> float:
        """
        Compute backoff delay with exponential increase and jitter.

        delay = min(max_delay, base * 2^attempt) + random_jitter
        If Retry-After header is present and parseable, use it as minimum.
        """
        delay = min(max_delay, base * (2 ** attempt))
        jitter = random.uniform(0, delay * 0.3)
        backoff = delay + jitter

        if retry_after:
            try:
                retry_seconds = float(retry_after)
                backoff = max(backoff, retry_seconds)
            except ValueError:
                pass  # Retry-After might be a date — ignore for now

        return backoff

    @abstractmethod
    async def discover(self) -> AsyncIterator[str]:
        """
        Yield URLs or identifiers to crawl.

        Subclasses implement source-specific discovery logic
        (e.g., API pagination, RSS feed parsing, sitemap walking).
        """
        yield ""  # pragma: no cover

    @abstractmethod
    async def parse(self, doc: RawDocument) -> list[dict[str, Any]]:
        """
        Parse a raw document into structured records.

        Returns a list of dicts conforming to the appropriate schema.
        Subclasses must never invent values — return null for missing fields.
        """
        ...  # pragma: no cover

    async def run(self, max_items: int | None = None) -> AsyncIterator[dict[str, Any]]:
        """
        Full crawl pipeline: discover → fetch → parse.

        Runs with bounded concurrency via asyncio.Semaphore.
        """
        semaphore = asyncio.Semaphore(self.concurrency)
        count = 0

        async def process_url(url: str) -> list[dict[str, Any]]:
            async with semaphore:
                try:
                    doc = await self.fetch(url)
                    return await self.parse(doc)
                except CrawlerError as e:
                    logger.error(
                        "crawl_item_failed",
                        source=self.source_name,
                        url=url,
                        error=str(e),
                        status_code=e.status_code,
                    )
                    return []

        async for url in self.discover():
            if max_items and count >= max_items:
                break

            results = await process_url(url)
            for record in results:
                yield record
                count += 1
                if max_items and count >= max_items:
                    return

    async def close(self) -> None:
        """Clean up HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "BaseCrawler":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
