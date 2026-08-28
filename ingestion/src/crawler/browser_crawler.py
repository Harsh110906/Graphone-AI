"""
Playwright Async browser crawler — anti-bot fallback chain.

Implements the full fallback chain per Correction 1:
1. Attempt direct HTTP request (httpx) first
2. If blocked (403/429/challenge page detected) → attempt official API/RSS alternative
3. If none → render with Playwright Async (realistic UA, viewport, randomized delays)
4. If CAPTCHA detected → log with full context and skip — never bypass

Low concurrency: max 1-2 concurrent browser contexts to avoid triggering defenses.
"""

from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import httpx
import structlog

from src.crawler.base import BaseCrawler, CrawlerError, RawDocument
from src.crawler.rate_limiter import DomainRateLimiter

logger = structlog.get_logger(__name__)

# Signals that indicate a challenge/block page
CHALLENGE_SIGNALS = [
    "cf-browser-verification",
    "cf-challenge-running",
    "challenge-platform",
    "just a moment",
    "checking your browser",
    "verify you are human",
    "captcha",
    "recaptcha",
    "hcaptcha",
    "datadome",
    "access denied",
    "please complete the security check",
]

# Realistic browser viewport/UA configurations
BROWSER_CONFIGS = [
    {
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
    },
    {
        "viewport": {"width": 1440, "height": 900},
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
    },
    {
        "viewport": {"width": 1366, "height": 768},
        "user_agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
    },
]


def _is_challenge_page(html: str) -> bool:
    """
    Detect if a page is a bot-challenge / CAPTCHA page.

    Checks for known challenge platform markers in the HTML.
    """
    html_lower = html.lower()
    for signal in CHALLENGE_SIGNALS:
        if signal in html_lower:
            return True
    return False


def _detect_captcha(html: str) -> Optional[str]:
    """
    Detect specific CAPTCHA types in the page.

    Returns the CAPTCHA type string if detected, None otherwise.
    """
    html_lower = html.lower()
    if "recaptcha" in html_lower or "g-recaptcha" in html_lower:
        return "reCAPTCHA"
    if "hcaptcha" in html_lower or "h-captcha" in html_lower:
        return "hCaptcha"
    if "cf-turnstile" in html_lower:
        return "Cloudflare Turnstile"
    if "datadome" in html_lower:
        return "DataDome"
    return None


class BrowserCrawler(BaseCrawler):
    """
    Playwright-based browser crawler with the full anti-bot fallback chain.

    Fallback order:
    1. Direct HTTP request (httpx) — fastest, preferred
    2. Official API/RSS alternative (if registered for this domain)
    3. Playwright Async rendering — realistic browser simulation
    4. Skip and log — if CAPTCHA detected, never bypass

    Args:
        headless: Run browser in headless mode. Set False for stubborn sources.
        max_browser_contexts: Max concurrent browser contexts (1-2 recommended).
        api_alternatives: Dict mapping domain → API/RSS URL to try before browser rendering.
    """

    def __init__(
        self,
        source_name: str = "browser",
        headless: bool = True,
        max_browser_contexts: int = 2,
        api_alternatives: dict[str, str] | None = None,
        rate_limiter: DomainRateLimiter | None = None,
        urls: list[str] | None = None,
    ):
        limiter = rate_limiter or DomainRateLimiter(
            requests_per_second=0.5,  # Very conservative for browser crawling
            max_concurrent=max_browser_contexts,
            burst=1,
        )
        super().__init__(
            source_name=source_name,
            rate_limiter=limiter,
            max_retries=2,
            timeout_seconds=45,
            concurrency=max_browser_contexts,
        )
        self.headless = headless
        self.max_browser_contexts = max_browser_contexts
        self.api_alternatives = api_alternatives or {}
        self._urls = urls or []
        self._browser_semaphore = asyncio.Semaphore(max_browser_contexts)

    async def discover(self) -> AsyncIterator[str]:
        """Yield URLs provided at construction time."""
        for url in self._urls:
            yield url

    async def parse(self, doc: RawDocument) -> list[dict[str, Any]]:
        """
        Basic content extraction from the rendered page.

        Returns the raw HTML content as a record. Subclasses or downstream
        processors handle domain-specific extraction.
        """
        return [{
            "source_url": doc.source_url,
            "source_name": doc.source_name,
            "raw_content": doc.raw_content,
            "fetched_at": doc.fetched_at.isoformat(),
            "content_hash": doc.content_hash,
            "fetch_method": doc.metadata.get("fetch_method", "unknown"),
        }]

    async def fetch_with_fallback(self, url: str) -> RawDocument:
        """
        Full anti-bot fallback chain for a single URL.

        1. Direct HTTP → 2. API/RSS alternative → 3. Playwright → 4. Skip+log
        """
        from urllib.parse import urlparse

        domain = urlparse(url).netloc

        # ── Step 1: Direct HTTP request ──
        logger.info("browser_crawler_step1_http", url=url)
        try:
            doc = await self.fetch(url)  # Uses BaseCrawler.fetch with retry/backoff

            if _is_challenge_page(doc.raw_content):
                logger.warning(
                    "challenge_page_detected_on_http",
                    url=url,
                    status=doc.http_status,
                )
            elif doc.http_status == 200 and len(doc.raw_content) > 500:
                doc.metadata["fetch_method"] = "direct_http"
                logger.info("browser_crawler_http_success", url=url, size=len(doc.raw_content))
                return doc

        except CrawlerError as e:
            if e.status_code not in (403, 429, 503):
                # Non-block error — don't try browser rendering
                logger.error(
                    "browser_crawler_http_error_non_block",
                    url=url,
                    status=e.status_code,
                    error=str(e),
                )
                raise
            logger.warning(
                "browser_crawler_http_blocked",
                url=url,
                status=e.status_code,
            )

        # ── Step 2: API/RSS alternative ──
        api_url = self.api_alternatives.get(domain)
        if api_url:
            logger.info("browser_crawler_step2_api", url=url, api_url=api_url)
            try:
                doc = await self.fetch(api_url)
                doc.metadata["fetch_method"] = "api_alternative"
                doc.metadata["original_url"] = url
                logger.info("browser_crawler_api_success", url=api_url)
                return doc
            except CrawlerError as e:
                logger.warning(
                    "browser_crawler_api_failed",
                    api_url=api_url,
                    error=str(e),
                )

        # ── Step 3: Playwright rendering ──
        logger.info("browser_crawler_step3_playwright", url=url, headless=self.headless)
        try:
            doc = await self._render_with_playwright(url)
            if doc is not None:
                return doc
        except Exception as e:
            logger.error(
                "browser_crawler_playwright_error",
                url=url,
                error_type=type(e).__name__,
                error=str(e),
            )

        # ── Step 4: Skip and log ──
        logger.error(
            "browser_crawler_all_methods_failed",
            url=url,
            fallback_chain=["direct_http", "api_alternative", "playwright"],
            action="SKIPPED",
            reason="All fetch methods exhausted. URL skipped — no CAPTCHA bypass attempted.",
        )
        raise CrawlerError(
            f"All fetch methods failed for {url}. Skipped.",
            url=url,
            status_code=0,
        )

    async def _render_with_playwright(self, url: str) -> RawDocument | None:
        """
        Render a page using Playwright Async.

        Uses realistic browser config, randomized delays, and low concurrency.
        If CAPTCHA is detected, logs and returns None — never attempts to solve it.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "playwright_not_installed",
                url=url,
                action="SKIPPED",
                hint="Install with: pip install playwright && playwright install chromium",
            )
            return None

        config = random.choice(BROWSER_CONFIGS)

        async with self._browser_semaphore:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                try:
                    context = await browser.new_context(
                        viewport=config["viewport"],
                        user_agent=config["user_agent"],
                        locale="en-US",
                        timezone_id="America/New_York",
                    )
                    page = await context.new_page()

                    # Randomized delay before navigation (0.5-2.0 seconds)
                    await asyncio.sleep(random.uniform(0.5, 2.0))

                    response = await page.goto(url, wait_until="networkidle", timeout=30000)

                    if response is None:
                        logger.warning("playwright_no_response", url=url)
                        return None

                    # Wait a bit for any lazy-loaded content
                    await asyncio.sleep(random.uniform(1.0, 3.0))

                    html = await page.content()
                    status = response.status

                    # Check for CAPTCHA
                    captcha_type = _detect_captcha(html)
                    if captcha_type:
                        logger.error(
                            "captcha_detected",
                            url=url,
                            captcha_type=captcha_type,
                            status=status,
                            action="SKIPPED",
                            reason=f"{captcha_type} detected — no bypass attempted per policy",
                        )
                        return None

                    # Check for challenge page
                    if _is_challenge_page(html):
                        logger.warning(
                            "challenge_page_after_render",
                            url=url,
                            status=status,
                            action="SKIPPED",
                            reason="Challenge page persists after browser rendering",
                        )
                        return None

                    if len(html) < 500:
                        logger.warning(
                            "playwright_empty_page",
                            url=url,
                            content_length=len(html),
                        )
                        return None

                    doc = RawDocument(
                        source_name=self.source_name,
                        source_url=url,
                        content_type="text/html",
                        raw_content=html,
                        http_status=status,
                        headers=dict(response.headers) if response.headers else {},
                        metadata={"fetch_method": "playwright_render"},
                    )

                    logger.info(
                        "playwright_render_success",
                        url=url,
                        status=status,
                        content_length=len(html),
                    )

                    return doc

                finally:
                    await browser.close()

    async def run(self, max_items: int | None = None) -> AsyncIterator[dict[str, Any]]:
        """
        Override run to use fetch_with_fallback instead of plain fetch.
        """
        count = 0
        async for url in self.discover():
            if max_items and count >= max_items:
                break
            try:
                doc = await self.fetch_with_fallback(url)
                results = await self.parse(doc)
                for record in results:
                    yield record
                    count += 1
                    if max_items and count >= max_items:
                        return
            except CrawlerError as e:
                logger.error(
                    "browser_crawl_item_skipped",
                    url=url,
                    error=str(e),
                )
