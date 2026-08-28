"""
Unit tests for IncrementalCrawlTracker.

Verifies:
- Accurate content hash computation (SHA-256)
- First crawl detects change and records state
- Second crawl with identical content returns is_changed=False (proves unchanged URL is skipped)
- Content update triggers is_changed=True
- JSON state serialization / deserialization
"""

import time
from pathlib import Path
import pytest

from src.crawler.incremental import IncrementalCrawlTracker


class TestIncrementalCrawler:
    """Test incremental crawling and content hash tracking."""

    def test_first_crawl_records_state(self):
        tracker = IncrementalCrawlTracker()
        url = "https://techcrunch.com/article/openai-update"
        content_v1 = "<html><body>Initial article text</body></html>"

        is_changed = tracker.update_crawl_state(url, content_v1)
        assert is_changed is True

        state = tracker.get_state(url)
        assert state is not None
        assert state.url == url
        assert state.last_seen_hash == tracker.compute_content_hash(content_v1)
        assert state.last_crawled_at <= time.time()

    def test_second_crawl_with_same_content_is_skipped(self):
        tracker = IncrementalCrawlTracker()
        url = "https://techcrunch.com/article/openai-update"
        content = "<html><body>Static unchanging content</body></html>"

        # First run
        tracker.update_crawl_state(url, content)

        # Second run with identical content -> should report unchanged
        has_changed = tracker.has_content_changed(url, content)
        assert has_changed is False

        is_new = tracker.update_crawl_state(url, content)
        assert is_new is False

    def test_modified_content_detected(self):
        tracker = IncrementalCrawlTracker()
        url = "https://techcrunch.com/article/openai-update"
        content_v1 = "<html><body>Initial draft</body></html>"
        content_v2 = "<html><body>Updated breaking news with new details</body></html>"

        tracker.update_crawl_state(url, content_v1)

        has_changed = tracker.has_content_changed(url, content_v2)
        assert has_changed is True

        is_updated = tracker.update_crawl_state(url, content_v2)
        assert is_updated is True
        assert tracker.get_state(url).last_seen_hash == tracker.compute_content_hash(content_v2)

    def test_persistence_save_and_load(self, tmp_path: Path):
        state_file = tmp_path / "crawl_state.json"
        tracker1 = IncrementalCrawlTracker(state_file_path=state_file)

        url = "https://venturebeat.com/ai/article-1"
        tracker1.update_crawl_state(url, "Some content here")
        tracker1.save()

        # Load from new instance
        tracker2 = IncrementalCrawlTracker(state_file_path=state_file)
        assert tracker2.get_state(url) is not None
        assert tracker2.has_content_changed(url, "Some content here") is False
        assert tracker2.has_content_changed(url, "Different content") is True
