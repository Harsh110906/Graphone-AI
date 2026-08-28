"""
Tests for the browser crawler (Playwright Async anti-bot fallback chain).

Tests cover (all mocked — no real browser needed for unit tests):
- Successful direct HTTP path (no browser needed)
- Challenge page detection (403/Cloudflare/DataDome signals)
- CAPTCHA detection and skip-and-log behavior
- Fallback chain progression: HTTP → API → Playwright → Skip
- Logging of all failure paths with full context
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.crawler.browser_crawler import (
    BrowserCrawler,
    _detect_captcha,
    _is_challenge_page,
)
from src.crawler.base import CrawlerError, RawDocument


# ═══════════════════════════════════════════════════════════════
# Challenge / CAPTCHA Detection Tests (Pure Functions)
# ═══════════════════════════════════════════════════════════════

class TestChallengeDetection:
    """Test bot/challenge page detection."""

    def test_cloudflare_challenge(self):
        html = '<div id="cf-browser-verification">Checking your browser...</div>'
        assert _is_challenge_page(html) is True

    def test_datadome_challenge(self):
        html = '<script src="https://js.datadome.co/tags.js"></script>'
        assert _is_challenge_page(html) is True

    def test_just_a_moment_challenge(self):
        html = "<html><body><h1>Just a moment...</h1><p>Checking your browser</p></body></html>"
        assert _is_challenge_page(html) is True

    def test_normal_page_not_challenge(self):
        html = "<html><body><h1>Welcome to our site</h1><p>Real content here</p></body></html>"
        assert _is_challenge_page(html) is False

    def test_access_denied(self):
        html = "<html><body><h1>Access Denied</h1></body></html>"
        assert _is_challenge_page(html) is True

    def test_empty_html(self):
        assert _is_challenge_page("") is False


class TestCaptchaDetection:
    """Test CAPTCHA type detection."""

    def test_recaptcha(self):
        html = '<div class="g-recaptcha" data-sitekey="abc123"></div>'
        assert _detect_captcha(html) == "reCAPTCHA"

    def test_hcaptcha(self):
        html = '<div class="h-captcha" data-sitekey="abc123"></div>'
        assert _detect_captcha(html) == "hCaptcha"

    def test_cloudflare_turnstile(self):
        html = '<div class="cf-turnstile" data-sitekey="abc123"></div>'
        assert _detect_captcha(html) == "Cloudflare Turnstile"

    def test_datadome_captcha(self):
        html = '<iframe src="https://geo.captcha-delivery.com/captcha/?initialCid=datadome"></iframe>'
        assert _detect_captcha(html) == "DataDome"

    def test_no_captcha(self):
        html = "<html><body><p>Normal content</p></body></html>"
        assert _detect_captcha(html) is None


# ═══════════════════════════════════════════════════════════════
# BrowserCrawler Fallback Chain Tests (Mocked)
# ═══════════════════════════════════════════════════════════════

class TestBrowserCrawlerFallback:
    """Test the fallback chain logic with mocked HTTP and Playwright."""

    @pytest.mark.asyncio
    async def test_http_success_no_browser_needed(self):
        """If direct HTTP succeeds, browser is never invoked."""
        crawler = BrowserCrawler(
            urls=["https://example.com"],
            headless=True,
        )

        # Mock the BaseCrawler.fetch to return a normal page
        normal_doc = RawDocument(
            source_name="browser",
            source_url="https://example.com",
            raw_content="<html><body><h1>Real Content</h1>" + "x" * 600 + "</body></html>",
            http_status=200,
        )

        with patch.object(crawler, "fetch", new_callable=AsyncMock, return_value=normal_doc):
            doc = await crawler.fetch_with_fallback("https://example.com")

        assert doc.http_status == 200
        assert doc.metadata.get("fetch_method") == "direct_http"

    @pytest.mark.asyncio
    async def test_http_blocked_triggers_playwright(self):
        """If HTTP returns 403, should attempt Playwright rendering."""
        crawler = BrowserCrawler(
            urls=["https://protected.com"],
            headless=True,
        )

        # Mock fetch to raise 403
        async def mock_fetch(url):
            raise CrawlerError("Forbidden", url=url, status_code=403)

        # Mock Playwright to return content
        playwright_doc = RawDocument(
            source_name="browser",
            source_url="https://protected.com",
            raw_content="<html><body><h1>Playwright Content</h1>" + "x" * 600 + "</body></html>",
            http_status=200,
            metadata={"fetch_method": "playwright_render"},
        )

        with patch.object(crawler, "fetch", side_effect=mock_fetch):
            with patch.object(
                crawler, "_render_with_playwright",
                new_callable=AsyncMock,
                return_value=playwright_doc,
            ):
                doc = await crawler.fetch_with_fallback("https://protected.com")

        assert doc.metadata.get("fetch_method") == "playwright_render"

    @pytest.mark.asyncio
    async def test_captcha_detection_skips_and_logs(self):
        """If Playwright detects a CAPTCHA, it should return None (skip)."""
        crawler = BrowserCrawler(
            urls=["https://captcha-site.com"],
            headless=True,
        )

        # Mock fetch to raise 403
        async def mock_fetch(url):
            raise CrawlerError("Forbidden", url=url, status_code=403)

        # Mock Playwright to return None (CAPTCHA detected)
        with patch.object(crawler, "fetch", side_effect=mock_fetch):
            with patch.object(
                crawler, "_render_with_playwright",
                new_callable=AsyncMock,
                return_value=None,  # CAPTCHA detected
            ):
                with pytest.raises(CrawlerError, match="All fetch methods failed"):
                    await crawler.fetch_with_fallback("https://captcha-site.com")

    @pytest.mark.asyncio
    async def test_api_alternative_used_before_playwright(self):
        """If an API alternative is registered, it should be tried before Playwright."""
        crawler = BrowserCrawler(
            urls=["https://news-site.com/article/123"],
            api_alternatives={"news-site.com": "https://news-site.com/api/articles/123"},
            headless=True,
        )

        # Mock fetch to:
        # 1. Fail with 403 for the original URL
        # 2. Succeed for the API URL
        api_doc = RawDocument(
            source_name="browser",
            source_url="https://news-site.com/api/articles/123",
            raw_content='{"title": "Test Article", "content": "Full text here"}',
            http_status=200,
            metadata={"fetch_method": "api_alternative"},
        )

        call_count = 0
        async def mock_fetch(url):
            nonlocal call_count
            call_count += 1
            if "api" in url:
                return api_doc
            raise CrawlerError("Forbidden", url=url, status_code=403)

        with patch.object(crawler, "fetch", side_effect=mock_fetch):
            doc = await crawler.fetch_with_fallback("https://news-site.com/article/123")

        assert doc.metadata.get("fetch_method") == "api_alternative"

    @pytest.mark.asyncio
    async def test_challenge_page_on_http_triggers_fallback(self):
        """If HTTP returns 200 but content is a challenge page, should try browser."""
        crawler = BrowserCrawler(
            urls=["https://cf-protected.com"],
            headless=True,
        )

        challenge_doc = RawDocument(
            source_name="browser",
            source_url="https://cf-protected.com",
            raw_content='<html><body><div id="cf-browser-verification">Just a moment...</div></body></html>',
            http_status=200,
        )

        real_doc = RawDocument(
            source_name="browser",
            source_url="https://cf-protected.com",
            raw_content="<html><body><h1>Real Content</h1>" + "x" * 600 + "</body></html>",
            http_status=200,
            metadata={"fetch_method": "playwright_render"},
        )

        with patch.object(crawler, "fetch", new_callable=AsyncMock, return_value=challenge_doc):
            with patch.object(
                crawler, "_render_with_playwright",
                new_callable=AsyncMock,
                return_value=real_doc,
            ):
                doc = await crawler.fetch_with_fallback("https://cf-protected.com")

        assert doc.metadata.get("fetch_method") == "playwright_render"


class TestBrowserCrawlerDiscovery:
    """Test URL discovery."""

    @pytest.mark.asyncio
    async def test_discover_yields_configured_urls(self):
        urls = ["https://a.com", "https://b.com", "https://c.com"]
        crawler = BrowserCrawler(urls=urls)

        discovered = []
        async for url in crawler.discover():
            discovered.append(url)

        assert discovered == urls

    @pytest.mark.asyncio
    async def test_discover_empty_yields_nothing(self):
        crawler = BrowserCrawler(urls=[])

        discovered = []
        async for url in crawler.discover():
            discovered.append(url)

        assert discovered == []
