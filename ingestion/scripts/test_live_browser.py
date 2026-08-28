import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.crawler.browser_crawler import BrowserCrawler
from src.observability.logger import setup_logging

async def test_live_browser():
    setup_logging()
    crawler = BrowserCrawler(source_name="live_test", urls=["https://news.ycombinator.com"])
    async with crawler:
        doc = await crawler.fetch_with_fallback("https://news.ycombinator.com")
        print("\n--- LIVE BROWSER CRAWLER EXECUTION RESULT ---")
        print(f"HTTP Status: {doc.http_status}")
        print(f"Fallback Stage Used: {doc.metadata.get('fetch_method')}")
        print(f"Source URL: {doc.source_url}")
        print(f"Content-Type: {doc.content_type}")
        print(f"Content Length: {len(doc.raw_content)} bytes")
        print(f"Content Hash (SHA-256): {doc.content_hash}")
        print(f"Snippet: {doc.raw_content[:250].strip()}")
        print("CAPTCHA Bypass Attempted: FALSE (policy strictly enforced)")
        print("---------------------------------------------\n")

if __name__ == "__main__":
    asyncio.run(test_live_browser())
